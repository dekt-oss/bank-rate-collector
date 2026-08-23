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
  await page.waitForSelector(
    'html[data-strategy-workspace="decision-first-v1"][data-strategy-theme="light-v1"][data-strategy-palette="main-brand-v2"][data-strategy-decision-evidence-refinement="v1"]',
    { timeout: 30_000 },
  );
  return { context, page, runtimeErrors };
}

async function assertNavigation(browser, strategyPage, viewport, label) {
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  await page.route("**/favicon.ico", (route) => route.fulfill({ status: 204, body: "" }));
  const response = await page.goto(`${baseUrl}/`, { waitUntil: "domcontentloaded" });
  invariant(response && response.ok(), `${label}: index HTTP failure`);
  await page.waitForSelector("header.top > .page-nav", { timeout: 30_000 });
  const main = await page.locator("header.top > .page-nav a").allTextContents();
  const strategy = await strategyPage.locator("header.topbar > .nav a").allTextContents();
  invariant(JSON.stringify(main.map((x) => x.trim())) === JSON.stringify(["검색 조회", "전략 대시보드"]), `${label}: main nav=${main}`);
  invariant(JSON.stringify(strategy.map((x) => x.trim())) === JSON.stringify(["검색 조회", "전략 대시보드"]), `${label}: strategy nav=${strategy}`);
  await context.close();
}

async function assertDecisionIA(page, label) {
  const result = await page.evaluate(() => {
    const precedes = (a, b) => Boolean(a && b && (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING));
    const readiness = document.querySelector(".ux-decision-readiness");
    const insight = document.querySelector(".decision-integrated-insight");
    const top5 = document.querySelector(".decision-integrated-top5");
    const planning = document.getElementById("planning-zone");
    const productLabel = document.getElementById("workspace-label-product");
    const preference = document.getElementById("preference-intelligence");
    const hiddenLegacy = document.querySelector(".workspace-insights");
    const hiddenDetail = document.querySelector(".workspace-detail.primary");
    const handoff = document.querySelector(".ux-region-handoff");
    return {
      order: [precedes(readiness, insight), precedes(insight, top5), precedes(top5, planning)],
      insightTitle: insight?.querySelector(".head h2")?.textContent.trim() || "",
      insightTags: [...(insight?.querySelectorAll(".insight em") || [])].map((x) => x.textContent.trim()),
      productTitle: productLabel?.querySelector("strong")?.textContent.trim() || "",
      productBeforePreference: precedes(productLabel, preference),
      legacyHidden: Boolean(hiddenLegacy?.hidden),
      detailHidden: Boolean(hiddenDetail?.hidden),
      handoffVisible: Boolean(handoff && !handoff.hidden),
      handoffHref: handoff?.querySelector("a")?.getAttribute("href") || "",
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
    };
  });
  invariant(result.order.every(Boolean), `${label}: readiness -> insight -> TOP5 -> planning order=${result.order}`);
  invariant(result.insightTitle === "금리결정 인사이트", `${label}: insight title=${result.insightTitle}`);
  invariant(!result.insightTags.includes("저축은행 시장 방향") && !result.insightTags.includes("당사 위치"), `${label}: duplicated decision insight remains=${result.insightTags}`);
  invariant(result.productTitle === "상품·우대조건 설계" && result.productBeforePreference, `${label}: product section label/order wrong`);
  invariant(result.legacyHidden && result.detailHidden, `${label}: duplicated legacy/detail shell not hidden`);
  invariant(result.handoffVisible && result.handoffHref === "./", `${label}: Search 지역 상세 handoff가 유지되지 않음`);
  invariant(result.scrollWidth <= result.clientWidth + 1, `${label}: horizontal overflow ${result.scrollWidth} > ${result.clientWidth}`);
}

