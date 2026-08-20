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
  await page.waitForSelector('html[data-strategy-workspace="decision-first-v1"][data-strategy-theme="light-v1"][data-strategy-palette="main-brand-v2"]', { timeout: 30_000 });
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

async function assertPageNavigation(browser, strategyPage, viewport, label) {
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
  invariant(JSON.stringify(strategy.labels) === JSON.stringify(main.labels), `${label}: navigation labels differ between pages`);
  invariant(JSON.stringify(main.hrefs) === JSON.stringify(["./", "strategy.html"]), `${label}: main navigation hrefs=${main.hrefs}`);
  invariant(JSON.stringify(strategy.hrefs) === JSON.stringify(main.hrefs), `${label}: navigation hrefs differ between pages`);
  invariant(main.activeLabel === "검색 조회" && main.activeCurrent === "page", `${label}: main active page=${main.activeLabel}/${main.activeCurrent}`);
  invariant(strategy.activeLabel === "전략 대시보드" && strategy.activeCurrent === "page", `${label}: strategy active page=${strategy.activeLabel}/${strategy.activeCurrent}`);

  for (const key of ["navPadding", "navRadius", "navBackground", "linkPadding", "linkRadius", "linkFontSize", "linkFontWeight", "activeBackground", "activeColor"]) {
    invariant(main[key] === strategy[key], `${label}: navigation visual contract differs for ${key}: main=${main[key]} strategy=${strategy[key]}`);
  }
  invariant(main.scrollWidth <= main.clientWidth + 1, `${label}: main page horizontal overflow ${main.scrollWidth} > ${main.clientWidth}`);
  if (label === "desktop") {
    invariant(!overlaps(main.navRect, main.brandRect), `desktop: page navigation overlaps main brand`);
    invariant(!overlaps(main.navRect, main.controlsRect), `desktop: page navigation overlaps main controls`);
  }

  await page.screenshot({ path: path.join(workDir, `strategy-main-runtime-navigation-main-${label}.png`), fullPage: false });
  await context.close();
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
    const modelDetail = planning?.querySelector(".workspace-model-detail");
    const evidencePanel = document.querySelector(".ux-evidence-panel");
    const firstCard = document.querySelector(".card");
    const firstKpiValue = document.querySelector(".kvalue");
    const topbar = document.querySelector(".topbar");
    const koreaMapImage = document.querySelector(".korea-map-image");
    const denseMicrocopy = document.querySelector(".external-context-card small");
    const bodyStyle = getComputedStyle(document.body);
    const cardStyle = firstCard ? getComputedStyle(firstCard) : null;
    const kpiValueStyle = firstKpiValue ? getComputedStyle(firstKpiValue) : null;
    const rootStyle = getComputedStyle(document.documentElement);
    const topbarStyle = topbar ? getComputedStyle(topbar) : null;
    const koreaMapImageStyle = koreaMapImage ? getComputedStyle(koreaMapImage) : null;
    const denseStyle = denseMicrocopy ? getComputedStyle(denseMicrocopy) : null;
    const externalStyle = external ? getComputedStyle(external) : null;
    const marketIntelStyle = marketIntel ? getComputedStyle(marketIntel) : null;
    const preferenceStyle = preference ? getComputedStyle(preference) : null;
    const prefMain = preference?.querySelector(".pref-intel-main");
    const prefMainStyle = prefMain ? getComputedStyle(prefMain) : null;
    const marketDirection = marketIntel?.querySelector(".market-intel-direction");
    const marketDirectionStyle = marketDirection ? getComputedStyle(marketDirection) : null;
    const marketEmpty = marketIntel?.querySelector(".market-intel-empty");
    const marketEmptyStyle = marketEmpty ? getComputedStyle(marketEmpty) : null;
    const segmentButton = document.querySelector(".segment button:not(.active)");
    const segmentButtonStyle = segmentButton ? getComputedStyle(segmentButton) : null;
    const termCard = document.querySelector(".termcard");
    const termCardStyle = termCard ? getComputedStyle(termCard) : null;
    const kpis = Array.from(document.querySelectorAll(".kpis .kpi")).slice(0, 2).map((node) => node.getBoundingClientRect());
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
      modelDetailExists: Boolean(modelDetail),
      modelDetailOpen: Boolean(modelDetail?.open),
      modelDetailHasResults: Boolean(modelDetail?.querySelector(".prediction-results")),
      modelDetailHasEvidence: Boolean(modelDetail?.querySelector(".model-evidence")),
      evidencePanelExists: Boolean(evidencePanel),
      evidencePanelOpen: Boolean(evidencePanel?.open),
      planningTop: planning?.getBoundingClientRect().top,
      externalTop: external?.getBoundingClientRect().top,
      kpis,
      mapHeight: mapStage?.height || 0,
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
      kpiFont: kpiValueStyle?.fontFamily || "",
      kpiNumeric: kpiValueStyle?.fontVariantNumeric || "",
      topbarBackground: topbarStyle?.backgroundImage || "",
      koreaMapImageOpacity: koreaMapImageStyle ? parseFloat(koreaMapImageStyle.opacity) : NaN,
      koreaMapImageFilter: koreaMapImageStyle?.filter || "",
      denseFontSize: denseStyle ? parseFloat(denseStyle.fontSize) : 0,
      externalBackground: externalStyle?.backgroundColor || "",
      marketIntelBackground: marketIntelStyle?.backgroundColor || "",
      preferenceBackground: preferenceStyle?.backgroundColor || "",
      prefMainBackground: prefMainStyle?.backgroundColor || "",
      marketDirectionBackground: marketDirectionStyle?.backgroundColor || "",
      marketEmptyBackground: marketEmptyStyle?.backgroundColor || "",
      segmentButtonBackground: segmentButtonStyle?.backgroundColor || "",
      termCardBackground: termCardStyle?.backgroundColor || "",
    };
  });

  invariant(result.decisionBeforeExternal, `${label}: decision workspace is not before market evidence`);
  invariant(result.externalBeforeIntel && result.intelBeforeFlow, `${label}: market evidence order is wrong`);
  invariant(result.flowBeforeInsight && result.insightBeforePreference && result.preferenceBeforeDetail, `${label}: insight/product/detail order is wrong`);
  invariant(result.labels === 4, `${label}: workspace section labels=${result.labels}`);
  invariant(!result.changesOpen, `${label}: recent change details should start collapsed`);
  invariant(result.legacyExists && !result.legacyOpen, `${label}: legacy preference summary should be collapsed`);
  invariant(result.modelDetailExists && !result.modelDetailOpen, `${label}: model detail should start collapsed`);
  invariant(result.modelDetailHasResults && result.modelDetailHasEvidence, `${label}: model detail lost prediction results or evidence`);
  invariant(result.evidencePanelExists && !result.evidencePanelOpen, `${label}: evidence panel should start collapsed`);
  invariant(result.planningTop < result.externalTop, `${label}: planning visual order is not decision-first`);
  invariant(result.scrollWidth <= result.clientWidth + 1, `${label}: page horizontal overflow ${result.scrollWidth} > ${result.clientWidth}`);
  invariant(result.strategyTheme === "light-v1", `${label}: light theme marker=${result.strategyTheme}`);
  invariant(result.strategyPalette === "main-brand-v2", `${label}: brand palette marker=${result.strategyPalette}`);
  invariant(result.strategyTypography === "variable-ui-v2", `${label}: typography marker=${result.strategyTypography}`);
  invariant(result.colorScheme === "light", `${label}: color-scheme=${result.colorScheme}`);
  invariant(result.accent.toUpperCase() === "#D33A7C", `${label}: accent=${result.accent}`);
  invariant(result.accentInk.toUpperCase() === "#5B2F64", `${label}: accent ink=${result.accentInk}`);
  invariant(result.bodyFont.includes("Pretendard"), `${label}: readable font stack missing Pretendard: ${result.bodyFont}`);
  invariant(result.bodyColor === "rgb(37, 29, 39)", `${label}: primary text color=${result.bodyColor}`);
  invariant(result.cardBackground === "rgb(255, 255, 255)", `${label}: card is not white surface: ${result.cardBackground}`);
  invariant(!result.kpiFont.toLowerCase().includes("monospace"), `${label}: KPI font still uses monospace: ${result.kpiFont}`);
  invariant(result.kpiNumeric.includes("tabular-nums"), `${label}: KPI numerals are not tabular: ${result.kpiNumeric}`);
  invariant(result.topbarBackground.includes("linear-gradient"), `${label}: branded topbar gradient missing: ${result.topbarBackground}`);
  invariant(Number.isFinite(result.koreaMapImageOpacity) && result.koreaMapImageOpacity <= 0.2, `${label}: external Korea map is still visually heavy: opacity=${result.koreaMapImageOpacity}`);
  invariant(result.koreaMapImageFilter.includes("grayscale"), `${label}: external Korea map filter missing: ${result.koreaMapImageFilter}`);
  invariant(result.denseFontSize >= 10.5, `${label}: analytical microcopy too small: ${result.denseFontSize}px`);
  invariant(result.externalBackground === "rgb(255, 255, 255)", `${label}: external context parent is not white: ${result.externalBackground}`);
  invariant(result.marketIntelBackground === "rgb(255, 255, 255)", `${label}: market intel parent is not white: ${result.marketIntelBackground}`);
  invariant(result.preferenceBackground === "rgb(255, 255, 255)", `${label}: preference parent is not white: ${result.preferenceBackground}`);
  invariant(result.prefMainBackground === "rgb(252, 250, 252)", `${label}: preference main surface is not branded neutral: ${result.prefMainBackground}`);
  invariant(Boolean(result.marketDirectionBackground || result.marketEmptyBackground), `${label}: market intelligence rendered neither supported nor empty state`);
  if (result.marketDirectionBackground) {
    invariant(result.marketDirectionBackground === "rgb(252, 250, 252)", `${label}: market direction surface is not branded neutral: ${result.marketDirectionBackground}`);
  } else {
    invariant(result.marketEmptyBackground === "rgb(255, 248, 236)", `${label}: market empty state is not light warning surface: ${result.marketEmptyBackground}`);
  }
  invariant(result.segmentButtonBackground === "rgb(251, 249, 251)", `${label}: simulator option retains dark surface: ${result.segmentButtonBackground}`);
  invariant(result.termCardBackground === "rgb(252, 250, 252)", `${label}: term card retains dark surface: ${result.termCardBackground}`);

  if (label === "desktop") {
    invariant(result.bodyFontSize >= 14, `desktop: body type too small=${result.bodyFontSize}`);
    invariant(result.mapHeight >= 400 && result.mapHeight <= 460, `desktop: expanded analysis map height=${result.mapHeight}`);
  } else {
    invariant(result.bodyFontSize >= 13.5, `mobile: body type too small=${result.bodyFontSize}`);
    invariant(result.kpis.length === 2 && Math.abs(result.kpis[0].y - result.kpis[1].y) < 2 && result.kpis[0].x !== result.kpis[1].x, "mobile: KPI cards are not two-column");
    invariant(result.mapHeight >= 330 && result.mapHeight <= 390, `mobile: expanded analysis map height=${result.mapHeight}`);
  }
}

