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
      const boundary = document.getElementById("strategy-decision-boundary");
      const bridge = document.getElementById("strategy-region-bridge");
      return Boolean(count && error && error.hidden && boundary && bridge && count.textContent.trim() !== "—");
    },
    null,
    { timeout: 30_000 },
  );
  invariant(await page.locator("#error").isHidden(), "strategy runtime error banner is visible");
}

async function selectMode(page, mode, expectedLabel) {
  const button = page.locator(`[data-market-mode="${mode}"]`);
  await button.click();
  await page.waitForFunction(
    ({ mode, label }) => {
      const active = document.querySelector(`[data-market-mode="${mode}"]`);
      return active?.classList.contains("active")
        && document.getElementById("scope-pill")?.textContent.trim() === label;
    },
    { mode, label: expectedLabel },
    { timeout: 10_000 },
  );
}

async function strategySectorMeta(page, sector) {
  return page.evaluate(async (key) => {
    const response = await fetch("data/strategy-table.json");
    if (!response.ok) throw new Error(`strategy-table.json HTTP ${response.status}`);
    const packed = await response.json();
    return packed.strategy_universe?.sectors?.[key] || null;
  }, sector);
}

async function waitForPositiveCount(page) {
  await page.waitForFunction(
    () => Number(document.getElementById("count")?.textContent.replaceAll(",", "") || 0) > 0,
    null,
    { timeout: 10_000 },
  );
}

async function assertNoHorizontalOverflow(page, label) {
  const metrics = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }));
  invariant(
    metrics.scrollWidth <= metrics.clientWidth + 1,
    `${label} horizontal overflow: ${metrics.scrollWidth} > ${metrics.clientWidth}`,
  );
}

async function assertMarketIntelligence(page) {
  const panel = page.locator("#market-intelligence");
  invariant(await panel.count() === 1, "Stage C2 Market Intelligence panel이 없음");
  invariant((await page.locator("#market-intelligence-body").textContent()).trim().length > 0, "Stage C2 body가 비어 있음");
  invariant(await page.locator('[data-mi-sector="savings_bank"]').count() === 1, "C2 저축은행 selector가 없음");
  invariant(await page.locator('[data-mi-term="12"]').count() === 1, "C2 12개월 selector가 없음");
  invariant(await page.locator('[data-mi-window="7"]').count() === 1, "C2 7D selector가 없음");
  invariant(await page.locator('[data-mi-window="30"]').count() === 1, "C2 30D selector가 없음");

  await page.locator('[data-mi-window="7"]').click();
  await page.waitForFunction(
    () => document.querySelector('[data-mi-window="7"]')?.classList.contains("active"),
    null,
    { timeout: 5_000 },
  );
  invariant((await page.locator("#market-intelligence-body").textContent()).trim().length > 0, "C2 7D 결과가 비어 있음");

  await page.locator('[data-mi-sector="nh_local"]').click();
  await page.waitForFunction(
    () => document.querySelector('[data-mi-sector="nh_local"]')?.classList.contains("active"),
    null,
    { timeout: 5_000 },
  );
  const nhText = await page.locator("#market-intelligence-body").textContent();
  invariant(
    nhText.includes("과거 최고금리 계약 미지원") && nhText.includes("e-joy"),
    "NH historical fail-closed 사유가 C2에 표시되지 않음",
  );
  await page.locator('[data-mi-sector="savings_bank"]').click();
  await page.locator('[data-mi-term="12"]').click();
  await page.locator('[data-mi-window="30"]').click();
}

async function assertExternalMarketContext(page) {
  const panel = page.locator("#external-market-context");
  invariant(await panel.count() === 1, "Stage E0-6 External Market Context panel이 없음");
  invariant(await panel.isVisible(), "E0-6 패널이 보이지 않음");
  const text = await panel.textContent();
  invariant(text.includes("시장 자금환경"), "E0-6 제목이 렌더되지 않음");
  invariant(text.includes("농·축협과 1:1 동일하지 않음"), "E0-6 해석 경계 문구가 없음");
  invariant(await panel.locator(".external-context-card").count() === 3, "E0-6 금리 카드 3장이 렌더되지 않음");
  invariant(await panel.locator(".external-flow").count() === 4, "E0-6 업권 잔액 카드 4장이 렌더되지 않음");
}

async function assertRoleSeparation(page) {
  const state = await page.evaluate(() => {
    const map = document.getElementById("map-card");
    const kpis = document.querySelector(".kpis");
    const bridge = document.getElementById("strategy-region-bridge");
    const boundary = document.getElementById("strategy-decision-boundary");
    return {
      mapDisplay: map ? getComputedStyle(map).display : "missing",
      mapAriaHidden: map?.getAttribute("aria-hidden"),
      kpiDisplay: kpis ? getComputedStyle(kpis).display : "missing",
      bridgeVisible: Boolean(bridge && getComputedStyle(bridge).display !== "none"),
      bridgeText: bridge?.textContent || "",
      boundaryText: boundary?.textContent || "",
      top5Title: document.getElementById("top5-title")?.textContent.trim() || "",
      top5Copy: document.getElementById("top5-copy")?.textContent.trim() || "",
    };
  });
  invariant(state.mapDisplay === "none", `Strategy full map is still visible: ${state.mapDisplay}`);
  invariant(state.mapAriaHidden === "true", `Strategy map aria-hidden=${state.mapAriaHidden}`);
  invariant(state.kpiDisplay === "none", `duplicate Strategy KPI strip is still visible: ${state.kpiDisplay}`);
  invariant(state.bridgeVisible, "지역 상세 Main 연결 카드가 보이지 않음");
  invariant(state.bridgeText.includes("검색 조회") && state.bridgeText.includes("부산"), "지역 상세 연결 문구가 불완전함");
  invariant(state.boundaryText.includes("현재 판단 가능") && state.boundaryText.includes("내부자료 후 확정 가능"), "의사결정 가능범위가 표시되지 않음");
  invariant(state.boundaryText.includes("FTP") && state.boundaryText.includes("최적금리"), "calibration boundary가 불완전함");
  invariant(state.top5Title === "가격결정 경쟁 기준 TOP 5", `TOP5 role label=${state.top5Title}`);
  invariant(state.top5Copy.includes("상단 금리 anchor"), `TOP5 role copy=${state.top5Copy}`);
}

