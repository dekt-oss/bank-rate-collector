const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("@playwright/test");

const baseUrl = process.env.STRATEGY_PREVIEW_BASE_URL || "http://127.0.0.1:4173";
const workDir = path.resolve("work");
fs.mkdirSync(workDir, { recursive: true });

function invariant(condition, message) {
  if (!condition) throw new Error(message);
}

async function runViewport(browser, viewport, name) {
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  const runtimeErrors = [];
  page.on("pageerror", (error) => runtimeErrors.push(`pageerror: ${error.message}`));
  page.on("console", (message) => {
    if (message.type() === "error") runtimeErrors.push(`console: ${message.text()}`);
  });
  await page.route("**/favicon.ico", (route) => route.fulfill({ status: 204, body: "" }));
  const response = await page.goto(`${baseUrl}/strategy.html`, { waitUntil: "networkidle" });
  invariant(response && response.ok(), `${name}: strategy.html load failed`);
  await page.waitForSelector("#rate-funding-matrix", { state: "visible", timeout: 30_000 });

  const payload = await page.evaluate(() => {
    const raw = document.getElementById("rate-monitor-data")?.textContent || "{}";
    return JSON.parse(raw)?.strategy?.rate_funding_matrix || null;
  });
  invariant(payload, `${name}: Rate × Funding payload missing`);
  invariant(payload.contract?.current_rate_carryback === false, `${name}: carryback contract broken`);
  invariant(payload.contract?.missing_rate_as_zero === false, `${name}: missing-rate contract broken`);
  invariant(payload.contract?.causal_interpretation === false, `${name}: causal contract broken`);

  const sectors = payload.sectors || {};
  invariant(sectors.savings_bank, `${name}: savings-bank matrix evidence missing`);
  invariant(sectors.nh_local, `${name}: NH matrix evidence missing`);

  for (const [sector, expectedCurrent] of [["savings_bank", 66], ["nh_local", 1081]]) {
    const item = sectors[sector];
    invariant(item.available === false, `${name}: ${sector} must remain fail-closed without historical rates`);
    invariant(item.status === "historical_rate_unavailable", `${name}: ${sector} status mismatch`);
    invariant(item.historical_rate_institutions === 0, `${name}: ${sector} unexpectedly has historical aligned rates`);
    invariant(item.paired_institutions === 0, `${name}: ${sector} unexpectedly has exact pairs`);
    invariant(item.current_rate_institutions_not_carried_back === expectedCurrent, `${name}: ${sector} blocked-current count mismatch: ${item.current_rate_institutions_not_carried_back}`);
  }

  const bodyText = (await page.locator("#rate-funding-matrix").textContent()).trim();
  invariant(bodyText.includes("시점정합 금리 이력이 부족"), `${name}: fail-closed explanation missing`);
  invariant(bodyText.includes("현재 공시금리가 존재하더라도 과거 수신잔액에 소급해 붙이지 않습니다"), `${name}: no-carryback explanation missing`);
  invariant(bodyText.includes("인과효과 판정이 아닙니다"), `${name}: association boundary missing`);
  invariant(await page.locator("#rate-funding-matrix svg").count() === 0, `${name}: chart rendered despite zero exact pairs`);

  await page.screenshot({ path: path.join(workDir, `rate-funding-matrix-${name}.png`), fullPage: true });
  invariant(runtimeErrors.length === 0, `${name} runtime errors:\n${runtimeErrors.join("\n")}`);
  await context.close();
}

(async () => {
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.CHROME_BIN || "/usr/bin/google-chrome",
    args: ["--no-sandbox", "--disable-dev-shm-usage"],
  });
  try {
    await runViewport(browser, { width: 1280, height: 900 }, "desktop");
    await runViewport(browser, { width: 390, height: 844 }, "mobile");
  } finally {
    await browser.close();
  }
})();
