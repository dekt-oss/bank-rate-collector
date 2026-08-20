const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("@playwright/test");

const baseUrl = process.env.STRATEGY_PREVIEW_BASE_URL || "http://127.0.0.1:4173";
const workDir = path.resolve("work");
fs.mkdirSync(workDir, { recursive: true });

function invariant(condition, message) {
  if (!condition) throw new Error(message);
}

async function loadStrategy(browser, viewport) {
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  const runtimeErrors = [];
  page.on("pageerror", (error) => runtimeErrors.push(`pageerror: ${error.message}`));
  page.on("console", (message) => { if (message.type() === "error") runtimeErrors.push(`console: ${message.text()}`); });
  await page.route("**/favicon.ico", (route) => route.fulfill({ status: 204, body: "" }));
  const response = await page.goto(`${baseUrl}/strategy.html`, { waitUntil: "networkidle" });
  invariant(response && response.ok(), `strategy.html HTTP ${response ? response.status() : "no response"}`);
  await page.waitForSelector('html[data-strategy-workspace="decision-first-v1"][data-strategy-theme="light-v1"][data-strategy-palette="main-brand-v2"]', { timeout: 30_000 });
  await page.waitForSelector("#strategy-decision-boundary", { timeout: 30_000 });
  return { context, page, runtimeErrors };
}

async function navigationSnapshot(page, selector) {
  return page.evaluate((navSelector) => {
    const nav = document.querySelector(navSelector);
    if (!nav) return null;
    const links = [...nav.querySelectorAll("a")];
    const navStyle = getComputedStyle(nav);
    const firstStyle = links[0] ? getComputedStyle(links[0]) : null;
    const active = nav.querySelector("a.active");
    const activeStyle = active ? getComputedStyle(active) : null;
    const rect = (node) => {
      if (!node) return null;
      const box = node.getBoundingClientRect();
      return { left: box.left, right: box.right, top: box.top, bottom: box.bottom };
    };
    return {
      labels: links.map((link) => link.textContent.trim()),
      hrefs: links.map((link) => link.getAttribute("href")),
      activeLabel: active?.textContent.trim() || "",
      activeCurrent: active?.getAttribute("aria-current") || "",
      navPadding: navStyle.padding,
      navRadius: navStyle.borderRadius,
      navBackground: navStyle.backgroundColor,
      linkPadding: firstStyle?.padding || "",
      linkRadius: firstStyle?.borderRadius || "",
      linkFontSize: firstStyle?.fontSize || "",
      linkFontWeight: firstStyle?.fontWeight || "",
      activeBackground: activeStyle?.backgroundColor || "",
      activeColor: activeStyle?.color || "",
      navRect: rect(nav),
      brandRect: rect(document.querySelector("header.top > .brand")),
      controlsRect: rect(document.querySelector("header.top > .head-right")),
      clientWidth: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth,
    };
  }, selector);
}

function overlaps(a, b) {
  if (!a || !b) return false;
  return a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
}

async function assertUnifiedNavigation(browser, strategyPage, viewport, label) {
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  await page.route("**/favicon.ico", (route) => route.fulfill({ status: 204, body: "" }));
  const response = await page.goto(`${baseUrl}/`, { waitUntil: "domcontentloaded" });
  invariant(response && response.ok(), `index.html HTTP ${response ? response.status() : "no response"}`);
  await page.waitForSelector("header.top > .page-nav", { timeout: 30_000 });

  const main = await navigationSnapshot(page, "header.top > .page-nav");
  const strategy = await navigationSnapshot(strategyPage, "header.topbar > .nav");
  invariant(main && strategy, `${label}: page navigation missing`);
  invariant(JSON.stringify(main.labels) === JSON.stringify(["검색 조회", "전략 대시보드"]), `${label}: main navigation labels=${main.labels}`);
  invariant(JSON.stringify(strategy.labels) === JSON.stringify(main.labels), `${label}: navigation labels differ`);
  invariant(JSON.stringify(main.hrefs) === JSON.stringify(["./", "strategy.html"]), `${label}: main navigation hrefs=${main.hrefs}`);
  invariant(JSON.stringify(strategy.hrefs) === JSON.stringify(main.hrefs), `${label}: navigation hrefs differ`);
  invariant(main.activeLabel === "검색 조회" && main.activeCurrent === "page", `${label}: main active=${main.activeLabel}/${main.activeCurrent}`);
  invariant(strategy.activeLabel === "전략 대시보드" && strategy.activeCurrent === "page", `${label}: strategy active=${strategy.activeLabel}/${strategy.activeCurrent}`);
  for (const key of ["navPadding", "navRadius", "navBackground", "linkPadding", "linkRadius", "linkFontSize", "linkFontWeight", "activeBackground", "activeColor"]) {
    invariant(main[key] === strategy[key], `${label}: navigation visual contract differs for ${key}: main=${main[key]} strategy=${strategy[key]}`);
  }
  invariant(main.scrollWidth <= main.clientWidth + 1, `${label}: main horizontal overflow ${main.scrollWidth} > ${main.clientWidth}`);
  if (label === "desktop") {
    invariant(!overlaps(main.navRect, main.brandRect), "desktop: page navigation overlaps main brand");
    invariant(!overlaps(main.navRect, main.controlsRect), "desktop: page navigation overlaps main controls");
  }
  await page.screenshot({ path: path.join(workDir, `strategy-main-runtime-navigation-main-${label}.png`), fullPage: false });
  await context.close();
}