async function assertStrategyReport(page) {
  invariant(await page.locator("#strategy-report-button").isVisible(), "Strategy 보고서 출력 버튼이 없음");
  const report = await page.evaluate(() => {
    const api = window.__rateMonitorReport;
    if (!api || api.kind !== "strategy") return null;
    const root = api.build();
    return {
      kind: root?.dataset.reportKind || "",
      text: root?.textContent || "",
      maps: root?.querySelectorAll("#geo-map, .mapstage, .mapcard").length || 0,
      tables: root?.querySelectorAll("table").length || 0,
    };
  });
  invariant(report?.kind === "strategy", `Strategy report kind=${report?.kind}`);
  invariant(report.text.includes("수신상품 금리결정 검토보고서"), "Strategy report title missing");
  invariant(report.text.includes("내부 수신실적 미보정") && report.text.includes("최적금리 확정값이 아닙니다"), "Strategy report calibration caveat missing");
  invariant(report.text.includes("가격결정 경쟁 기준 TOP 5"), "Strategy report competitor benchmark missing");
  invariant(report.text.includes("전국 지도 자체는") && report.text.includes("중복 포함하지 않습니다"), "Strategy report map exclusion note missing");
  invariant(report.maps === 0, `Strategy report unexpectedly contains map DOM: ${report.maps}`);
  invariant(report.tables >= 1, "Strategy report has no decision/competitor table");
  await page.evaluate(() => window.__rateMonitorReport?.cleanup());
}

async function runDesktop(browser) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await context.newPage();
  const runtimeErrors = [];
  page.on("pageerror", (error) => runtimeErrors.push(`pageerror: ${error.message}`));
  page.on("console", (message) => { if (message.type() === "error") runtimeErrors.push(`console: ${message.text()}`); });

  await waitForDashboard(page);
  await assertRoleSeparation(page);
  await assertStrategyReport(page);
  await assertMarketIntelligence(page);
  await assertExternalMarketContext(page);

  for (const sector of ["cu", "kfcc", "nh_local"]) {
    const meta = await strategySectorMeta(page, sector);
    invariant(meta?.strategy_rate_capability === true && meta?.selectable === true, `${sector} Strategy 최고금리 capability가 열리지 않음`);
    invariant(!(await page.locator(`[data-sector="${sector}"]`).isDisabled()), `${sector} selector가 비활성화됨`);
  }

  await selectMode(page, "savings_bank", "저축은행");
  await waitForPositiveCount(page);
  invariant(await page.locator("#market-flow").isVisible(), "저축은행 이력 block이 숨겨짐");
  invariant(await page.locator("#sim-form").isVisible(), "저축은행 시뮬레이터가 숨겨짐");
  invariant(await page.locator("#top5 tr").count() > 0, "저축은행 TOP5가 비어 있음");

  await selectMode(page, "mutual_finance", "상호금융");
  await waitForPositiveCount(page);
  invariant(await page.locator("#market-flow").isHidden(), "상호금융 단독에서 저축은행 이력 block이 노출됨");
  invariant(await page.locator("#sim-form").isHidden(), "상호금융 단독에서 고려저축은행 시뮬레이터가 열림");
  invariant(await page.locator("#market-intelligence").isVisible(), "상호금융 모드에서 C2 패널이 숨겨짐");
  invariant(await page.locator("#top5 tr").count() > 0, "상호금융 TOP5가 비어 있음");

  await selectMode(page, "combined", "저축은행 + 상호금융");
  await waitForPositiveCount(page);
  invariant(cleanNumber(await page.locator("#count").textContent()) > 0, "통합 12M 비교군이 비어 있음");
  invariant(await page.locator("#top5 tr").count() > 0, "통합 TOP5가 비어 있음");

  await assertRoleSeparation(page);
  await assertNoHorizontalOverflow(page, "desktop");
  await page.screenshot({ path: path.join(workDir, "strategy-smoke-desktop.png"), fullPage: true });
  invariant(runtimeErrors.length === 0, `desktop browser runtime errors:\n${runtimeErrors.join("\n")}`);
  await context.close();
}

async function runMobile(browser) {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const page = await context.newPage();
  const runtimeErrors = [];
  page.on("pageerror", (error) => runtimeErrors.push(`pageerror: ${error.message}`));
  page.on("console", (message) => { if (message.type() === "error") runtimeErrors.push(`console: ${message.text()}`); });

  await waitForDashboard(page);
  await assertRoleSeparation(page);
  await assertStrategyReport(page);
  invariant(await page.locator("#strategy-decision-boundary").isVisible(), "mobile decision boundary missing");
  invariant(await page.locator("#strategy-region-bridge").isVisible(), "mobile region bridge missing");
  await assertNoHorizontalOverflow(page, "mobile");
  await page.screenshot({ path: path.join(workDir, "strategy-smoke-mobile.png"), fullPage: true });
  invariant(runtimeErrors.length === 0, `mobile browser runtime errors:\n${runtimeErrors.join("\n")}`);
  await context.close();
}

(async () => {
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  try {
    await runDesktop(browser);
    await runMobile(browser);
    console.log("strategy preview browser smoke: PASS (role-separated decision support + reports, desktop/mobile)");
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
