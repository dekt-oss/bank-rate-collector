const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("@playwright/test");

const baseUrl = process.env.STRATEGY_PREVIEW_BASE_URL || "http://127.0.0.1:4173";
const workDir = path.resolve("work");
fs.mkdirSync(workDir, { recursive: true });

function invariant(condition, message) {
  if (!condition) throw new Error(message);
}

function parseCssColor(value) {
  const parts = String(value || "").match(/[\d.]+/g)?.map(Number) || [];
  if (parts.length < 3) throw new Error(`unsupported CSS color: ${value}`);
  return { r: parts[0], g: parts[1], b: parts[2], a: parts.length >= 4 ? parts[3] : 1 };
}

function relativeLuminance(value) {
  const { r, g, b } = parseCssColor(value);
  const linear = [r, g, b].map((channel) => {
    const normalized = channel / 255;
    return normalized <= 0.04045
      ? normalized / 12.92
      : ((normalized + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
}

function contrastRatio(foreground, background) {
  const a = relativeLuminance(foreground);
  const b = relativeLuminance(background);
  const lighter = Math.max(a, b);
  const darker = Math.min(a, b);
  return (lighter + 0.05) / (darker + 0.05);
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
  await page.waitForSelector(
    'html[data-strategy-workspace="market-first-v2"][data-strategy-lean-ia="v3"][data-strategy-theme="light-v1"][data-strategy-palette="main-brand-v2"][data-strategy-decision-evidence-refinement="v1"]',
    { timeout: 30_000 },
  );
  return { context, page, runtimeErrors };
}

async function assertNavigation(browser, strategyPage, viewport, label) {
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  await page.route("**/favicon.ico", (route) => route.fulfill({ status: 204, body: "" }));
  const response = await page.goto(baseUrl + "/", { waitUntil: "domcontentloaded" });
  invariant(response && response.ok(), label + ": index HTTP failure");
  await page.waitForSelector("header.top > .page-nav", { timeout: 30_000 });
  const main = await page.locator("header.top > .page-nav a").allTextContents();
  const strategy = await strategyPage.locator("header.topbar > .nav a").allTextContents();
  invariant(JSON.stringify(main.map((x) => x.trim())) === JSON.stringify(["검색 조회", "전략 대시보드"]), label + ": main nav=" + main);
  invariant(JSON.stringify(strategy.map((x) => x.trim())) === JSON.stringify(["검색 조회", "전략 대시보드"]), label + ": strategy nav=" + strategy);

  if (label === "desktop") {
    const direct = await context.newPage();
    await direct.route("**/favicon.ico", (route) => route.fulfill({ status: 204, body: "" }));
    const directResponse = await direct.goto(baseUrl + "/strategy.html#workspace-competitor-position", { waitUntil: "networkidle" });
    invariant(directResponse && directResponse.ok(), label + ": direct-hash HTTP failure");
    await direct.waitForSelector('html[data-strategy-lean-ia="v3"]', { timeout: 30_000 });
    await direct.waitForFunction(() => location.hash === "#workspace-competitor-position");
    const directState = await direct.evaluate(() => ({
      target: Boolean(document.getElementById("workspace-competitor-position")),
      current: document.querySelector('#strategy-workspace-nav a[aria-current="location"]')?.dataset.workspaceTarget || "",
    }));
    invariant(directState.target && directState.current === "workspace-competitor-position", label + ": direct hash did not activate competitor target " + JSON.stringify(directState));
    await direct.close();
  }
  await context.close();
}

async function assertDecisionIA(page, label) {
  const result = await page.evaluate(() => {
    const precedes = (a, b) => Boolean(a && b && (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING));
    const visible = (node) => Boolean(node && !node.hidden && getComputedStyle(node).display !== "none" && getComputedStyle(node).visibility !== "hidden" && node.getClientRects().length > 0);
    const external = document.getElementById("external-market-context");
    const funding = document.getElementById("market-funding-competition");
    const marketLabel = document.getElementById("workspace-label-market");
    const kpis = document.querySelector(".grid.kpis");
    const marketIntel = document.getElementById("market-intelligence");
    const marketFlow = document.getElementById("market-flow");
    const designLabel = document.getElementById("workspace-label-design");
    const planning = document.getElementById("planning-zone");
    const competitor = document.getElementById("workspace-competitor-position");
    const top5 = competitor?.querySelector(".top5-card");
    const institution = competitor?.querySelector("#institution-funding-position");
    const handoff = document.querySelector(".ux-region-handoff");
    const productLabel = document.getElementById("workspace-label-product");
    const preference = document.getElementById("preference-intelligence");
    const special = document.getElementById("special-offer-radar");
    const evidence = document.getElementById("scope-evidence");
    const nav = document.querySelector('#strategy-workspace-nav[data-lean-ia-nav="1"]');
    const navItems = [...(nav?.querySelectorAll("a[data-workspace-target]") || [])].map((link) => [link.textContent.trim(), link.dataset.workspaceTarget]);
    const top5Headers = [...(top5?.querySelectorAll("thead th") || [])].filter(visible).map((node) => node.textContent.trim());
    const bank = top5?.querySelector(".bank");
    const strongRate = top5?.querySelector(".strongrate");
    const top5Contract = top5?.querySelector(".chip");
    const preferenceBadge = preference?.querySelector(".pref-intel-badge");
    const eventTile = document.getElementById("plan-flow")?.parentElement;
    const regionMap = document.querySelector(".workspace-detail.primary .mapcard");
    const fundingStrip = funding?.querySelector(".funding-market-strip");
    const fundingDetail = funding?.querySelector(".funding-analysis-grid");
    const hidden = (selector) => {
      const node = document.querySelector(selector);
      return !node || !visible(node);
    };
    return {
      order: [
        precedes(external, funding),
        precedes(funding, marketLabel),
        precedes(marketLabel, kpis),
        precedes(kpis, marketIntel),
        precedes(marketIntel, marketFlow),
        precedes(marketFlow, designLabel),
        precedes(designLabel, planning),
        precedes(planning, competitor),
        precedes(competitor, productLabel),
        precedes(productLabel, preference),
        !special || precedes(preference, special),
        !evidence || !special || precedes(special, evidence),
      ],
      externalVisible: visible(external),
      fundingVisible: visible(funding),
      fundingStripVisible: visible(fundingStrip),
      fundingDetailHidden: !fundingDetail || !visible(fundingDetail),
      competitorVisible: visible(competitor),
      top5InWrapper: Boolean(top5 && top5.closest("#workspace-competitor-position") === competitor),
      institutionInWrapper: Boolean(institution && institution.closest("#workspace-competitor-position") === competitor),
      top5Headers,
      bankFont: bank ? parseFloat(getComputedStyle(bank).fontSize) : 0,
      strongRateFont: strongRate ? parseFloat(getComputedStyle(strongRate).fontSize) : 0,
      top5ContractText: top5Contract?.textContent.trim() || "",
      top5ContractMarker: top5Contract?.dataset.contractLabel || "",
      preferenceBadgeText: preferenceBadge?.textContent.trim() || "",
      preferenceBadgeMarker: preferenceBadge?.dataset.contractLabel || "",
      eventTileHidden: Boolean(eventTile && !visible(eventTile)),
      duplicateHidden: [
        hidden("#market-flow details.changes"),
        hidden(".strategy-market-direction"),
        hidden(".ux-decision-readiness"),
        hidden(".ux-decision-menu"),
        hidden(".decision-integrated-insight"),
        hidden("#workspace-detail-disclosure"),
        hidden("#relative-pricing-r1"),
        hidden("#rate-funding-matrix"),
      ],
      handoffVisible: visible(handoff),
      handoffHref: handoff?.querySelector("a")?.getAttribute("href") || "",
      regionMapHidden: !regionMap || !visible(regionMap),
      navItems,
      navVisible: visible(nav),
      planningHeadlineVisible: visible(document.getElementById("lean-planning-headline")),
      planningDetailClosed: Boolean(document.getElementById("lean-planning-detail") && !document.getElementById("lean-planning-detail").open),
      coreSimulatorVisible: visible(document.getElementById("sim-form")),
      institutionDetailClosed: Boolean(document.getElementById("lean-institution-detail") && !document.getElementById("lean-institution-detail").open),
      preferenceDetailClosed: Boolean(document.getElementById("lean-preference-detail") && !document.getElementById("lean-preference-detail").open),
      specialDetailClosed: Boolean(document.getElementById("lean-special-detail") && !document.getElementById("lean-special-detail").open),
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
    };
  });

  invariant(result.order.every(Boolean), label + ": Lean IA order=" + JSON.stringify(result.order));
  invariant(result.externalVisible && result.fundingVisible && result.fundingStripVisible && result.fundingDetailHidden, label + ": market funding environment visibility wrong " + JSON.stringify(result));
  invariant(result.competitorVisible && result.top5InWrapper && result.institutionInWrapper, label + ": competitor wrapper composition wrong " + JSON.stringify(result));
  const expectedTop5Headers = label === "desktop"
    ? ["순위", "업권", "금융사 / 상품", "최고금리"]
    : [];
  invariant(JSON.stringify(result.top5Headers) === JSON.stringify(expectedTop5Headers), label + ": TOP5 visible headers=" + JSON.stringify(result.top5Headers));
  invariant(result.bankFont >= 13 && result.strongRateFont >= 15, label + ": TOP5 readability bank=" + result.bankFont + " rate=" + result.strongRateFont);
  invariant(result.top5ContractText === "공식 비교기준" && result.top5ContractMarker === "CANONICAL", label + ": TOP5 contract label=" + JSON.stringify([result.top5ContractText, result.top5ContractMarker]));
  invariant(result.preferenceBadgeText === "조건 구조 근거" && result.preferenceBadgeMarker === "D1 Structure Evidence", label + ": preference contract label=" + JSON.stringify([result.preferenceBadgeText, result.preferenceBadgeMarker]));
  invariant(result.eventTileHidden && result.duplicateHidden.every(Boolean), label + ": redundant/event surfaces remain visible " + JSON.stringify(result.duplicateHidden));
  invariant(
    result.planningHeadlineVisible
      && result.planningDetailClosed
      && !result.coreSimulatorVisible
      && result.institutionDetailClosed
      && result.preferenceDetailClosed
      && result.specialDetailClosed,
    label + ": progressive disclosure defaults wrong " + JSON.stringify({
      planningHeadline: result.planningHeadlineVisible,
      planningDetail: result.planningDetailClosed,
      coreSimulator: result.coreSimulatorVisible,
      institution: result.institutionDetailClosed,
      preference: result.preferenceDetailClosed,
      special: result.specialDetailClosed,
    }),
  );
  invariant(result.handoffVisible && result.handoffHref === "./" && result.regionMapHidden, label + ": Search region handoff contract broken");
  const expectedNav = [
    ["시장 자금환경", "external-market-context"],
    ["업권 수신 흐름", "market-funding-competition"],
    ["시장 금리 방향", "market-intelligence"],
    ["12개월 시장 추이", "workspace-market-trend"],
    ["신상품 금리 시뮬레이션", "planning-zone"],
    ["경쟁사 · 기관 포지션", "workspace-competitor-position"],
    ["우대조건 · 상품구조", "preference-intelligence"],
    ["특판 · 시장기회", "special-offer-radar"],
  ];
  invariant(JSON.stringify(result.navItems) === JSON.stringify(expectedNav), label + ": Lean nav items=" + JSON.stringify(result.navItems));
  invariant(label === "desktop" ? result.navVisible : !result.navVisible, label + ": floating nav responsive visibility=" + result.navVisible);
  invariant(result.scrollWidth <= result.clientWidth + 1, label + ": horizontal overflow " + result.scrollWidth + " > " + result.clientWidth);

  if (label === "desktop") {
    await page.locator('#strategy-workspace-nav a[data-workspace-target="workspace-competitor-position"]').click();
    await page.waitForFunction(() => location.hash === "#workspace-competitor-position");
    await page.locator('#strategy-workspace-nav a[data-workspace-target="external-market-context"]').click();
    await page.waitForFunction(() => location.hash === "#external-market-context");
    await page.evaluate(() => history.back());
    await page.waitForFunction(() => location.hash === "#workspace-competitor-position");
    await page.evaluate(() => history.forward());
    await page.waitForFunction(() => location.hash === "#external-market-context");
    const active = await page.locator('#strategy-workspace-nav a[aria-current="location"]').getAttribute("data-workspace-target");
    invariant(active === "external-market-context", label + ": back/forward active target=" + active);
  }
}

async function assertPrediction(page, label) {
  const initial = await page.evaluate(() => {
    const planning = document.getElementById("planning-zone");
    const strip = [...(planning?.querySelectorAll(".planning-strip>div") || [])]
      .find((node) => !node.hidden && getComputedStyle(node).display !== "none");
    const stripValue = strip?.querySelector("b");
    const predictionTitle = planning?.querySelector(".prediction-head b");
    const inputLabel = planning?.querySelector(".predict-inputs label");
    const formula = planning?.querySelector(".decision-formula");
    const evidence = planning?.querySelector(".decision-model-evidence");
    const responseDisclosure = planning?.querySelector(".rate-response-disclosure");
    const caveat = planning?.querySelector(".rate-response-caveat");
    const style = (node) => node ? getComputedStyle(node) : null;
    return {
      stripBackground: style(strip)?.backgroundImage || "",
      stripValueColor: style(stripValue)?.color || "",
      stripValueFont: parseFloat(style(stripValue)?.fontSize || "0"),
      predictionTitleFont: parseFloat(style(predictionTitle)?.fontSize || "0"),
      inputLabelFont: parseFloat(style(inputLabel)?.fontSize || "0"),
      formulaExists: Boolean(formula),
      formulaOpen: Boolean(formula?.open),
      formulaText: formula?.textContent || "",
      evidenceExists: Boolean(evidence),
      evidenceOpen: Boolean(evidence?.open),
      responseDisclosureExists: Boolean(responseDisclosure),
      responseDisclosureOpen: Boolean(responseDisclosure?.open),
      caveatText: caveat?.textContent || "",
      predictBridge: typeof window.predictInflow,
      rangeHidden: document.getElementById("inflow-range")?.closest(".simresult")?.classList.contains("decision-range-legacy") || false,
    };
  });
  invariant(initial.stripValueFont >= 15, `${label}: planning strip visible value font=${initial.stripValueFont}`);
  invariant(initial.predictionTitleFont >= 15, `${label}: prediction title font=${initial.predictionTitleFont}`);
  invariant(initial.inputLabelFont >= 12, `${label}: prediction input label font=${initial.inputLabelFont}`);
  invariant(initial.formulaExists && initial.formulaOpen && initial.formulaText.includes("rate_steps"), `${label}: formula detail missing/not open`);
  invariant(initial.evidenceExists && !initial.evidenceOpen, `${label}: model evidence should start collapsed`);
  invariant(initial.responseDisclosureExists && !initial.responseDisclosureOpen, `${label}: rate-response detail should start collapsed`);
  invariant(initial.caveatText.includes("실제 예측치가 아닙니다") && initial.caveatText.includes("별도 보정 단계") && !initial.caveatText.includes("forecast") && !initial.caveatText.includes("Stage E"), `${label}: technical caveat copy remains visible=${initial.caveatText}`);
  await page.locator(".rate-response-disclosure > summary").click();
  await page.waitForFunction(() => document.querySelector(".rate-response-disclosure")?.open === true);
  invariant(initial.predictBridge === "function", `${label}: public prediction bridge missing`);
  invariant(initial.rangeHidden, `${label}: ambiguous min~max total range card still visible`);

  await page.locator("#baseline-new").fill("100");
  await page.locator("#maturity-amount").fill("200");
  await page.locator("#rollover-rate").fill("60");
  await page.locator("#bonus-n").fill("0.10");
  await page.locator("#bonus-n").dispatchEvent("input");
  await page.waitForFunction(() => document.querySelectorAll(".decision-sensitivity-card").length === 3, null, { timeout: 10_000 });

  const result = await page.evaluate(() => {
    const cards = [...document.querySelectorAll(".decision-sensitivity-card")];
    const baseCard = document.querySelector('.decision-sensitivity-card[data-sensitivity="base"]');
    const baseMetrics = [...(baseCard?.querySelectorAll(".decision-sensitivity-metrics div") || [])];
    const plus10 = [...document.querySelectorAll("#rate-response-body tbody tr")].find((row) => row.querySelector(".scenario-name")?.textContent.trim() === "+10bp");
    return {
      labels: cards.map((card) => card.querySelector(".decision-sensitivity-title b")?.textContent.trim()),
      totals: cards.map((card) => card.querySelector(".decision-sensitivity-total")?.textContent.trim()),
      cards: cards.map((card) => ({ key: card.dataset.sensitivity, text: card.textContent })),
      rateResponseRows: document.querySelectorAll("#rate-response-body tbody tr").length,
      rateResponseText: document.getElementById("rate-response-body")?.textContent || "",
      baseTotal: baseCard?.querySelector(".decision-sensitivity-total")?.textContent.trim() || "",
      baseCost: baseMetrics.at(-1)?.querySelector("strong")?.textContent.trim() || "",
      cockpitTotal: plus10?.children[4]?.textContent.trim() || "",
      cockpitCost: plus10?.children[6]?.textContent.trim() || "",
      responseDisclosureOpen: document.querySelector(".rate-response-disclosure")?.open || false,
    };
  });
  invariant(JSON.stringify(result.labels) === JSON.stringify(["저민감", "기준", "고민감"]), `${label}: sensitivity labels=${result.labels}`);
  invariant(new Set(result.totals).size >= 2, `${label}: sensitivity totals do not react to beta/gamma=${result.totals}`);
  invariant(result.cards.every((x) => x.text.includes("신규자금") && x.text.includes("재예치") && x.text.includes("현재 대비") && x.text.includes("추가 표면이자비용")), `${label}: sensitivity card metrics missing`);
  invariant(result.rateResponseRows >= 4 && !result.rateResponseText.includes("예측엔진 확인"), `${label}: rate response bridge did not feed existing comparison table`);
  invariant(result.baseTotal && result.baseTotal === result.cockpitTotal, `${label}: 기준 민감도 총수신 불일치 card=${result.baseTotal} cockpit=${result.cockpitTotal}`);
  invariant(result.baseCost && result.baseCost === result.cockpitCost, `${label}: 기준 민감도 비용 불일치 card=${result.baseCost} cockpit=${result.cockpitCost}`);
  invariant(result.responseDisclosureOpen, `${label}: user-opened rate-response detail was re-collapsed during session`);
}

async function assertMarketEvidence(page, label) {
  const result = await page.evaluate(() => {
    const external = document.getElementById("external-market-context");
    const precedes = (a, b) => Boolean(a && b && (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING));
    const visible = (node) => Boolean(node && !node.hidden && getComputedStyle(node).display !== "none");
    const flowHead = external?.querySelector(".decision-external-heading:not(.secondary)");
    const flows = external?.querySelector(".external-context-flows");
    const rateHead = external?.querySelector(".decision-external-heading.secondary");
    const rates = external?.querySelector(".external-context-rates");
    const rateLabels = [...(rates?.querySelectorAll(".external-context-card span") || [])].map((x) => x.textContent.trim());
    const marketIntel = document.getElementById("market-intelligence");
    const marketCopy = marketIntel?.querySelector(".market-intel-head p")?.textContent || "";
    const breadth = marketIntel?.querySelector(".market-intel-breadth span:last-child")?.textContent || "";
    const marketBasis = marketIntel?.querySelector(".decision-evidence-basis")?.textContent || "";
    const changes = document.querySelector("#market-flow details.changes");
    const payload = JSON.parse(document.getElementById("rate-monitor-data")?.textContent || "{}");
    return {
      flowBeforeRate: precedes(flowHead, flows) && precedes(flows, rateHead) && precedes(rateHead, rates),
      externalText: external?.textContent || "",
      rateLabels,
      marketCopy,
      breadth,
      marketBasis,
      changesPresent: Boolean(changes),
      changesHidden: Boolean(changes && !visible(changes)),
      marketChangesPresent: Boolean(payload.strategy?.market_changes),
    };
  });
  invariant(result.flowBeforeRate, label + ": external flow/rate evidence order wrong");
  invariant(result.externalText.includes("공식 월간통계 최신 공표월"), label + ": source publication month copy missing");
  invariant(result.externalText.includes("추정·보간하지 않습니다"), label + ": no-interpolation boundary missing");
  invariant(result.rateLabels.some((x) => x.includes("순수저축성예금 신규취급액 가중평균")), label + ": weighted new-business rate label missing");
  invariant(result.rateLabels.some((x) => x.includes("1년 정기예금 신규취급액 가중평균")), label + ": 1y weighted new-business rate label missing");
  invariant(result.marketCopy.includes("동일 stable product") && result.marketCopy.includes("별도 Evidence"), label + ": snapshot/event distinction missing");
  invariant(result.marketBasis.includes("snapshot"), label + ": market intelligence basis missing");
  invariant(!result.breadth.includes("churn"), label + ": internal churn jargon leaked=" + result.breadth);
  if (result.breadth) {
    invariant(result.breadth.includes("인상") && result.breadth.includes("인하") && result.breadth.includes("이동없음") && result.breadth.includes("상위 10% 구성 교체율"), label + ": participation counts/turnover missing=" + result.breadth);
  }
  invariant(result.changesPresent && result.changesHidden && result.marketChangesPresent, label + ": market_changes owner contract must remain while event panel stays hidden " + JSON.stringify(result));
}

async function assertTrend(page, label) {
  await page.waitForSelector("#decision-trend-toggle", { timeout: 10_000 });
  const delta = await page.evaluate(() => ({
    active: document.querySelector("#decision-trend-toggle button.active")?.dataset.trendMode,
    axis: [...document.querySelectorAll("#trend-grid .axistext")].map((x) => x.textContent),
    basis: document.getElementById("decision-trend-basis")?.textContent || "",
    markers: document.querySelectorAll('#trend-series [data-decision-trend="1"]').length,
  }));
  invariant(delta.active === "delta", `${label}: trend default mode=${delta.active}`);
  invariant(delta.axis.some((x) => x.includes("bp")) && delta.basis.includes("첫 관측값을 0bp"), `${label}: delta trend basis/axis missing`);
  invariant(delta.markers > 0, `${label}: delta trend series not drawn`);

  await page.locator('#decision-trend-toggle button[data-trend-mode="level"]').click();
  const levelAxis = await page.locator("#trend-grid .axistext").allTextContents();
  invariant(levelAxis.some((x) => x.includes("%")), `${label}: absolute rate mode did not render percent axis`);
  await page.locator('#decision-trend-toggle button[data-trend-mode="delta"]').click();
}

async function assertVisualRuntimeContracts(page, label) {
  await page.waitForSelector("#strategy-rate-decision-simulator", { state: "visible", timeout: 10_000 });
  const legacyDetails = page.locator("#strategy-rate-decision-simulator details.rds-details");
  await legacyDetails.waitFor({ state: "visible", timeout: 10_000 });
  const legacyState = await page.evaluate(() => {
    const details = document.querySelector("#strategy-rate-decision-simulator details.rds-details");
    const cockpit = document.getElementById("public-structural-v2-cockpit");
    const finder = document.getElementById("public-structural-v2-factual-rate-finder");
    return {
      open: Boolean(details?.open),
      cockpitInLegacy: Boolean(details && cockpit && details.contains(cockpit)),
      finderInCockpit: Boolean(cockpit && finder && cockpit.contains(finder)),
    };
  });
  invariant(!legacyState.open, `${label}: detailed structural analysis must start collapsed`);
  invariant(legacyState.cockpitInLegacy, `${label}: Public Structural cockpit must stay inside detailed analysis`);
  invariant(legacyState.finderInCockpit, `${label}: Factual Finder must stay inside Public Structural detail`);
  await legacyDetails.locator("summary").click();
  await page.waitForFunction(() => document.querySelector("#strategy-rate-decision-simulator details.rds-details")?.open === true, null, { timeout: 10_000 });
  await page.waitForSelector("#public-structural-v2-cockpit", { state: "visible", timeout: 10_000 });
  await page.waitForSelector("#public-structural-v2-factual-rate-finder", { state: "visible", timeout: 10_000 });
  const result = await page.evaluate(() => {
    const rootStyle = getComputedStyle(document.documentElement);
    const effectiveBackground = (node) => {
      for (let current = node; current; current = current.parentElement) {
        const value = getComputedStyle(current).backgroundColor;
        const parts = String(value || "").match(/[\d.]+/g)?.map(Number) || [];
        if (parts.length >= 3 && (parts.length < 4 || parts[3] > 0.01)) return value;
      }
      return "rgb(255, 255, 255)";
    };
    const sectionSoft = document.querySelector(".workspace-section-label span");
    const scenarioNote = document.querySelector(".rate-response-table .scenario-note");
    const mapCard = document.querySelector(".workspace-detail.primary .mapcard");
    const cockpitHost = document.getElementById("public-structural-v2-cockpit");
    const factualHost = document.getElementById("public-structural-v2-factual-rate-finder");
    const hosts = [cockpitHost, factualHost].filter(Boolean);
    const textNodes = hosts.flatMap((host) => [...host.querySelectorAll("*")]).filter((node) => {
      const hasDirectText = [...node.childNodes].some(
        (child) => child.nodeType === Node.TEXT_NODE && child.textContent.trim(),
      );
      if (!hasDirectText) return false;
      const style = getComputedStyle(node);
      const rect = node.getBoundingClientRect();
      return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
    });
    const fontSizes = textNodes.map((node) => ({
      text: node.textContent.trim().slice(0, 80),
      size: parseFloat(getComputedStyle(node).fontSize || "0"),
    }));
    const tooSmall = fontSizes.filter((item) => item.size < 10.5);
    const candidateCell = document.querySelector("#public-structural-v2-cockpit .psv2-table tbody td");
    const candidateBeforeStyle = candidateCell ? getComputedStyle(candidateCell, "::before") : null;
    const candidateBeforeFont = candidateBeforeStyle
      ? parseFloat(candidateBeforeStyle.fontSize || "0")
      : 0;
    const candidateCellRect = candidateCell?.getBoundingClientRect();
    const candidateBeforeContent = candidateBeforeStyle?.content || "";
    const candidateBeforeDisplay = candidateBeforeStyle?.display || "none";
    const candidateBeforeVisibility = candidateBeforeStyle?.visibility || "hidden";
    const chart = document.querySelector("#public-structural-v2-cockpit .psv2-chart");
    const chartStyle = chart ? getComputedStyle(chart) : null;
    const chartRect = chart?.getBoundingClientRect();
    const xTicks = [...document.querySelectorAll('#public-structural-v2-cockpit .psv2-chart text.axis[text-anchor="middle"]')]
      .filter((node) => getComputedStyle(node).visibility !== "hidden")
      .map((node) => {
        const rect = node.getBoundingClientRect();
        return { text: node.textContent.trim(), left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom };
      });
    const axisCollisions = [];
    for (let i = 0; i < xTicks.length; i += 1) {
      for (let j = i + 1; j < xTicks.length; j += 1) {
        const a = xTicks[i];
        const b = xTicks[j];
        const width = Math.min(a.right, b.right) - Math.max(a.left, b.left);
        const height = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
        if (width > 1 && height > 1) axisCollisions.push([a.text, b.text]);
      }
    }
    return {
      accent: rootStyle.getPropertyValue("--accent").trim(),
      accentInk: rootStyle.getPropertyValue("--accent-ink").trim(),
      sectionSoftColor: sectionSoft ? getComputedStyle(sectionSoft).color : "",
      sectionSoftBackground: sectionSoft ? effectiveBackground(sectionSoft) : "",
      scenarioNoteColor: scenarioNote ? getComputedStyle(scenarioNote).color : "",
      scenarioNoteBackground: scenarioNote ? effectiveBackground(scenarioNote) : "",
      mapCardDisplay: mapCard ? getComputedStyle(mapCard).display : "missing",
      cockpitVisible: Boolean(cockpitHost && getComputedStyle(cockpitHost).display !== "none"),
      factualFinderVisible: Boolean(factualHost && getComputedStyle(factualHost).display !== "none"),
      chartCount: document.querySelectorAll("#public-structural-v2-cockpit .psv2-chart").length,
      chartDisplay: chartStyle?.display || "none",
      chartVisibility: chartStyle?.visibility || "hidden",
      chartBox: chartRect
        ? { width: chartRect.width, height: chartRect.height }
        : { width: 0, height: 0 },
      fontCount: fontSizes.length,
      tooSmall,
      candidateBeforeFont,
      candidateBeforeContent,
      candidateBeforeDisplay,
      candidateBeforeVisibility,
      candidateCellBox: candidateCellRect
        ? { width: candidateCellRect.width, height: candidateCellRect.height }
        : { width: 0, height: 0 },
      axisCollisions,
    };
  });
  invariant(result.accent.toUpperCase() === "#D33A7C", `${label}: computed brand accent=${result.accent}`);
  invariant(result.accentInk.toUpperCase() === "#5B2F64", `${label}: computed brand accent ink=${result.accentInk}`);
  const sectionSoftContrast = contrastRatio(result.sectionSoftColor, result.sectionSoftBackground);
  const scenarioNoteContrast = contrastRatio(result.scenarioNoteColor, result.scenarioNoteBackground);
  invariant(
    sectionSoftContrast >= 4.5,
    `${label}: workspace section supporting text contrast=${sectionSoftContrast.toFixed(2)}`,
  );
  invariant(
    scenarioNoteContrast >= 4.5,
    `${label}: scenario note contrast=${scenarioNoteContrast.toFixed(2)}`,
  );
  invariant(result.mapCardDisplay === "none", `${label}: Strategy regional map resurfaced display=${result.mapCardDisplay}`);
  invariant(result.cockpitVisible && result.chartCount === 1, `${label}: active Public Structural Response Surface missing`);
  invariant(
    result.chartDisplay !== "none"
      && result.chartVisibility !== "hidden"
      && result.chartBox.width > 0
      && result.chartBox.height > 0,
    `${label}: Public Structural Response Surface not rendered display=${result.chartDisplay} visibility=${result.chartVisibility} box=${JSON.stringify(result.chartBox)}`,
  );
  invariant(result.factualFinderVisible, `${label}: Factual Finder runtime host missing`);
  invariant(result.fontCount > 0 && result.tooSmall.length === 0, `${label}: Public Structural computed font below 10.5px=${JSON.stringify(result.tooSmall)}`);
  if (label === "mobile") {
    const pseudoContent = result.candidateBeforeContent.replace(/^["']|["']$/g, "").trim();
    invariant(
      pseudoContent && !["none", "normal"].includes(pseudoContent),
      `${label}: candidate-card pseudo label content missing=${result.candidateBeforeContent}`,
    );
    invariant(
      result.candidateBeforeDisplay !== "none"
        && result.candidateBeforeVisibility !== "hidden"
        && result.candidateCellBox.width > 0
        && result.candidateCellBox.height > 0,
      `${label}: candidate-card pseudo label not rendered display=${result.candidateBeforeDisplay} visibility=${result.candidateBeforeVisibility} cell=${JSON.stringify(result.candidateCellBox)}`,
    );
    invariant(result.candidateBeforeFont >= 10.5, `${label}: candidate-card pseudo label font=${result.candidateBeforeFont}px`);
  }
  invariant(result.axisCollisions.length === 0, `${label}: visible Response Surface x-axis collision=${JSON.stringify(result.axisCollisions)}`);
}

async function runViewport(browser, label, viewport) {
  const { context, page, runtimeErrors } = await loadPage(browser, viewport);
  await assertDecisionIA(page, label);
  const depositFamily = page.locator('[data-product-family-toggle="deposit"]');
  const savingsFamily = page.locator('[data-product-family-toggle="savings"]');
  await depositFamily.waitFor({ state: "attached", timeout: 10_000 });
  if (!(await depositFamily.isChecked())) await depositFamily.check();
  if (await savingsFamily.isChecked()) await savingsFamily.uncheck();
  const predictionToggle = page.locator("#prediction-toggle");
  const predictionPanel = page.locator("#prediction-panel");
  await predictionToggle.waitFor({ state: "visible", timeout: 10_000 });
  if (await predictionPanel.isHidden()) await predictionToggle.click();
  await page.waitForFunction(() => document.getElementById("lean-planning-detail")?.open === true, null, { timeout: 10_000 });
  await page.waitForFunction(
    () => document.getElementById("prediction-panel")?.hidden === false
      && document.getElementById("prediction-toggle")?.getAttribute("aria-expanded") === "true",
    null,
    { timeout: 10_000 },
  );
  await page.locator("#baseline-new").waitFor({ state: "visible", timeout: 10_000 });
  await assertPrediction(page, label);
  await assertVisualRuntimeContracts(page, label);
  await assertMarketEvidence(page, label);
  await assertTrend(page, label);
  await assertNavigation(browser, page, viewport, label);

  const bodyFont = await page.evaluate(() => parseFloat(getComputedStyle(document.body).fontSize));
  invariant(bodyFont >= (label === "desktop" ? 17 : 16), `${label}: body font too small=${bodyFont}`);
  const dims = await page.evaluate(() => ({ client: document.documentElement.clientWidth, scroll: document.documentElement.scrollWidth }));
  invariant(dims.scroll <= dims.client + 1, `${label}: final horizontal overflow ${dims.scroll} > ${dims.client}`);
  invariant(runtimeErrors.length === 0, `${label}: runtime errors:\n${runtimeErrors.join("\n")}`);

  await page.screenshot({ path: path.join(workDir, `strategy-main-runtime-workspace-${label}.png`), fullPage: true });
  await context.close();
}

(async () => {
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  try {
    await runViewport(browser, "desktop", { width: 1440, height: 1000 });
    await runViewport(browser, "mobile", { width: 390, height: 844 });
    console.log("strategy decision evidence refinement smoke: PASS (desktop/mobile)");
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error.stack || error.message || String(error));
  process.exit(1);
});