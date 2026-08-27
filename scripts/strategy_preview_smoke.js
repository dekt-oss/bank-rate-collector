const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("@playwright/test");

const baseUrl = process.env.STRATEGY_PREVIEW_BASE_URL || "http://127.0.0.1:4173";
const workDir = path.resolve("work");
fs.mkdirSync(workDir, { recursive: true });

function invariant(condition, message) {
  if (!condition) throw new Error(message);
}

function cleanNumber(value) {
  return Number(String(value || "").replaceAll(",", "").trim());
}

async function waitForDashboard(page) {
  await page.route("**/favicon.ico", (route) => route.fulfill({ status: 204, body: "" }));
  const response = await page.goto(`${baseUrl}/strategy.html`, { waitUntil: "networkidle" });
  invariant(response && response.ok(), `strategy.html HTTP ${response ? response.status() : "no response"}`);
  await page.waitForFunction(
    () => {
      const count = document.getElementById("count");
      const error = document.getElementById("error");
      return Boolean(count && error && error.hidden && count.textContent.trim() !== "—");
    },
    null,
    { timeout: 30_000 },
  );
}

async function assertNoOverflow(page, label) {
  const metrics = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }));
  invariant(
    metrics.scrollWidth <= metrics.clientWidth + 1,
    `${label} horizontal overflow: ${metrics.scrollWidth} > ${metrics.clientWidth}`,
  );
}

async function assertPreviewRoleSplit(page, label) {
  const compact = page.locator("#strategy-market-funding-preview");
  invariant(await compact.count() === 1, `${label}: compact market context missing`);
  invariant(await compact.isVisible(), `${label}: compact market context hidden`);
  invariant(await compact.locator(".smf-item").count() === 4, `${label}: compact sector cards != 4`);
  const compactText = await compact.textContent();
  invariant(compactText.includes("시장 환경 요약"), `${label}: compact heading missing`);
  invariant(compactText.includes("2026.06"), `${label}: analysis month missing`);
  invariant(compactText.includes("2026.07"), `${label}: leading rate month missing`);
  invariant(compactText.includes("4.21%"), `${label}: verified savings-bank leading rate missing`);
  invariant(
    compactText.includes("인과관계는 단정하지 않음"),
    `${label}: non-causal semantic boundary missing`,
  );
  invariant(
    await compact.locator('a[href="./#market-funding-preview"]').count() === 1,
    `${label}: Search market handoff link missing`,
  );

  const legacy = page.locator("#external-market-context");
  invariant(await legacy.count() === 1, `${label}: canonical external context DOM missing`);
  invariant(await legacy.isHidden(), `${label}: full macro panel should move to Search in preview`);
  invariant(await page.locator("#market-funding-preview").count() === 0, `${label}: full Search macro view leaked into Strategy`);
}

async function assertCoreStrategy(page, label) {
  invariant(await page.locator("#error").isHidden(), `${label}: runtime error banner visible`);
  invariant(cleanNumber(await page.locator("#count").textContent()) > 0, `${label}: comparison group empty`);
  invariant(await page.locator("#top5 tr").count() > 0, `${label}: TOP5 empty`);
  invariant(await page.locator("#market-intelligence").isVisible(), `${label}: market intelligence hidden`);
  invariant(await page.locator("#planning-zone").isVisible(), `${label}: planning zone hidden`);
  invariant(await page.locator("#prediction-toggle").isVisible(), `${label}: prediction toggle hidden`);
  invariant(await page.locator("#scope-evidence").isVisible(), `${label}: scope evidence hidden`);
  await assertPreviewRoleSplit(page, label);
  await assertNoOverflow(page, label);
}

async function runViewport(browser, viewport, name) {
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  const runtimeErrors = [];
  page.on("pageerror", (error) => runtimeErrors.push(`pageerror: ${error.message}`));
  page.on("console", (message) => {
    if (message.type() === "error") runtimeErrors.push(`console: ${message.text()}`);
  });

  await waitForDashboard(page);
  await assertCoreStrategy(page, name);

  const cu = page.locator('[data-sector="cu"]');
  const kfcc = page.locator('[data-sector="kfcc"]');
  const nh = page.locator('[data-sector="nh_local"]');
  invariant(await cu.count() === 1 && !(await cu.isDisabled()), `${name}: credit-union selector unavailable`);
  invariant(await kfcc.count() === 1 && !(await kfcc.isDisabled()), `${name}: KFCC selector unavailable`);
  invariant(await nh.count() === 1 && !(await nh.isDisabled()), `${name}: NH-local selector unavailable`);

  const combined = page.locator('[data-market-mode="combined"]');
  if (await combined.count()) {
    await combined.evaluate((button) => button.click());
    await page.waitForFunction(
      () => document.querySelector('[data-market-mode="combined"]')?.classList.contains("active"),
      null,
      { timeout: 10_000 },
    );
    invariant(await page.locator("#sim-form").isVisible(), `${name}: combined simulator hidden`);
  }

  await page.screenshot({
    path: path.join(workDir, `strategy-smoke-${name}.png`),
    fullPage: true,
  });
  invariant(runtimeErrors.length === 0, `${name} browser errors:\n${runtimeErrors.join("\n")}`);
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
    console.log("strategy preview smoke: PASS");
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error.stack || error);
  process.exit(1);
});
