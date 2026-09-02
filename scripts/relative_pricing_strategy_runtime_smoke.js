const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("@playwright/test");

const baseUrl = process.env.STRATEGY_PREVIEW_BASE_URL || "http://127.0.0.1:4173";
const workDir = path.resolve("work");
fs.mkdirSync(workDir, { recursive: true });

function invariant(condition, message) {
  if (!condition) throw new Error(message);
}

function numericText(value) {
  const normalized = String(value || "").replace(/[^0-9.+-]/g, "");
  const number = Number(normalized);
  return Number.isFinite(number) ? number : null;
}

function moneyNumber(value) {
  const normalized = String(value || "")
    .replaceAll(",", "")
    .replace(/[^0-9.+−-]/g, "")
    .replace("−", "-");
  const number = Number(normalized);
  return Number.isFinite(number) ? number : null;
}

async function embeddedRelativePricing(page) {
  return page.evaluate(() => {
    const node = document.getElementById("rate-monitor-data");
    if (!node) throw new Error("rate-monitor-data payload missing");
    const payload = JSON.parse(node.textContent || "{}");
    return payload.strategy?.relative_pricing || null;
  });
}

async function assertNoRootOverflow(page, label) {
  const size = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }));
  invariant(
    size.scrollWidth <= size.clientWidth + 1,
    `${label} horizontal overflow: ${size.scrollWidth} > ${size.clientWidth}`,
  );
}

async function openStrategy(page) {
  const response = await page.goto(`${baseUrl}/strategy.html`, { waitUntil: "networkidle" });
  invariant(response && response.ok(), `strategy.html HTTP ${response ? response.status() : "none"}`);
  await page.waitForFunction(
    () => {
      const section = document.getElementById("relative-pricing-r1");
      const status = document.getElementById("rp-status");
      const ready = document.getElementById("rp-ready");
      return Boolean(section && status && ready && !ready.hidden && status.textContent.trim() === "R1 factual");
    },
    null,
    { timeout: 30_000 },
  );
}

async function assertSearchDoesNotLeakR1(page) {
  const response = await page.goto(`${baseUrl}/`, { waitUntil: "networkidle" });
  invariant(response && response.ok(), `index HTTP ${response ? response.status() : "none"}`);
  invariant(await page.locator("#relative-pricing-r1").count() === 0, "Search page leaked R1 Strategy surface");
}

