const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("@playwright/test");

const baseUrl = process.env.SEARCH_PHASE3_BASE_URL || "http://127.0.0.1:4176";
const sourceSha = process.env.SEARCH_PHASE3_SOURCE_SHA || "unknown";
const workDir = path.resolve("work/search-phase3");
fs.mkdirSync(workDir, { recursive: true });

function invariant(condition, message) {
  if (!condition) throw new Error(message);
}

function countValue(text) {
  return Number(String(text || "").replaceAll(",", "").replace(/[^0-9.-]/g, ""));
}

async function waitForLoaded(page) {
  await page.waitForFunction(() => {
    const count = document.getElementById("count")?.textContent.trim();
    return Boolean(count && count !== "—" && document.querySelector("#rows > tr"));
  }, null, { timeout: 45_000 });
}

async function waitForCount(page, expected) {
  await page.waitForFunction((value) => {
    const text = document.getElementById("count")?.textContent || "";
    return Number(text.replaceAll(",", "").replace(/[^0-9.-]/g, "")) === value;
  }, expected, { timeout: 20_000 });
}

async function selectedValues(page, key) {
  return page.locator(`input[data-group="${key}"]:checked`).evaluateAll((nodes) =>
    nodes.map((node) => node.value).sort());
}

async function overflow(page) {
  return page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
    bodyClientWidth: document.body.clientWidth,
    bodyScrollWidth: document.body.scrollWidth,
  }));
}

function assertNoOverflow(metrics, label) {
  invariant(metrics.scrollWidth <= metrics.clientWidth + 1,
    `${label}: document overflow ${metrics.scrollWidth} > ${metrics.clientWidth}`);
  invariant(metrics.bodyScrollWidth <= metrics.bodyClientWidth + 1,
    `${label}: body overflow ${metrics.bodyScrollWidth} > ${metrics.bodyClientWidth}`);
}

async function presetInfo(page, id) {
  const button = page.locator(`[data-preset="${id}"]`);
  invariant(await button.count() === 1, `preset missing: ${id}`);
  return {
    pressed: await button.getAttribute("aria-pressed"),
    count: countValue(await button.locator(".n").textContent()),
  };
}

async function clickExactPreset(page, id, expectedType, label) {
  const beforeRegion = await selectedValues(page, "region");
  const beforeSector = await selectedValues(page, "sector");
  const before = await presetInfo(page, id);
  invariant(before.count > 0, `${label}: preset count should be positive`);

  await page.locator(`[data-preset="${id}"]`).click();
  await waitForCount(page, before.count);
  invariant(await page.locator(`[data-preset="${id}"]`).getAttribute("aria-pressed") === "true",
    `${label}: preset should be active after click`);
  invariant((await selectedValues(page, "type")).join(",") === expectedType,
    `${label}: product type mismatch`);
  invariant((await selectedValues(page, "term")).join(",") === "7-12",
    `${label}: term bucket mismatch`);
  invariant(await page.locator("#tmin").inputValue() === "12", `${label}: tmin not 12`);
  invariant(await page.locator("#tmax").inputValue() === "12", `${label}: tmax not 12`);
  invariant(JSON.stringify(await selectedValues(page, "region")) === JSON.stringify(beforeRegion),
    `${label}: generic exact preset changed region`);
  invariant(JSON.stringify(await selectedValues(page, "sector")) === JSON.stringify(beforeSector),
    `${label}: generic exact preset changed sector`);

  const activeInfo = await presetInfo(page, id);
  invariant(activeInfo.count === before.count,
    `${label}: active preset badge ${activeInfo.count} != result ${before.count}`);

  const url = new URL(page.url());
  invariant(url.searchParams.get("tmin") === "12", `${label}: URL tmin missing`);
  invariant(url.searchParams.get("tmax") === "12", `${label}: URL tmax missing`);
  invariant(url.searchParams.get("type") === expectedType, `${label}: URL type mismatch`);
  invariant(url.searchParams.get("term") === "7-12", `${label}: URL term mismatch`);

  const exactUrl = page.url();
  await page.reload({ waitUntil: "networkidle" });
  await waitForLoaded(page);
  await waitForCount(page, before.count);
  invariant(page.url() === exactUrl, `${label}: URL changed after reload`);
  invariant(await page.locator(`[data-preset="${id}"]`).getAttribute("aria-pressed") === "true",
    `${label}: preset active state lost after reload`);
  invariant(await page.locator("#tmin").inputValue() === "12", `${label}: reload tmin mismatch`);
  invariant(await page.locator("#tmax").inputValue() === "12", `${label}: reload tmax mismatch`);

  await page.locator("#tmax").fill("13");
  await page.waitForTimeout(350);
  invariant(await page.locator(`[data-preset="${id}"]`).getAttribute("aria-pressed") === "false",
    `${label}: manual scalar edit did not clear active state`);

  return { count: before.count, url: exactUrl, region: beforeRegion, sector: beforeSector };
}

async function assertLegacyPreset(page, label) {
  await page.locator("#reset").click();
  await waitForLoaded(page);
  const id = "sb-dep";
  const before = await presetInfo(page, id);
  invariant(before.count > 0, `${label}: legacy preset count should be positive`);
  await page.locator(`[data-preset="${id}"]`).click();
  await waitForCount(page, before.count);
  invariant(await page.locator("#tmin").inputValue() === "", `${label}: legacy preset kept tmin`);
  invariant(await page.locator("#tmax").inputValue() === "", `${label}: legacy preset kept tmax`);
  invariant(await page.locator(`[data-preset="${id}"]`).getAttribute("aria-pressed") === "true",
    `${label}: legacy preset not active`);
  const text = (await page.locator(`[data-preset="${id}"]`).textContent()) || "";
  invariant(text.includes("7~12개월"), `${label}: legacy preset label is still misleading`);
  const url = new URL(page.url());
  invariant(!url.searchParams.has("tmin") && !url.searchParams.has("tmax"),
    `${label}: legacy 7~12 preset unexpectedly became exact range`);
  return { count: before.count, url: page.url() };
}

