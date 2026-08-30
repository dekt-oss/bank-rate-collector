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
  invariant(payload.contract?.rate_field === "max_rate", `${name}: Strategy rate-field contract mismatch`);
  invariant(payload.contract?.source_precedence === "presentation.db_only_sources", `${name}: source precedence contract mismatch`);
  invariant(payload.contract?.current_rate_carryback === false, `${name}: carryback contract broken`);
  invariant(payload.contract?.missing_rate_as_zero === false, `${name}: missing-rate contract broken`);
  invariant(payload.contract?.causal_interpretation === false, `${name}: causal contract broken`);

  const sectors = payload.sectors || {};
  const savings = sectors.savings_bank;
  const nh = sectors.nh_local;
  invariant(savings, `${name}: savings-bank matrix evidence missing`);
  invariant(nh, `${name}: NH matrix evidence missing`);

  invariant(savings.available === false, `${name}: savings bank must remain fail-closed`);
  invariant(savings.status === "historical_rate_unavailable", `${name}: savings status mismatch`);
  invariant(savings.historical_rate_institutions === 0, `${name}: savings historical rate unexpectedly available`);
  invariant(savings.paired_institutions === 0, `${name}: savings exact pair unexpectedly available`);
  invariant(savings.current_rate_institutions > 0, `${name}: savings current-rate evidence missing`);

  invariant(nh.available === false, `${name}: NH must remain fail-closed`);
  invariant(nh.status === "rate_data_unavailable", `${name}: NH rate-data status mismatch`);
  invariant(nh.historical_rate_institutions === 0, `${name}: NH historical rate unexpectedly available`);
  invariant(nh.paired_institutions === 0, `${name}: NH exact pair unexpectedly available`);
  invariant(nh.current_rate_institutions === 0, `${name}: NH current rate should be absent in production evidence`);

  let bodyText = (await page.locator("#rate-funding-matrix").textContent()).trim();
  invariant(bodyText.includes("시점정합 금리 이력이 부족"), `${name}: savings fail-closed explanation missing`);
  invariant(bodyText.includes("현재 공시금리가 존재하더라도 과거 수신잔액에 소급해 붙이지 않습니다"), `${name}: no-carryback explanation missing`);
  invariant(bodyText.includes("presentation.db_only_sources 우선순위"), `${name}: source precedence explanation missing`);
  invariant(bodyText.includes("인과효과 판정이 아닙니다"), `${name}: association boundary missing`);
  invariant(await page.locator("#rate-funding-matrix svg").count() === 0, `${name}: chart rendered despite zero exact pairs`);

  await page.locator('#rate-funding-matrix-tabs button[data-sector="nh_local"]').click();
  bodyText = (await page.locator("#rate-funding-matrix").textContent()).trim();
  invariant(bodyText.includes("금리 데이터 미수집"), `${name}: NH missing-rate badge missing`);
  invariant(bodyText.includes("이 업권의 12개월 공시금리 데이터가 없어"), `${name}: NH missing-rate explanation missing`);
  invariant(bodyText.includes("이름 유사 매칭이나 다른 업권 금리를 대신 붙이지 않습니다"), `${name}: NH exact-identity boundary missing`);
  invariant(await page.locator("#rate-funding-matrix svg").count() === 0, `${name}: NH chart rendered without rate data`);

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
