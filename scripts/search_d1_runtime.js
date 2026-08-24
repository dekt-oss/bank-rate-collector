const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("@playwright/test");

const baseUrl = process.env.SEARCH_D1_BASE_URL || "http://127.0.0.1:4175";
const sourceSha = process.env.SEARCH_D1_SOURCE_SHA || "unknown";
const workDir = path.resolve("work/search-d1");
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
    const n = Number(text.replaceAll(",", "").replace(/[^0-9.-]/g, ""));
    return n === value;
  }, expected, { timeout: 15_000 });
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

async function typeState(page) {
  const total = await page.locator('input[data-group="type"]').count();
  const checked = await page.locator('input[data-group="type"]:checked').count();
  const button = page.locator('[data-all="type"]');
  return {
    total,
    checked,
    buttonText: (await button.textContent()).trim(),
    ariaPressed: await button.getAttribute("aria-pressed"),
  };
}

async function assertEmptyState(page, label) {
  await waitForCount(page, 0);
  const type = await typeState(page);
  invariant(type.checked === 0, `${label}: type DOM should be 0/${type.total}`);
  invariant(type.buttonText === "전체 선택", `${label}: empty type button should say 전체 선택`);
  invariant(type.ariaPressed === "false", `${label}: empty type aria-pressed should be false`);

  const url = new URL(page.url());
  invariant(url.searchParams.has("type"), `${label}: explicit empty type key missing from URL`);
  invariant(url.searchParams.get("type") === "", `${label}: type URL value must be explicit empty`);

  invariant(await page.locator('[data-recover-group="type"]').count() === 1,
    `${label}: inline recovery action missing`);
  invariant((await page.locator("#filter-mode-summary").textContent()).includes("상품유형 선택 없음"),
    `${label}: filter summary does not expose empty type`);
  invariant((await page.locator("#rankline").textContent()).includes("상품유형 선택 없음"),
    `${label}: rank empty-state missing`);
  invariant((await page.locator("#marks").textContent()).includes("상품유형 선택 없음"),
    `${label}: reference-card empty-state missing`);

  invariant(await page.locator("#hist > *").count() === 0, `${label}: stale histogram remains`);
  invariant(await page.locator("#terms > *").count() === 0, `${label}: stale term chart remains`);
  invariant(await page.locator("#reg .main-map-shell").count() === 0, `${label}: stale map remains`);
  invariant((await page.locator("#hist").getAttribute("aria-label") || "").includes("상품유형 선택 없음"),
    `${label}: histogram aria empty-state missing`);
  invariant((await page.locator("#reg").getAttribute("aria-label") || "").includes("상품유형 선택 없음"),
    `${label}: map aria empty-state missing`);

  const metrics = await overflow(page);
  assertNoOverflow(metrics, `${label} empty`);
  return { type, url: page.url(), overflow: metrics };
}

async function assertRecovered(page, initialCount, label) {
  await page.locator('[data-recover-group="type"]').click();
  await waitForCount(page, initialCount);
  const type = await typeState(page);
  invariant(type.checked === type.total && type.total > 0,
    `${label}: inline recovery did not restore all type values`);
  invariant(type.buttonText === "전체 해제", `${label}: recovered type button should say 전체 해제`);
  invariant(type.ariaPressed === "true", `${label}: recovered type aria-pressed should be true`);
  invariant((new URL(page.url()).searchParams.get("type") || "").length > 0,
    `${label}: recovered type URL is empty`);
  await page.waitForSelector("#reg.main-korea-map .main-map-shell", { timeout: 10_000 });
  invariant(await page.locator('#reg path[data-has-rate="1"]').count() > 0,
    `${label}: map did not recover after inline action`);
  const metrics = await overflow(page);
  assertNoOverflow(metrics, `${label} recovered`);
  return { type, url: page.url(), overflow: metrics };
}

async function assertIndividualLastOff(page, initialCount, label) {
  await page.locator("#reset").click();
  await waitForCount(page, initialCount);
  const values = await page.locator('input[data-group="type"]').evaluateAll((nodes) =>
    nodes.map((node) => node.value));
  invariant(values.length > 0, `${label}: type checkboxes missing`);

  for (const value of values) {
    await page.locator(`input[data-group="type"][value="${value}"]`).uncheck();
  }
  const empty = await assertEmptyState(page, `${label} individual-last-off`);

  await page.locator('[data-all="type"]').click();
  await waitForCount(page, initialCount);
  const restored = await typeState(page);
  invariant(restored.checked === restored.total,
    `${label}: group toggle did not restore all after individual last-off`);
  invariant(restored.buttonText === "전체 해제", `${label}: restored toggle label mismatch`);
  return { empty, restored };
}

