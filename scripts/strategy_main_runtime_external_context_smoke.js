const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("@playwright/test");

const baseUrl = process.env.STRATEGY_PREVIEW_BASE_URL || "http://127.0.0.1:4173";
const workDir = path.resolve("work");
fs.mkdirSync(workDir, { recursive: true });

function invariant(condition, message) {
  if (!condition) throw new Error(message);
}

function signedPct(value) {
  const number = Number(value);
  return `${number > 0 ? "+" : ""}${number.toFixed(2)}%`;
}

async function loadPage(browser, viewport) {
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  const runtimeErrors = [];
  page.on("pageerror", (error) => runtimeErrors.push(`pageerror: ${error.message}`));
  page.on("console", (message) => {
    if (message.type() === "error") runtimeErrors.push(`console: ${message.text()}`);
  });
  await page.route("**/favicon.ico", (route) => route.fulfill({ status: 204, body: "" }));
  const response = await page.goto(`${baseUrl}/strategy.html`, { waitUntil: "networkidle" });
  invariant(response && response.ok(), `strategy.html HTTP ${response ? response.status() : "no response"}`);
  await page.waitForSelector("#external-market-context", { state: "visible", timeout: 30_000 });
  return { context, page, runtimeErrors };
}

async function assertPopulated(page, label) {
  const result = await page.evaluate(() => {
    const raw = document.getElementById("rate-monitor-data")?.textContent || "{}";
    const payload = JSON.parse(raw);
    const features = payload.strategy?.external_features;
    const panel = document.getElementById("external-market-context");
    return {
      features,
      panelText: panel?.textContent || "",
      badge: panel?.querySelector(".external-context-badge")?.textContent || "",
      rateValues: Array.from(panel?.querySelectorAll(".external-context-card b") || []).map((node) => node.textContent.trim()),
      flowValues: Array.from(panel?.querySelectorAll(".external-flow b") || []).map((node) => node.textContent.trim()),
      rateCards: panel?.querySelectorAll(".external-context-card").length || 0,
      flowCards: panel?.querySelectorAll(".external-flow").length || 0,
      clientWidth: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth,
    };
  });

  const features = result.features;
  invariant(features?.status === "ready", `${label}: external_features status=${features?.status}`);
  invariant(features.policy_rate?.status === "ready", `${label}: policy rate not ready`);
  invariant(features.deposit_market?.status === "ready", `${label}: deposit market not ready`);

  const rates = features.deposit_market.bank_rates || {};
  const flows = features.deposit_market.sector_balances || {};
  invariant(rates.primary_realized_deposit_rate?.status === "ready", `${label}: bank primary rate not ready`);
  invariant(rates.term_deposit_1y_rate?.status === "ready", `${label}: bank 12m rate not ready`);
  for (const key of ["savings_bank", "credit_union", "kfcc", "broad_mutual_finance"]) {
    invariant(flows[key]?.status === "ready", `${label}: ${key} flow not ready`);
    invariant(Number.isFinite(Number(flows[key]?.mom_change_pct)), `${label}: ${key} MoM missing`);
  }

  invariant(result.rateCards === 3, `${label}: rate card count=${result.rateCards}`);
  invariant(result.flowCards === 4, `${label}: flow card count=${result.flowCards}`);
  invariant(result.badge.includes("BOK · 정상"), `${label}: ready badge not rendered: ${result.badge}`);
  invariant(result.rateValues.length === 3 && result.rateValues.every((value) => value !== "—"), `${label}: rate cards contain missing value: ${result.rateValues.join(", ")}`);
  invariant(result.flowValues.length === 4 && result.flowValues.every((value) => value !== "—"), `${label}: flow cards contain missing value: ${result.flowValues.join(", ")}`);
  invariant(result.panelText.includes("농·축협과 1:1 동일하지 않음"), `${label}: broad mutual finance boundary missing`);
  invariant(result.scrollWidth <= result.clientWidth + 1, `${label}: horizontal overflow ${result.scrollWidth} > ${result.clientWidth}`);

  invariant(result.rateValues[0] === `${Number(features.policy_rate.value).toFixed(2)}%`, `${label}: policy rate DOM/payload mismatch`);
  invariant(result.rateValues[1] === `${Number(rates.primary_realized_deposit_rate.value).toFixed(2)}%`, `${label}: bank primary DOM/payload mismatch`);
  invariant(result.rateValues[2] === `${Number(rates.term_deposit_1y_rate.value).toFixed(2)}%`, `${label}: bank 12m DOM/payload mismatch`);

  const expectedFlows = [
    signedPct(flows.savings_bank.mom_change_pct),
    signedPct(flows.credit_union.mom_change_pct),
    signedPct(flows.kfcc.mom_change_pct),
    signedPct(flows.broad_mutual_finance.mom_change_pct),
  ];
  invariant(JSON.stringify(result.flowValues) === JSON.stringify(expectedFlows), `${label}: flow DOM/payload mismatch ${result.flowValues.join(", ")} != ${expectedFlows.join(", ")}`);
}

(async () => {
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  try {
    const desktop = await loadPage(browser, { width: 1280, height: 900 });
    await assertPopulated(desktop.page, "desktop");
    await desktop.page.screenshot({ path: path.join(workDir, "strategy-main-runtime-desktop.png"), fullPage: true });
    invariant(desktop.runtimeErrors.length === 0, `desktop runtime errors:\n${desktop.runtimeErrors.join("\n")}`);
    await desktop.context.close();

    const mobile = await loadPage(browser, { width: 390, height: 844 });
    await assertPopulated(mobile.page, "mobile");
    await mobile.page.screenshot({ path: path.join(workDir, "strategy-main-runtime-mobile.png"), fullPage: true });
    invariant(mobile.runtimeErrors.length === 0, `mobile runtime errors:\n${mobile.runtimeErrors.join("\n")}`);
    await mobile.context.close();

    console.log("strategy main runtime external context smoke: PASS (populated desktop/mobile)");
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error.stack || error.message || String(error));
  process.exit(1);
});