(async () => {
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  try {
    const desktopViewport = { width: 1280, height: 900 };
    const desktop = await loadPage(browser, desktopViewport);
    await assertWorkspace(desktop.page, "desktop");
    await assertPageNavigation(browser, desktop.page, desktopViewport, "desktop");
    await desktop.page.screenshot({ path: path.join(workDir, "strategy-main-runtime-workspace-desktop.png"), fullPage: true });
    invariant(desktop.runtimeErrors.length === 0, `desktop runtime errors:\n${desktop.runtimeErrors.join("\n")}`);
    await desktop.context.close();

    const mobileViewport = { width: 390, height: 844 };
    const mobile = await loadPage(browser, mobileViewport);
    await assertWorkspace(mobile.page, "mobile");
    await assertPageNavigation(browser, mobile.page, mobileViewport, "mobile");
    await mobile.page.screenshot({ path: path.join(workDir, "strategy-main-runtime-workspace-mobile.png"), fullPage: true });
    invariant(mobile.runtimeErrors.length === 0, `mobile runtime errors:\n${mobile.runtimeErrors.join("\n")}`);
    await mobile.context.close();

    console.log("strategy decision workspace + unified page navigation smoke: PASS (desktop/mobile)");
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error.stack || error.message || String(error));
  process.exit(1);
});
