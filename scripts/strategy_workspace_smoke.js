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

function before(a, b) {
  return Boolean(a && b && (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING));
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
    const readiness = document.querySelector(".ux-decision-readiness");
    const insight = document.querySelector(".decision-integrated-insight");
    const top5 = document.querySelector(".decision-integrated-top5");
    const planning = document.getElementById("planning-zone");
    const productLabel = document.getElementById("workspace-label-product");
    const preference = document.getElementById("preference-intelligence");
    const hiddenLegacy = document.querySelector(".workspace-insights");
    const hiddenDetail = document.querySelector(".workspace-detail.primary");
    return {
      order: [before(readiness, insight), before(insight, top5), before(top5, planning)],
      insightTitle: insight?.querySelector(".head h2")?.textContent.trim() || "",
      insightTags: [...(insight?.querySelectorAll(".insight em") || [])].map((x) => x.textContent.trim()),
      productTitle: productLabel?.querySelector("strong")?.textContent.trim() || "",
      productBeforePreference: before(productLabel, preference),
      legacyHidden: Boolean(hiddenLegacy?.hidden),
      detailHidden: Boolean(hiddenDetail?.hidden),
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
    };
  });
  invariant(result.order.every(Boolean), `${label}: readiness -> insight -> TOP5 -> planning order=${result.order}`);
  invariant(result.insightTitle === "금리결정 인사이트", `${label}: insight title=${result.insightTitle}`);
  invariant(!result.insightTags.includes("저축은행 시장 방향") && !result.insightTags.includes("당사 위치"), `${label}: duplicated decision insight remains=${result.insightTags}`);
  invariant(result.productTitle === "상품·우대조건 설계" && result.productBeforePreference, `${label}: product section label/order wrong`);
  invariant(result.legacyHidden && result.detailHidden, `${label}: duplicated legacy/detail shell not hidden`);
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

  const result = await page.evaluate(() => ({
    labels: [...document.querySelectorAll(".decision-sensitivity-card .decision-sensitivity-title b")].map((x) => x.textContent.trim()),
    totals: [...document.querySelectorAll(".decision-sensitivity-card .decision-sensitivity-total")].map((x) => x.textContent.trim()),
    cards: [...document.querySelectorAll(".decision-sensitivity-card")].map((card) => ({
      key: card.dataset.sensitivity,
      text: card.textContent,
    })),
    rateResponseRows: document.querySelectorAll("#rate-response-body tbody tr").length,
    rateResponseText: document.getElementById("rate-response-body")?.textContent || "",
  }));
  invariant(JSON.stringify(result.labels) === JSON.stringify(["저민감", "기준", "고민감"]), `${label}: sensitivity labels=${result.labels}`);
  invariant(new Set(result.totals).size >= 2, `${label}: sensitivity totals do not react to beta/gamma=${result.totals}`);
  invariant(result.cards.every((x) => x.text.includes("신규자금") && x.text.includes("재예치") && x.text.includes("현재 대비") && x.text.includes("추가 표면이자비용")), `${label}: sensitivity card metrics missing`);
  invariant(result.rateResponseRows >= 4 && !result.rateResponseText.includes("예측엔진 확인"), `${label}: rate response bridge did not feed existing comparison table`);
}

async function assertMarketEvidence(page, label) {
  const result = await page.evaluate(() => {
    const external = document.getElementById("external-market-context");
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
      flowBeforeRate: before(flowHead, flows) && before(flows, rateHead) && before(rateHead, rates),
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
  invariant(result.changesOpen && result.changesText.includes("상품변경 이벤트") && result.changesText.includes("별도 지표"), `${label}: recent event panel not permanently open/basis missing`);

  const details = page.locator("#market-flow details.changes");
  await details.evaluate((node) => { node.open = false; node.dispatchEvent(new Event("toggle")); });
  await page.waitForTimeout(50);
  invariant(await details.evaluate((node) => node.open), `${label}: recent market events could be closed`);
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

async function runViewport(browser, label, viewport) {
  const { context, page, runtimeErrors } = await loadPage(browser, viewport);
  await assertDecisionIA(page, label);
  await assertPrediction(page, label);
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
