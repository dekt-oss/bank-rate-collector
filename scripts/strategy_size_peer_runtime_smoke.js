const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("@playwright/test");

const baseUrl = process.env.STRATEGY_PREVIEW_BASE_URL || "http://127.0.0.1:4173";
const workDir = path.resolve("work");
fs.mkdirSync(workDir, { recursive: true });

function invariant(condition, message) {
  if (!condition) throw new Error(message);
}

async function openStrategy(browser, viewport) {
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  const runtimeErrors = [];
  page.on("pageerror", (error) => runtimeErrors.push(`pageerror: ${error.message}`));
  page.on("console", (message) => {
    if (message.type() === "error") runtimeErrors.push(`console: ${message.text()}`);
  });
  await page.route("**/favicon.ico", (route) => route.fulfill({ status: 204, body: "" }));
  const response = await page.goto(`${baseUrl}/strategy.html`, { waitUntil: "networkidle" });
  invariant(response && response.ok(), `strategy.html HTTP ${response ? response.status() : "none"}`);
  await page.waitForSelector("#strategy-rate-decision-simulator", { timeout: 30_000 });
  await page.waitForSelector("#rds-size-peers", { timeout: 30_000 });
  return { context, page, runtimeErrors };
}

async function readPayload(page) {
  return page.evaluate(() => {
    const node = document.getElementById("rate-monitor-data");
    if (!node) throw new Error("rate-monitor-data missing");
    const data = JSON.parse(String(node.textContent || "").replace(/<\\\//g, "</"));
    return data.strategy?.size_peer || null;
  });
}

function expectedIds(payload, mode) {
  return (payload.modes?.[mode]?.display_rows || []).map((row) => String(row.institution_id));
}

async function renderedIds(page) {
  return page.locator("#rds-size-peers [data-size-peer-id]").evaluateAll((rows) =>
    rows.map((row) => String(row.getAttribute("data-size-peer-id") || "")),
  );
}

async function assertMode(page, payload, mode, label) {
  const selector = `[data-size-peer-mode="${mode}"]`;
  await page.locator(selector).click();
  await page.waitForFunction(
    ({ selector }) => document.querySelector(selector)?.classList.contains("active"),
    { selector },
    { timeout: 5_000 },
  );
  const modePayload = payload.modes?.[mode];
  invariant(modePayload?.status === "ready", `${label}: payload mode is not ready`);
  const expected = expectedIds(payload, mode);
  invariant(expected.length > 0, `${label}: payload display rows are empty`);
  await page.waitForFunction(
    (count) => document.querySelectorAll("#rds-size-peers [data-size-peer-id]").length === count,
    expected.length,
    { timeout: 5_000 },
  );
  const actual = await renderedIds(page);
  invariant(JSON.stringify(actual) === JSON.stringify(expected), `${label}: DOM rows differ from payload`);
  const text = await page.locator("#rds-size-peers").textContent();
  invariant(text.includes(payload.financial_as_of), `${label}: financial clock is not visible`);
  invariant(text.includes(payload.eligibility_as_of), `${label}: eligibility clock is not visible`);
  invariant(text.includes("저축은행 · 농·축협 · 신협"), `${label}: coverage note is not visible`);
  invariant(text.includes("가격 경쟁기관과 별도 기준"), `${label}: R1 separation note is not visible`);
  return actual;
}

async function assertTermFailClosed(page, payload) {
  const nonTwelve = page.locator("#term-segment button").filter({ hasNotText: /^12개월$/ }).first();
  invariant(await nonTwelve.count() === 1, "non-12M term selector missing");
  await nonTwelve.click();
  await page.waitForFunction(
    () => document.querySelectorAll("#rds-size-peers [data-size-peer-id]").length === 0,
    null,
    { timeout: 5_000 },
  );
  const text = await page.locator("#rds-size-peers").textContent();
  invariant(text.includes(`${payload.term_months}개월`), "term fail-closed reason is not visible");
  const twelve = page.locator('#term-segment button[data-term="12"]');
  invariant(await twelve.count() === 1, "12M term selector missing");
  await twelve.click();
  await page.waitForFunction(
    () => document.querySelectorAll("#rds-size-peers [data-size-peer-id]").length > 0,
    null,
    { timeout: 5_000 },
  );
}

async function assertNoHorizontalOverflow(page, label) {
  const metrics = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }));
  invariant(
    metrics.scrollWidth <= metrics.clientWidth + 1,
    `${label}: horizontal overflow ${metrics.scrollWidth} > ${metrics.clientWidth}`,
  );
  return metrics;
}