async function assertDecisionWorkspace(page, label) {
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
    const modelDetail = planning?.querySelector(".workspace-model-detail");
    const evidencePanel = document.querySelector(".ux-evidence-panel");
    const bodyStyle = getComputedStyle(document.body);
    const card = document.querySelector(".card");
    const cardStyle = card ? getComputedStyle(card) : null;
    const rootStyle = getComputedStyle(document.documentElement);
    const topbar = document.querySelector(".topbar");
    const topbarStyle = topbar ? getComputedStyle(topbar) : null;
    const map = byId("map-card");
    const kpis = document.querySelector(".kpis");
    const bridge = byId("strategy-region-bridge");
    const boundary = byId("strategy-decision-boundary");
    return {
      decisionBeforeExternal: order(planning, external),
      externalBeforeIntel: order(external, marketIntel),
      intelBeforeFlow: order(marketIntel, marketFlow),
      flowBeforeInsight: order(marketFlow, interpretation),
      insightBeforePreference: order(interpretation, preference),
      preferenceBeforeDetail: order(preference, primary),
      changesOpen: Boolean(changes?.open),
      legacyExists: Boolean(legacy),
      legacyOpen: Boolean(legacy?.open),
      modelDetailExists: Boolean(modelDetail),
      modelDetailOpen: Boolean(modelDetail?.open),
      evidencePanelExists: Boolean(evidencePanel),
      evidencePanelOpen: Boolean(evidencePanel?.open),
      mapDisplay: map ? getComputedStyle(map).display : "missing",
      mapAriaHidden: map?.getAttribute("aria-hidden") || "",
      kpiDisplay: kpis ? getComputedStyle(kpis).display : "missing",
      bridgeText: bridge?.textContent || "",
      boundaryText: boundary?.textContent || "",
      reportButton: Boolean(byId("strategy-report-button")),
      clientWidth: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth,
      strategyTheme: document.documentElement.dataset.strategyTheme,
      strategyPalette: document.documentElement.dataset.strategyPalette,
      strategyTypography: document.documentElement.dataset.strategyTypography,
      colorScheme: rootStyle.colorScheme,
      accent: rootStyle.getPropertyValue("--accent").trim(),
      accentInk: rootStyle.getPropertyValue("--accent-ink").trim(),
      bodyColor: bodyStyle.color,
      bodyFont: bodyStyle.fontFamily,
      bodyFontSize: parseFloat(bodyStyle.fontSize),
      cardBackground: cardStyle?.backgroundColor || "",
      topbarBackground: topbarStyle?.backgroundImage || "",
    };
  });

  invariant(result.decisionBeforeExternal, `${label}: decision workspace is not first`);
  invariant(result.externalBeforeIntel && result.intelBeforeFlow, `${label}: market evidence order is wrong`);
  invariant(result.flowBeforeInsight && result.insightBeforePreference && result.preferenceBeforeDetail, `${label}: product/detail order is wrong`);
  invariant(!result.changesOpen, `${label}: recent changes should start collapsed`);
  invariant(result.legacyExists && !result.legacyOpen, `${label}: legacy preference summary should start collapsed`);
  invariant(result.modelDetailExists && !result.modelDetailOpen, `${label}: model detail should start collapsed`);
  invariant(result.evidencePanelExists && !result.evidencePanelOpen, `${label}: collection evidence should start collapsed`);
  invariant(result.mapDisplay === "none" && result.mapAriaHidden === "true", `${label}: Strategy map is still a visible explorer (${result.mapDisplay}/${result.mapAriaHidden})`);
  invariant(result.kpiDisplay === "none", `${label}: duplicate Strategy KPI strip visible=${result.kpiDisplay}`);
  invariant(result.bridgeText.includes("검색 조회") && result.bridgeText.includes("지역 상세"), `${label}: Main region bridge missing`);
  invariant(result.boundaryText.includes("현재 판단 가능") && result.boundaryText.includes("최적금리"), `${label}: decision calibration boundary missing`);
  invariant(result.reportButton, `${label}: Strategy report button missing`);
  invariant(result.scrollWidth <= result.clientWidth + 1, `${label}: horizontal overflow ${result.scrollWidth} > ${result.clientWidth}`);
  invariant(result.strategyTheme === "light-v1", `${label}: light theme marker=${result.strategyTheme}`);
  invariant(result.strategyPalette === "main-brand-v2", `${label}: brand palette marker=${result.strategyPalette}`);
  invariant(result.strategyTypography === "variable-ui-v2", `${label}: typography marker=${result.strategyTypography}`);
  invariant(result.colorScheme === "light", `${label}: color-scheme=${result.colorScheme}`);
  invariant(result.accent.toUpperCase() === "#D33A7C", `${label}: accent=${result.accent}`);
  invariant(result.accentInk.toUpperCase() === "#5B2F64", `${label}: accent ink=${result.accentInk}`);
  invariant(result.bodyFont.includes("Pretendard"), `${label}: readable font stack missing Pretendard: ${result.bodyFont}`);
  invariant(result.bodyColor === "rgb(37, 29, 39)", `${label}: primary text color=${result.bodyColor}`);
  invariant(result.cardBackground === "rgb(255, 255, 255)", `${label}: card is not white: ${result.cardBackground}`);
  invariant(result.topbarBackground.includes("linear-gradient"), `${label}: branded topbar gradient missing`);
  if (label === "desktop") invariant(result.bodyFontSize >= 14, `desktop: body type too small=${result.bodyFontSize}`);
  else invariant(result.bodyFontSize >= 13.5, `mobile: body type too small=${result.bodyFontSize}`);
}