async function assertNestedSelectOnly(page, label) {
  await page.locator("#reset").click();

  await page.locator('[data-detail="gu"]').click();
  const guButton = page.locator('[data-all="gu"]');
  invariant((await guButton.textContent()).trim() === "전체 선택",
    `${label}: 부산 nested action unexpectedly became toggle`);
  const guBefore = await page.locator('input[data-gu]:checked').count();
  await guButton.click();
  const guAfter = await page.locator('input[data-gu]:checked').count();
  invariant(guBefore > 0 && guAfter === guBefore,
    `${label}: 부산 nested select-only contract changed ${guBefore} -> ${guAfter}`);

  if (await page.locator("#advanced-filters").isHidden()) {
    await page.locator("#filter-toggle").click();
  }
  await page.locator('[data-detail="pref"]').click();
  const prefButton = page.locator('[data-all="prefTags"]');
  invariant((await prefButton.textContent()).trim() === "전체 선택",
    `${label}: preference nested action unexpectedly became toggle`);
  const prefBefore = await page.locator('input[data-preftag]:checked').count();
  await prefButton.click();
  const prefAfter = await page.locator('input[data-preftag]:checked').count();
  invariant(prefBefore > 0 && prefAfter === prefBefore,
    `${label}: preference nested select-only contract changed ${prefBefore} -> ${prefAfter}`);

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
  await page.waitForSelector("#reg.main-korea-map .main-map-shell", { timeout: 10_000 });

  const initialCount = countValue(await page.locator("#count").textContent());
  invariant(initialCount > 0, `${label}: default result count must be positive`);
  const initialType = await typeState(page);
  invariant(initialType.checked === initialType.total && initialType.total > 0,
    `${label}: default type group must be fully selected`);
  invariant(initialType.buttonText === "전체 해제", `${label}: default type toggle label mismatch`);
  invariant(initialType.ariaPressed === "true", `${label}: default type aria state mismatch`);
  const initialOverflow = await overflow(page);
  assertNoOverflow(initialOverflow, `${label} initial`);

  await page.locator('[data-all="type"]').click();
  const empty = await assertEmptyState(page, `${label} toggle-off`);
  await page.screenshot({ path: path.join(workDir, `search-d1-empty-${label}.png`), fullPage: true });

  const emptyUrl = page.url();
  await page.reload({ waitUntil: "networkidle" });
  await waitForLoaded(page);
  const reloadedEmpty = await assertEmptyState(page, `${label} reload-empty`);
  invariant(page.url() === emptyUrl, `${label}: explicit empty URL changed on reload`);

  const recovered = await assertRecovered(page, initialCount, `${label} inline-recovery`);
  const individual = await assertIndividualLastOff(page, initialCount, label);
  const nested = await assertNestedSelectOnly(page, label);

  invariant(runtimeErrors.length === 0, `${label}: browser runtime errors:\n${runtimeErrors.join("\n")}`);
  await page.screenshot({ path: path.join(workDir, `search-d1-recovered-${label}.png`), fullPage: true });

  const evidence = {
    schema: "search-d1-runtime-v1",
    capturedAt: new Date().toISOString(),
    sourceSha,
    viewport,
    initial: { resultCount: initialCount, type: initialType, overflow: initialOverflow },
    toggleEmpty: empty,
    reloadEmpty: reloadedEmpty,
    recovered,
    individualLastOff: individual,
    nestedSelectOnly: nested,
    runtimeErrors,
  };
  fs.writeFileSync(path.join(workDir, `search-d1-${label}.json`), JSON.stringify(evidence, null, 2) + "\n");
  await context.close();
  return evidence;
}

(async () => {
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  try {
    const desktop = await runViewport(browser, "desktop-1440", { width: 1440, height: 1000 });
    const mobile = await runViewport(browser, "mobile-390", { width: 390, height: 844 });
    const summary = {
      schema: "search-d1-runtime-summary-v1",
      sourceSha,
      desktop: { initialCount: desktop.initial.resultCount, runtimeErrors: desktop.runtimeErrors },
      mobile: { initialCount: mobile.initial.resultCount, runtimeErrors: mobile.runtimeErrors },
    };
    fs.writeFileSync(path.join(workDir, "search-d1-summary.json"), JSON.stringify(summary, null, 2) + "\n");
    console.log(JSON.stringify(summary));
    console.log("Search D1 runtime: PASS");
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error.stack || error.message || String(error));
  process.exit(1);
});
