const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("@playwright/test");

const baseUrl = process.env.STRATEGY_PREVIEW_BASE_URL || "http://127.0.0.1:4173";
const workDir = path.resolve("work");
const requiredRateKeys = ["primary_realized_deposit_rate", "term_deposit_1y_rate"];
const requiredFlowKeys = ["savings_bank", "credit_union", "kfcc", "broad_mutual_finance"];
fs.mkdirSync(workDir, { recursive: true });

function invariant(condition, message) {
  if (!condition) throw new Error(message);
}

function signedPct(value) {
  const number = Number(value);
  return `${number > 0 ? "+" : ""}${number.toFixed(2)}%`;
}

function assertStatus(item, allowed, label) {
  const status = item?.status;
  invariant(allowed.includes(status), `${label}: unexpected status=${status}`);
  return status;
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

async function assertContract(page, label) {
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
  assertStatus(features, ["ready", "partial", "no_data"], `${label}: external_features`);
  assertStatus(features.policy_rate, ["ready", "no_data"], `${label}: policy_rate`);
  assertStatus(features.deposit_market, ["ready", "partial", "no_data"], `${label}: deposit_market`);

  const rates = features.deposit_market.bank_rates || {};
  const flows = features.deposit_market.sector_balances || {};
  for (const key of requiredRateKeys) {
    invariant(Object.hasOwn(rates, key), `${label}: missing bank_rate:${key}`);
    assertStatus(rates[key], ["ready", "no_data"], `${label}: bank_rate:${key}`);
  }
  for (const key of requiredFlowKeys) {
    invariant(Object.hasOwn(flows, key), `${label}: missing sector_balance:${key}`);
    assertStatus(
      flows[key],
      ["ready", "no_data", "insufficient_history", "non_consecutive_months"],
      `${label}: sector_balance:${key}`,
    );
  }

  invariant(result.rateCards === 3, `${label}: rate card count=${result.rateCards}`);
  invariant(result.flowCards === 4, `${label}: flow card count=${result.flowCards}`);
  invariant(result.badge.includes("BOK ·"), `${label}: BOK status badge missing: ${result.badge}`);
  invariant(result.panelText.includes("농·축협과 1:1 동일하지 않음"), `${label}: broad mutual finance boundary missing`);
  invariant(result.scrollWidth <= result.clientWidth + 1, `${label}: horizontal overflow ${result.scrollWidth} > ${result.clientWidth}`);

  const shownRates = [features.policy_rate, rates.primary_realized_deposit_rate, rates.term_deposit_1y_rate];
  shownRates.forEach((item, index) => {
    const expected = item?.status === "ready" ? `${Number(item.value).toFixed(2)}%` : "—";
    invariant(result.rateValues[index] === expected, `${label}: rate DOM/payload mismatch at ${index}: ${result.rateValues[index]} != ${expected}`);
  });

  const shownFlows = [flows.savings_bank, flows.credit_union, flows.kfcc, flows.broad_mutual_finance];
  shownFlows.forEach((item, index) => {
    if (item?.status === "ready") {
      invariant(Number.isFinite(Number(item.mom_change_pct)), `${label}: flow ${index} ready without MoM`);
    }
    const expected = item?.status === "ready" ? signedPct(item.mom_change_pct) : "—";
    invariant(result.flowValues[index] === expected, `${label}: flow DOM/payload mismatch at ${index}: ${result.flowValues[index]} != ${expected}`);
  });
}

(async () => {
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  try {
    const desktop = await loadPage(browser, { width: 1280, height: 900 });
    await assertContract(desktop.page, "desktop");
    await desktop.page.screenshot({ path: path.join(workDir, "strategy-main-runtime-desktop.png"), fullPage: true });
    invariant(desktop.runtimeErrors.length === 0, `desktop runtime errors:\n${desktop.runtimeErrors.join("\n")}`);
    await desktop.context.close();

    const mobile = await loadPage(browser, { width: 390, height: 844 });
    await assertContract(mobile.page, "mobile");
    await mobile.page.screenshot({ path: path.join(workDir, "strategy-main-runtime-mobile.png"), fullPage: true });
    invariant(mobile.runtimeErrors.length === 0, `mobile runtime errors:\n${mobile.runtimeErrors.join("\n")}`);
    await mobile.context.close();

    console.log("strategy main runtime external context smoke: PASS (contract-valid desktop/mobile)");
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error.stack || error.message || String(error));
  process.exit(1);
});