async function assertReportBuilders(browser, strategyPage, viewport, label) {
  const strategyReport = await strategyPage.evaluate(() => {
    const api = window.__rateMonitorReport;
    if (!api || api.kind !== "strategy") return null;
    const root = api.build();
    const result = { kind: root.dataset.reportKind, text: root.textContent, mapCount: root.querySelectorAll("#geo-map,.mapstage,.mapcard").length };
    api.cleanup();
    return result;
  });
  invariant(strategyReport?.kind === "strategy", `${label}: Strategy report API missing`);
  invariant(strategyReport.text.includes("수신상품 금리결정 검토보고서"), `${label}: Strategy report title missing`);
  invariant(strategyReport.text.includes("내부 수신실적 미보정") && strategyReport.text.includes("FTP"), `${label}: Strategy report caveat missing`);
  invariant(strategyReport.mapCount === 0, `${label}: Strategy report contains full map`);

  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  await page.route("**/favicon.ico", (route) => route.fulfill({ status: 204, body: "" }));
  const response = await page.goto(`${baseUrl}/`, { waitUntil: "networkidle" });
  invariant(response && response.ok(), `index.html HTTP ${response ? response.status() : "no response"}`);
  await page.waitForSelector("#main-report-button", { timeout: 30_000 });
  const mainReport = await page.evaluate(() => {
    const api = window.__rateMonitorReport;
    if (!api || api.kind !== "main") return null;
    const root = api.build();
    const result = { kind: root.dataset.reportKind, text: root.textContent, tableCount: root.querySelectorAll("table").length };
    api.cleanup();
    return result;
  });
  invariant(mainReport?.kind === "main", `${label}: Main report API missing`);
  invariant(mainReport.text.includes("금리 조회·경쟁현황 보고서"), `${label}: Main report title missing`);
  invariant(mainReport.text.includes("지역 근거") && mainReport.text.includes("CSV/JSON"), `${label}: Main report role/evidence note missing`);
  const metrics = await page.evaluate(() => ({ clientWidth: document.documentElement.clientWidth, scrollWidth: document.documentElement.scrollWidth }));
  invariant(metrics.scrollWidth <= metrics.clientWidth + 1, `${label}: Main horizontal overflow ${metrics.scrollWidth} > ${metrics.clientWidth}`);
  await context.close();
}

(async () => {
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  try {
    const desktopViewport = { width: 1280, height: 900 };
    const desktop = await loadStrategy(browser, desktopViewport);
    await assertDecisionWorkspace(desktop.page, "desktop");
    await assertUnifiedNavigation(browser, desktop.page, desktopViewport, "desktop");
    await assertReportBuilders(browser, desktop.page, desktopViewport, "desktop");
    await desktop.page.screenshot({ path: path.join(workDir, "strategy-main-runtime-workspace-desktop.png"), fullPage: true });
    invariant(desktop.runtimeErrors.length === 0, `desktop runtime errors:\n${desktop.runtimeErrors.join("\n")}`);
    await desktop.context.close();

    const mobileViewport = { width: 390, height: 844 };
    const mobile = await loadStrategy(browser, mobileViewport);
    await assertDecisionWorkspace(mobile.page, "mobile");
    await assertUnifiedNavigation(browser, mobile.page, mobileViewport, "mobile");
    await assertReportBuilders(browser, mobile.page, mobileViewport, "mobile");
    await mobile.page.screenshot({ path: path.join(workDir, "strategy-main-runtime-workspace-mobile.png"), fullPage: true });
    invariant(mobile.runtimeErrors.length === 0, `mobile runtime errors:\n${mobile.runtimeErrors.join("\n")}`);
    await mobile.context.close();

    console.log("strategy decision workspace + role separation + reports smoke: PASS (desktop/mobile)");
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
