const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("@playwright/test");

const baseUrl = process.env.STRATEGY_PREVIEW_BASE_URL || "http://127.0.0.1:4173";
const workDir = path.resolve("work");
fs.mkdirSync(workDir, { recursive: true });

function invariant(condition, message) {
  if (!condition) throw new Error(message);
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
  await page.waitForSelector('html[data-strategy-workspace="decision-first-v1"]', { timeout: 30_000 });
  return { context, page, runtimeErrors };
}

async function assertWorkspace(page, label) {
  const result = await page.evaluate(() => {
    const byId = (id) => document.getElementById(id);
    const order = (a, b) => Boolean(a && b && (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING));
    const planning = byId("planning-zone");
    const external = byId("external-market-context");
    const marketIntel = byId("market-intelligence");
    const marketFlow = byId("market-flow");
    const interpretation = document.querySelector(".grid.interpretation");
    const preference = byId("preference-intelligence");
    const primary = document.querySelector(".grid.primary");
    const changes = marketFlow?.querySelector("details.changes");
    const legacy = interpretation?.querySelector(".workspace-legacy-pref");
    const kpis = Array.from(document.querySelectorAll(".kpis .kpi")).slice(0, 2).map((node) => node.getBoundingClientRect());
    const evidence = Array.from(document.querySelectorAll(".evidence-strip .evidence-card")).slice(0, 2).map((node) => node.getBoundingClientRect());
    const mapStage = primary?.querySelector(".mapstage")?.getBoundingClientRect();
    return {
      decisionBeforeExternal: order(planning, external),
      externalBeforeIntel: order(external, marketIntel),
      intelBeforeFlow: order(marketIntel, marketFlow),
      flowBeforeInsight: order(marketFlow, interpretation),
      insightBeforePreference: order(interpretation, preference),
      preferenceBeforeDetail: order(preference, primary),
      labels: ["workspace-label-decision", "workspace-label-evidence", "workspace-label-product", "workspace-label-detail"].filter((id) => byId(id)).length,
      changesOpen: Boolean(changes?.open),
      legacyOpen: Boolean(legacy?.open),
      legacyExists: Boolean(legacy),
      planningTop: planning?.getBoundingClientRect().top,
      externalTop: external?.getBoundingClientRect().top,
      kpis,
      evidence,
      mapHeight: mapStage?.height || 0,
      clientWidth: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth,
    };
  });

  invariant(result.decisionBeforeExternal, `${label}: decision workspace is not before market evidence`);
  invariant(result.externalBeforeIntel && result.intelBeforeFlow, `${label}: market evidence order is wrong`);
  invariant(result.flowBeforeInsight && result.insightBeforePreference && result.preferenceBeforeDetail, `${label}: insight/product/detail order is wrong`);
  invariant(result.labels === 4, `${label}: workspace section labels=${result.labels}`);
  invariant(!result.changesOpen, `${label}: recent change details should start collapsed`);
  invariant(result.legacyExists && !result.legacyOpen, `${label}: legacy preference summary should be collapsed`);
  invariant(result.planningTop < result.externalTop, `${label}: planning visual order is not decision-first`);
  invariant(result.scrollWidth <= result.clientWidth + 1, `${label}: page horizontal overflow ${result.scrollWidth} > ${result.clientWidth}`);

  if (label === "desktop") {
    invariant(result.mapHeight <= 300, `desktop: compact map height=${result.mapHeight}`);
  } else {
    invariant(result.kpis.length === 2 && Math.abs(result.kpis[0].y - result.kpis[1].y) < 2 && result.kpis[0].x !== result.kpis[1].x, "mobile: KPI cards are not two-column");
    invariant(result.evidence.length === 2 && Math.abs(result.evidence[0].y - result.evidence[1].y) < 2 && result.evidence[0].x !== result.evidence[1].x, "mobile: evidence cards are not two-column");
    invariant(result.mapHeight <= 310, `mobile: compact map height=${result.mapHeight}`);
  }
}

(async () => {
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  try {
    const desktop = await loadPage(browser, { width: 1280, height: 900 });
    await assertWorkspace(desktop.page, "desktop");
    await desktop.page.screenshot({ path: path.join(workDir, "strategy-main-runtime-workspace-desktop.png"), fullPage: true });
    invariant(desktop.runtimeErrors.length === 0, `desktop runtime errors:\n${desktop.runtimeErrors.join("\n")}`);
    await desktop.context.close();

    const mobile = await loadPage(browser, { width: 390, height: 844 });
    await assertWorkspace(mobile.page, "mobile");
    await mobile.page.screenshot({ path: path.join(workDir, "strategy-main-runtime-workspace-mobile.png"), fullPage: true });
    invariant(mobile.runtimeErrors.length === 0, `mobile runtime errors:\n${mobile.runtimeErrors.join("\n")}`);
    await mobile.context.close();

    console.log("strategy decision workspace smoke: PASS (desktop/mobile)");
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error.stack || error.message || String(error));
  process.exit(1);
});
