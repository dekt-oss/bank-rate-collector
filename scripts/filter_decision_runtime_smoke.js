#!/usr/bin/env node

const { chromium } = require("@playwright/test");

const base = (process.env.STRATEGY_PREVIEW_BASE_URL || "http://127.0.0.1:4173").replace(/\/$/, "");
const invariant = (condition, message) => {
  if (!condition) throw new Error(message);
};

async function assertSearch(browser) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const errors = [];
  page.on("pageerror", (error) => errors.push(String(error)));
  let response = await page.goto(`${base}/`, { waitUntil: "networkidle", timeout: 60_000 });
  invariant(response && response.ok(), "Search page failed to load");
  await page.waitForSelector('[data-product-family-toggle="deposit"]', { timeout: 30_000 });
  await page.waitForSelector('[data-product-family-toggle="savings"]', { timeout: 30_000 });

  const deposit = page.locator('[data-product-family-toggle="deposit"]');
  const savings = page.locator('[data-product-family-toggle="savings"]');
  invariant(await deposit.isChecked(), "Search default deposit family is not checked");
  await savings.check();
  await page.waitForFunction(() => new URLSearchParams(location.search).get("family") === "combined");
  invariant(await deposit.isChecked() && await savings.isChecked(), "Search did not keep deposit+savings selected together");
  invariant(await page.locator(".product-savings-detail").isVisible(), "Search combined scope hid savings subtypes");

  const combinedUrl = page.url();
  response = await page.goto(combinedUrl, { waitUntil: "networkidle", timeout: 60_000 });
  invariant(response && response.ok(), "Search combined URL reload failed");
  await page.waitForSelector('[data-product-family-toggle="deposit"]', { timeout: 30_000 });
  invariant(
    await page.locator('[data-product-family-toggle="deposit"]').isChecked()
      && await page.locator('[data-product-family-toggle="savings"]').isChecked(),
    "Search combined URL reload lost product families",
  );
  invariant(errors.length === 0, `Search runtime errors:\n${errors.join("\n")}`);
  await page.close();
}

async function assertStrategy(browser) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const errors = [];
  page.on("pageerror", (error) => errors.push(String(error)));
  const response = await page.goto(`${base}/strategy.html`, { waitUntil: "networkidle", timeout: 60_000 });
  invariant(response && response.ok(), "Strategy page failed to load");

  await page.waitForSelector('[data-sector-family-toggle="savings_bank"]', { timeout: 30_000 });
  await page.waitForSelector('[data-product-family-toggle="deposit"]', { timeout: 30_000 });
  const sectorLabels = await page.locator(".strategy-mutual-children .sector-toggle").allTextContents();
  invariant(sectorLabels.length === 3, `mutual-finance children missing: ${sectorLabels.join(" | ")}`);
  invariant(sectorLabels[0].includes("신협"), `first mutual child is not CU: ${sectorLabels[0]}`);
  invariant(sectorLabels[1].includes("농·축협"), `second mutual child is not NH: ${sectorLabels[1]}`);
  invariant(sectorLabels[2].includes("새마을금고"), `third mutual child is not KFCC: ${sectorLabels[2]}`);

  const savingsBank = page.locator('[data-sector-family-toggle="savings_bank"]');
  const mutual = page.locator('[data-sector-family-toggle="mutual_finance"]');
  invariant(await savingsBank.isChecked(), "Strategy savings-bank parent is not checked by default");
  await mutual.check();
  await page.waitForFunction(() => document.querySelector('[data-market-mode="combined"]')?.classList.contains("active"));
  invariant(await savingsBank.isChecked() && await mutual.isChecked(), "Strategy parent sector checkboxes did not enter combined mode");

  const marketReference = page.locator(".market-position-reference");
  await marketReference.waitFor({ state: "visible", timeout: 30_000 });
  invariant(await marketReference.evaluate((node) => node.open), "market position reference is not open by default");

  const panel = page.locator("#prediction-panel");
  await panel.waitFor({ state: "visible", timeout: 30_000 });
  const modelDetail = page.locator(".workspace-model-detail");
  invariant(await modelDetail.count() === 1, "prediction model detail was not constructed");
  invariant(await modelDetail.evaluate((node) => node.open), "prediction model detail is not open by default");

  await page.locator('[data-product-family-toggle="savings"]').check();
  await page.waitForFunction(() => document.getElementById("product-scope-pill")?.textContent.includes("예금 + 적금"));
  invariant(await panel.isVisible(), "combined product scope hid prediction details");
  await page.waitForFunction(() => document.getElementById("rate-response-body")?.textContent.includes("예금 단독 전용"));
  invariant(
    (await page.locator("#rate-response-body").textContent()).includes("예금 단독 전용"),
    "combined product scope did not fail closed for rate-response calculation",
  );
  invariant(
    (await page.locator("#decision-sensitivity-grid").textContent()).includes("예금 단독 전용"),
    "combined product scope did not fail closed for sensitivity calculation",
  );

  invariant(errors.length === 0, `Strategy runtime errors:\n${errors.join("\n")}`);
  await page.close();
}

async function assertMobileHierarchy(browser) {
  const page = await browser.newPage({ viewport: { width: 390, height: 844 }, isMobile: true });
  const errors = [];
  page.on("pageerror", (error) => errors.push(String(error)));
  const response = await page.goto(`${base}/strategy.html`, { waitUntil: "networkidle", timeout: 60_000 });
  invariant(response && response.ok(), "mobile Strategy page failed to load");
  await page.waitForSelector(".strategy-sector-family-controls", { timeout: 30_000 });
  invariant(await page.locator('[data-sector-family-toggle="savings_bank"]').isVisible(), "mobile savings-bank parent is hidden");
  invariant(await page.locator('[data-sector-family-toggle="mutual_finance"]').isVisible(), "mobile mutual-finance parent is hidden");
  invariant(await page.locator(".strategy-mutual-children .sector-toggle").count() === 3, "mobile mutual child controls are incomplete");
  const layout = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
    columns: getComputedStyle(document.querySelector(".strategy-sector-family-controls")).gridTemplateColumns,
  }));
  invariant(layout.scrollWidth <= layout.clientWidth + 1, `mobile filter hierarchy overflows: ${JSON.stringify(layout)}`);
  invariant(layout.columns.trim().split(/\s+/).length === 1, `mobile sector parents did not stack: ${layout.columns}`);
  invariant(await page.locator(".market-position-reference").evaluate((node) => node.open), "mobile market position reference is closed by default");
  invariant(errors.length === 0, `mobile Strategy runtime errors:\n${errors.join("\n")}`);
  await page.close();
}

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: "/usr/bin/google-chrome" });
  try {
    await assertSearch(browser);
    await assertStrategy(browser);
    await assertMobileHierarchy(browser);
    console.log("filter + decision runtime smoke: PASS");
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