async function assertPrediction(page, label) {
  const initial = await page.evaluate(() => {
    const planning = document.querySelector(".workspace-decision");
    const strip = planning?.querySelector(".planning-strip>div");
    const stripValue = strip?.querySelector("b");
    const predictionTitle = planning?.querySelector(".prediction-head b");
    const inputLabel = planning?.querySelector(".predict-inputs label");
    const formula = planning?.querySelector(".decision-formula");
    const evidence = planning?.querySelector(".decision-model-evidence");
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
      predictBridge: typeof window.predictInflow,
      rangeHidden: document.getElementById("inflow-range")?.closest(".simresult")?.classList.contains("decision-range-legacy") || false,
    };
  });
  invariant(initial.stripBackground.includes("linear-gradient"), `${label}: planning strip still faint/no explicit surface`);
  invariant(initial.stripValueColor === "rgb(46, 28, 50)", `${label}: planning strip value color=${initial.stripValueColor}`);
  invariant(initial.stripValueFont >= 17, `${label}: planning strip value font=${initial.stripValueFont}`);
  invariant(initial.predictionTitleFont >= 15, `${label}: prediction title font=${initial.predictionTitleFont}`);
  invariant(initial.inputLabelFont >= 12, `${label}: prediction input label font=${initial.inputLabelFont}`);
  invariant(initial.formulaExists && initial.formulaOpen && initial.formulaText.includes("rate_steps"), `${label}: formula detail missing/not open`);
  invariant(initial.evidenceExists && !initial.evidenceOpen, `${label}: model evidence should start collapsed`);
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
    };
  });
  invariant(JSON.stringify(result.labels) === JSON.stringify(["저민감", "기준", "고민감"]), `${label}: sensitivity labels=${result.labels}`);
  invariant(new Set(result.totals).size >= 2, `${label}: sensitivity totals do not react to beta/gamma=${result.totals}`);
  invariant(result.cards.every((x) => x.text.includes("신규자금") && x.text.includes("재예치") && x.text.includes("현재 대비") && x.text.includes("추가 표면이자비용")), `${label}: sensitivity card metrics missing`);
  invariant(result.rateResponseRows >= 4 && !result.rateResponseText.includes("예측엔진 확인"), `${label}: rate response bridge did not feed existing comparison table`);
  invariant(result.baseTotal && result.baseTotal === result.cockpitTotal, `${label}: 기준 민감도 총수신 불일치 card=${result.baseTotal} cockpit=${result.cockpitTotal}`);
  invariant(result.baseCost && result.baseCost === result.cockpitCost, `${label}: 기준 민감도 비용 불일치 card=${result.baseCost} cockpit=${result.cockpitCost}`);
}

async function assertMarketEvidence(page, label) {
  const result = await page.evaluate(() => {
    const external = document.getElementById("external-market-context");
    const precedes = (a, b) => Boolean(a && b && (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING));
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
    return {
      flowBeforeRate: precedes(flowHead, flows) && precedes(flows, rateHead) && precedes(rateHead, rates),
      externalText: external?.textContent || "",
      rateLabels,
      marketCopy,
      breadth,
      marketBasis,
      changesOpen: Boolean(changes?.open),
      changesText: changes?.textContent || "",
    };
  });
  invariant(result.flowBeforeRate, `${label}: external flow/rate evidence order wrong`);
  invariant(result.externalText.includes("공식 월간통계 최신 공표월"), `${label}: source publication month copy missing`);
  invariant(result.externalText.includes("추정·보간하지 않습니다"), `${label}: no-interpolation boundary missing`);
  invariant(result.rateLabels.some((x) => x.includes("순수저축성예금 신규취급액 가중평균")), `${label}: weighted new-business rate label missing`);
  invariant(result.rateLabels.some((x) => x.includes("1년 정기예금 신규취급액 가중평균")), `${label}: 1y weighted new-business rate label missing`);
  invariant(result.marketCopy.includes("동일 stable product") && result.marketCopy.includes("별도 Evidence"), `${label}: snapshot/event distinction missing`);
  invariant(result.marketBasis.includes("snapshot"), `${label}: market intelligence basis missing`);
  invariant(!result.breadth.includes("churn"), `${label}: internal churn jargon leaked=${result.breadth}`);
  if (result.breadth) {
    invariant(result.breadth.includes("인상") && result.breadth.includes("인하") && result.breadth.includes("이동없음") && result.breadth.includes("상위 10% 구성 교체율"), `${label}: participation counts/turnover missing=${result.breadth}`);
  }
  invariant(result.changesOpen && result.changesText.includes("상품변경 이벤트") && result.changesText.includes("별도 지표"), `${label}: recent event panel default-open/basis missing`);

  const details = page.locator("#market-flow details.changes");
  await details.locator("summary").click();
  await page.waitForTimeout(100);
  invariant(!(await details.evaluate((node) => node.open)), `${label}: 사용자가 최근 시장 이벤트를 접을 수 없음`);
  await page.waitForTimeout(100);
  invariant(!(await details.evaluate((node) => node.open)), `${label}: 접은 최근 시장 이벤트가 자동으로 다시 열림`);
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
  await page.waitForSelector("#public-structural-v2-cockpit", { state: "visible", timeout: 10_000 });
  await page.waitForSelector("#public-structural-v2-factual-rate-finder", { state: "visible", timeout: 10_000 });
  const result = await page.evaluate(() => {
    const rootStyle = getComputedStyle(document.documentElement);
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
      mapCardDisplay: mapCard ? getComputedStyle(mapCard).display : "missing",
      cockpitVisible: Boolean(cockpitHost && getComputedStyle(cockpitHost).display !== "none"),
      factualFinderVisible: Boolean(factualHost && getComputedStyle(factualHost).display !== "none"),
      chartCount: document.querySelectorAll("#public-structural-v2-cockpit .psv2-chart").length,
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
  invariant(result.mapCardDisplay === "none", `${label}: Strategy regional map resurfaced display=${result.mapCardDisplay}`);
  invariant(result.cockpitVisible && result.chartCount === 1, `${label}: active Public Structural Response Surface missing`);
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
