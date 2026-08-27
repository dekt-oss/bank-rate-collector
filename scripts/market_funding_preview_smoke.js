const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("@playwright/test");

const baseUrl = process.env.STRATEGY_PREVIEW_BASE_URL || "http://127.0.0.1:4173";
const workDir = path.resolve("work");
fs.mkdirSync(workDir, { recursive: true });

function invariant(condition, message) {
  if (!condition) throw new Error(message);
}

async function noOverflow(page, label) {
  const m = await page.evaluate(() => ({
    client: document.documentElement.clientWidth,
    scroll: document.documentElement.scrollWidth,
  }));
  invariant(m.scroll <= m.client + 1, `${label} overflow ${m.scroll} > ${m.client}`);
}

async function openPage(page, url) {
  await page.route("**/favicon.ico", (route) => route.fulfill({ status: 204, body: "" }));
  const response = await page.goto(url, { waitUntil: "networkidle" });
  invariant(response && response.ok(), `${url} HTTP ${response ? response.status() : "none"}`);
}

async function assertSearch(page, label) {
  await openPage(page, `${baseUrl}/`);
  const panel = page.locator("#market-funding-preview");
  invariant(await panel.count() === 1 && await panel.isVisible(), `${label}: Search market panel missing`);
  invariant(await panel.locator(".mf-card").count() === 4, `${label}: Search sector cards != 4`);
  invariant(await panel.locator(".mf-line").count() === 4, `${label}: Search trend series != 4`);
  invariant(await panel.locator(".mf-stack i").count() === 5, `${label}: maturity bands != 5`);
  const text = await panel.textContent();
  for (const required of [
    "수신시장 현황",
    "업권별 수신잔액 추이",
    "예금은행 수신 구조",
    "정기예금 만기 구조",
    "2026.06",
    "2026.07",
    "2,281.49",
    "4.21%",
    "잔액 증감은 신규 순유입과 동일하지 않으며",
  ]) {
    invariant(text.includes(required), `${label}: Search missing ${required}`);
  }
  invariant(await page.locator("#strategy-market-funding-preview").count() === 0, `${label}: Strategy strip leaked into Search`);
  await noOverflow(page, `${label} Search`);
  await page.screenshot({
    path: path.join(workDir, `market-funding-search-${label}.png`),
    fullPage: true,
  });
}

async function assertStrategy(page, label) {
  await openPage(page, `${baseUrl}/strategy.html`);
  await page.waitForFunction(
    () => document.getElementById("count")?.textContent.trim() !== "—",
    null,
    { timeout: 30_000 },
  );
  const compact = page.locator("#strategy-market-funding-preview");
  invariant(await compact.count() === 1 && await compact.isVisible(), `${label}: Strategy compact strip missing`);
  invariant(await compact.locator(".smf-item").count() === 4, `${label}: Strategy compact cards != 4`);
  invariant(await page.locator("#external-market-context").isHidden(), `${label}: legacy full macro panel visible`);
  invariant(await page.locator("#market-funding-preview").count() === 0, `${label}: full Search panel leaked into Strategy`);
  const text = await compact.textContent();
  invariant(text.includes("시장 환경 요약"), `${label}: Strategy compact heading missing`);
  invariant(text.includes("수신시장 현황 전체 보기"), `${label}: Search handoff missing`);
  invariant(text.includes("인과관계는 단정하지 않음"), `${label}: semantic boundary missing`);
  await noOverflow(page, `${label} Strategy`);
  await page.screenshot({
    path: path.join(workDir, `market-funding-strategy-${label}.png`),
    fullPage: true,
  });
}

async function runViewport(browser, viewport, label) {
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(`pageerror: ${error.message}`));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(`console: ${message.text()}`);
  });
  await assertSearch(page, label);
  await assertStrategy(page, label);
  invariant(errors.length === 0, `${label} runtime errors:\n${errors.join("\n")}`);
  await context.close();
}

(async () => {
  const browser = await chromium.launch({
    executablePath: process.env.CHROME_BIN || "/usr/bin/google-chrome",
    headless: true,
    args: ["--no-sandbox"],
  });
  try {
    await runViewport(browser, { width: 1280, height: 900 }, "desktop");
    await runViewport(browser, { width: 390, height: 844 }, "mobile");
    console.log("market funding preview smoke: PASS");
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error.stack || error);
  process.exit(1);
});