async function assertFactualR1(page, label) {
  const rp = await embeddedRelativePricing(page);
  invariant(rp?.status === "ready", `${label}: R1 payload not ready: ${rp?.status} / ${rp?.reason}`);
  invariant(rp?.reason == null, `${label}: ready R1 unexpectedly has reason ${rp?.reason}`);

  const position = rp.pricing_peer_position || {};
  const peers = Array.isArray(rp.peers) ? rp.peers : [];
  invariant(peers.length > 0, `${label}: pricing peers empty`);
  invariant(position.pricing_peer_count === peers.length, `${label}: payload peer count mismatch`);
  invariant(position.funding_join_count === peers.length, `${label}: funding join is not complete`);
  invariant(position.funding_unjoined_count === 0, `${label}: funding has unjoined peers`);
  invariant(Number(position.funding_join_ratio) === 1, `${label}: funding join ratio is not 1`);

  const section = page.locator("#relative-pricing-r1");
  invariant(await section.isVisible(), `${label}: R1 section hidden`);
  invariant(await page.locator("#rp-ready").isVisible(), `${label}: R1 ready panel hidden`);
  invariant(await page.locator("#rp-blocked").isHidden(), `${label}: blocked panel still visible`);
  invariant((await page.locator("#rp-scope").textContent()).includes("부산"), `${label}: official Busan scope not visible`);

  const current = Number(position.current_rate_pct);
  invariant(Number.isFinite(current), `${label}: current rate invalid`);
  const currentDom = numericText(await page.locator("#rp-current-rate").textContent());
  invariant(Math.abs(currentDom - current) < 1e-9, `${label}: current rate DOM mismatch`);

  const coverage = (await page.locator("#rp-funding-coverage").textContent()).trim();
  invariant(coverage === `${peers.length} / ${peers.length}기관`, `${label}: funding coverage DOM mismatch: ${coverage}`);
  invariant(await page.locator("#rp-peer-rows tr").count() === peers.length, `${label}: peer table row count mismatch`);

  const first = peers.slice().sort((a, b) => {
    const rateDiff = Number(b.rate_pct) - Number(a.rate_pct);
    if (rateDiff) return rateDiff;
    return String(a.institution || a.institution_id).localeCompare(String(b.institution || b.institution_id), "ko");
  })[0];
  const firstCells = page.locator("#rp-peer-rows tr").first().locator("td");
  invariant(await firstCells.count() === 8, `${label}: peer row must expose 8 factual columns`);
  const rateAsOfText = (await firstCells.nth(3).textContent()).trim();
  const fundingAsOfText = (await firstCells.nth(6).textContent()).trim();
  invariant(rateAsOfText.startsWith(String(first.rate_as_of).slice(0, 10)), `${label}: rate_as_of not rendered separately`);
  invariant(fundingAsOfText.startsWith(String(first.funding_as_of)), `${label}: funding_as_of not rendered separately`);

  for (const forbidden of [
    "#target-balance",
    "#target-net-inflow",
    "#target-horizon",
    "#recommended-rate",
    "#predicted-inflow",
  ]) {
    invariant(await page.locator(forbidden).count() === 0, `${label}: forbidden goal/prediction surface ${forbidden}`);
  }

  const initialProductRank = (await page.locator("#rp-product-market-rank").textContent()).trim();
  const slider = page.locator("#rp-review-slider");
  const max = Number(await slider.getAttribute("max"));
  invariant(current + 0.10 <= max + 1e-9, `${label}: current rate leaves no +10bp slider room`);
  await slider.evaluate((node, value) => {
    node.value = value.toFixed(2);
    node.dispatchEvent(new Event("input", { bubbles: true }));
  }, current + 0.10);

  await page.waitForFunction(
    (expected) => document.getElementById("rp-review-rate")?.textContent.trim() === `${expected.toFixed(2)}%`,
    current + 0.10,
    { timeout: 5_000 },
  );

  const termMonths = Number(rp.scope?.term_months || 12);
  const expectedCost = 10_000_000_000 * 0.001 * (termMonths / 12);
  const costValueText = await page.locator("#rp-cost").evaluate((node) => node.firstChild?.textContent || "");
  const actualCost = moneyNumber(costValueText);
  invariant(actualCost === expectedCost, `${label}: +10bp / 100억원 cost mismatch ${actualCost} != ${expectedCost}`);

  const afterProductRank = (await page.locator("#rp-product-market-rank").textContent()).trim();
  invariant(afterProductRank === initialProductRank, `${label}: review slider mutated factual product-market rank`);
  invariant((await page.locator("#rp-peer-rank").textContent()).includes("기관"), `${label}: peer rank not recomputed`);

  await assertNoRootOverflow(page, label);
}

async function runViewport(browser, viewport, label, screenshot) {
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  const runtimeErrors = [];

  // The evidence server is intentionally a static http.server. Production owns
  // /api/health in the hosting runtime, so isolate exactly that endpoint here
  // instead of allowing its harness-only 404 to hide real asset/JS failures.
  await page.route("**/api/health", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ harness: "static-r1-e2e", sources: [] }),
  }));
  await page.route("**/favicon.ico", (route) => route.fulfill({ status: 204, body: "" }));

  page.on("pageerror", (error) => runtimeErrors.push(`pageerror: ${error.message}`));
  page.on("console", (message) => {
    if (message.type() === "error") runtimeErrors.push(`console: ${message.text()}`);
  });

  await assertSearchDoesNotLeakR1(page);
  await openStrategy(page);
  await assertFactualR1(page, label);
  await page.screenshot({ path: path.join(workDir, screenshot), fullPage: true });
  invariant(runtimeErrors.length === 0, `${label} browser runtime errors:\n${runtimeErrors.join("\n")}`);
  await context.close();
}

(async () => {
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  try {
    await runViewport(browser, { width: 1280, height: 900 }, "desktop", "relative-pricing-r1-desktop.png");
    await runViewport(browser, { width: 390, height: 844 }, "mobile", "relative-pricing-r1-mobile.png");
    console.log("relative pricing Strategy runtime smoke: PASS (desktop + mobile)");
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error.stack || error.message || String(error));
  process.exit(1);
});