async function assertNestedSelectOnly(page, label) {
  await page.locator("#reset").click();
  await page.locator('[data-detail="gu"]').click();
  const guButton = page.locator('[data-all="gu"]');
  invariant((await guButton.textContent()).trim() === "전체 선택",
    `${label}: 부산 nested contract changed`);
  const guBefore = await page.locator("input[data-gu]:checked").count();
  await guButton.click();
  const guAfter = await page.locator("input[data-gu]:checked").count();
  invariant(guBefore > 0 && guAfter === guBefore,
    `${label}: 부산 nested select-only changed ${guBefore} -> ${guAfter}`);

  if (await page.locator("#advanced-filters").isHidden()) await page.locator("#filter-toggle").click();
  await page.locator('[data-detail="pref"]').click();
  const prefButton = page.locator('[data-all="prefTags"]');
  invariant((await prefButton.textContent()).trim() === "전체 선택",
    `${label}: preference nested contract changed`);
  const prefBefore = await page.locator("input[data-preftag]:checked").count();
  await prefButton.click();
  const prefAfter = await page.locator("input[data-preftag]:checked").count();
  invariant(prefBefore > 0 && prefAfter === prefBefore,
    `${label}: preference nested select-only changed ${prefBefore} -> ${prefAfter}`);
  return { guChecked: guAfter, preferenceChecked: prefAfter };
}

async function runViewport(browser, label, viewport) {
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  const runtimeErrors = [];
  page.on("pageerror", (error) => runtimeErrors.push(`pageerror: ${error.message}`));
  page.on("console", (message) => {
    if (message.type() === "error") runtimeErrors.push(`console: ${message.text()}`);
  });
  await page.route("**/favicon.ico", (route) => route.fulfill({ status: 204, body: "" }));

  const response = await page.goto(`${baseUrl}/index.html`, { waitUntil: "networkidle" });
  invariant(response && response.ok(), `${label}: index HTTP failure`);
  await waitForLoaded(page);

  const initialCount = countValue(await page.locator("#count").textContent());
  invariant(initialCount > 0, `${label}: default result count must be positive`);
  invariant(await page.locator("#tmin").inputValue() === "", `${label}: default tmin changed`);
  invariant(await page.locator("#tmax").inputValue() === "", `${label}: default tmax changed`);
  const labels = await page.locator("#presets [data-preset]").evaluateAll((buttons) =>
    buttons.map((button) => button.childNodes[0]?.textContent?.trim() || ""));
  invariant(labels.length === 6, `${label}: expected 6 presets, got ${labels.length}`);
  invariant(labels[0] === "1년 예금 · 12개월", `${label}: deposit exact preset is not first`);
  invariant(labels[1] === "1년 적금 · 12개월", `${label}: savings exact preset is not second`);
  invariant(labels.slice(2).every((text) => text.includes("7~12개월")),
    `${label}: legacy preset labels do not expose 7~12개월`);
  assertNoOverflow(await overflow(page), `${label} default`);

  const deposit = await clickExactPreset(page, "exact12-dep", "term_deposit", `${label} deposit`);
  await page.screenshot({ path: path.join(workDir, `search-phase3-deposit-${label}.png`), fullPage: true });

  await page.locator("#reset").click();
  await waitForCount(page, initialCount);
  const savings = await clickExactPreset(page, "exact12-sav", "installment_savings", `${label} savings`);
  const legacy = await assertLegacyPreset(page, label);
  const nested = await assertNestedSelectOnly(page, label);
  await page.locator("#reset").click();
  await waitForCount(page, initialCount);

  const finalOverflow = await overflow(page);
  assertNoOverflow(finalOverflow, `${label} final`);
  invariant(runtimeErrors.length === 0, `${label}: browser runtime errors:\n${runtimeErrors.join("\n")}`);

  const evidence = {
    schema: "search-phase3-runtime-v1",
    capturedAt: new Date().toISOString(),
    sourceSha,
    viewport,
    initialCount,
    labels,
    deposit,
    savings,
    legacy,
    nestedSelectOnly: nested,
    finalOverflow,
    runtimeErrors,
  };
  fs.writeFileSync(path.join(workDir, `search-phase3-${label}.json`), JSON.stringify(evidence, null, 2) + "\n");
  await context.close();
  return evidence;
}

(async () => {
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  try {
    const desktop = await runViewport(browser, "desktop-1440", { width: 1440, height: 1000 });
    const mobile = await runViewport(browser, "mobile-390", { width: 390, height: 844 });
    const summary = {
      schema: "search-phase3-runtime-summary-v1",
      sourceSha,
      desktop: { initialCount: desktop.initialCount, deposit: desktop.deposit.count, savings: desktop.savings.count },
      mobile: { initialCount: mobile.initialCount, deposit: mobile.deposit.count, savings: mobile.savings.count },
    };
    fs.writeFileSync(path.join(workDir, "search-phase3-summary.json"), JSON.stringify(summary, null, 2) + "\n");
    console.log(JSON.stringify(summary));
    console.log("Search phase 3 runtime: PASS");
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error.stack || error.message || String(error));
  process.exit(1);
});