async function runDesktop(browser, payload) {
  const { context, page, runtimeErrors } = await openStrategy(browser, { width: 1280, height: 900 });
  invariant(await page.getByText("공식 가격 경쟁기관", { exact: false }).count() > 0, "desktop: R1 heading missing");
  invariant(await page.getByText("유사 규모 기관", { exact: false }).count() > 0, "desktop: Size Peer heading missing");
  const remoteIds = await assertMode(page, payload, "remote", "desktop remote");
  await page.locator("#strategy-rate-decision-simulator").screenshot({
    path: path.join(workDir, "strategy-size-peer-desktop-remote.png"),
  });
  const branchIds = await assertMode(page, payload, "branch_busan", "desktop branch_busan");
  await page.locator("#strategy-rate-decision-simulator").screenshot({
    path: path.join(workDir, "strategy-size-peer-desktop-branch-busan.png"),
  });
  await assertTermFailClosed(page, payload);
  const layout = await assertNoHorizontalOverflow(page, "desktop");
  invariant(runtimeErrors.length === 0, `desktop runtime errors:\n${runtimeErrors.join("\n")}`);
  await context.close();
  return { remoteIds, branchIds, layout };
}

async function runMobile(browser, payload) {
  const { context, page, runtimeErrors } = await openStrategy(browser, { width: 390, height: 844 });
  const remoteIds = await assertMode(page, payload, "remote", "mobile remote");
  const firstCellDisplay = await page
    .locator("#rds-size-peers [data-size-peer-id] td")
    .first()
    .evaluate((cell) => getComputedStyle(cell).display);
  invariant(firstCellDisplay === "flex", `mobile card presentation missing: td display=${firstCellDisplay}`);
  await page.locator("#strategy-rate-decision-simulator").screenshot({
    path: path.join(workDir, "strategy-size-peer-mobile-remote.png"),
  });
  const branchIds = await assertMode(page, payload, "branch_busan", "mobile branch_busan");
  await page.locator("#strategy-rate-decision-simulator").screenshot({
    path: path.join(workDir, "strategy-size-peer-mobile-branch-busan.png"),
  });
  const layout = await assertNoHorizontalOverflow(page, "mobile");
  invariant(runtimeErrors.length === 0, `mobile runtime errors:\n${runtimeErrors.join("\n")}`);
  await context.close();
  return { remoteIds, branchIds, layout, firstCellDisplay };
}

(async () => {
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.CHROME_BIN || "/usr/bin/google-chrome",
    args: ["--no-sandbox"],
  });
  try {
    const probe = await openStrategy(browser, { width: 1280, height: 900 });
    const payload = await readPayload(probe.page);
    invariant(payload, "Size Peer payload missing");
    invariant(payload.status === "ready", `Size Peer payload not ready: ${payload.reason}`);
    invariant(
      payload.policy_id === "strategy-size-peer-worst-axis-log-ratio",
      "ranking policy id changed",
    );
    invariant(payload.term_months === 12, "Size Peer term contract changed");
    invariant(payload.anchor?.institution === "고려저축은행", "anchor institution changed");
    invariant(Number(payload.anchor?.deposit_liabilities_total) > 0, "anchor funding missing");
    invariant(Number(payload.anchor?.total_assets) > 0, "anchor total assets missing");
    invariant(/^\d{4}-\d{2}$/.test(payload.financial_as_of || ""), "financial_as_of invalid");
    invariant(/^\d{4}-\d{2}-\d{2}$/.test(payload.eligibility_as_of || ""), "eligibility_as_of invalid");
    invariant(
      JSON.stringify(payload.supported_sectors) === JSON.stringify(["savings_bank", "nh_local", "cu"]),
      "CU-enabled supported sector coverage missing",
    );
    invariant(
      JSON.stringify(payload.unsupported_sectors) === JSON.stringify(["kfcc"]),
      "unsupported sector coverage changed",
    );
    invariant(
      !(payload.modes?.branch_busan?.display_rows || []).some((row) => row.sector === "cu"),
      "CU query-region evidence was incorrectly promoted to Busan branch locality",
    );
    await probe.context.close();

    const desktop = await runDesktop(browser, payload);
    const mobile = await runMobile(browser, payload);
    const evidence = {
      policy_id: payload.policy_id,
      policy_version: payload.policy_version,
      financial_as_of: payload.financial_as_of,
      eligibility_as_of: payload.eligibility_as_of,
      supported_sectors: payload.supported_sectors,
      unsupported_sectors: payload.unsupported_sectors,
      anchor: payload.anchor,
      remote: {
        eligible_count: payload.modes.remote.eligible_count,
        ranked_count: payload.modes.remote.ranked_count,
        display_ids: desktop.remoteIds,
      },
      branch_busan: {
        eligible_count: payload.modes.branch_busan.eligible_count,
        ranked_count: payload.modes.branch_busan.ranked_count,
        display_ids: desktop.branchIds,
      },
      desktop,
      mobile,
    };
    fs.writeFileSync(
      path.join(workDir, "strategy-size-peer-runtime-metrics.json"),
      `${JSON.stringify(evidence, null, 2)}\n`,
      "utf8",
    );
    console.log(JSON.stringify(evidence));
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
