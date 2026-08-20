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
      return Boolean(count && error && error.hidden && count.textContent.trim() !== "—");
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
  invariant(
    text.includes("농·축협과 1:1 동일하지 않음"),
    "E0-6 광의 상호금융 해석 경계 문구가 렌더되지 않음",
  );
  invariant(
    await panel.locator(".external-context-card").count() === 3,
    "E0-6 금리 카드 3장이 렌더되지 않음",
  );
  invariant(
    await panel.locator(".external-flow").count() === 4,
    "E0-6 업권 잔액 카드 4장이 렌더되지 않음",
  );
  invariant(
    await panel.locator(".external-context-badge").count() === 1,
    "E0-6 상태 배지가 없음",
  );
}

async function assertStrategyRoleSplit(page, label) {
  const mapCard = page.locator(".workspace-detail.primary .mapcard");
  invariant(await mapCard.count() === 1, `${label}: Strategy 지역 지도 DOM이 없음`);
  invariant(await mapCard.isHidden(), `${label}: Strategy 지역 지도는 검색 조회로 이관되어 숨겨져야 함`);

  const handoff = page.locator(".ux-region-handoff");
  invariant(await handoff.count() === 1 && await handoff.isVisible(), `${label}: 검색 조회 지역 상세 handoff가 보이지 않음`);
  invariant(
    (await handoff.textContent()).includes("지역·지도 상세는 검색 조회로 통합했습니다."),
    `${label}: 지역 상세 역할 분리 안내가 없음`,
  );
  invariant(await handoff.locator("a").getAttribute("href") === "./", `${label}: 지역 상세 handoff 링크가 검색 조회를 가리키지 않음`);

  const readiness = page.locator(".ux-decision-readiness");
  invariant(await readiness.count() === 1 && await readiness.isVisible(), `${label}: 금리결정 준비도 카드가 보이지 않음`);
  invariant((await readiness.textContent()).includes("최종 최적금리 자동추천"), `${label}: calibration 전 의사결정 경계가 표시되지 않음`);
  invariant(await page.locator(".ux-report-button").isVisible(), `${label}: Strategy 보고서 출력 버튼이 보이지 않음`);
}

async function runDesktop(browser) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await context.newPage();
  const runtimeErrors = [];
  page.on("pageerror", (error) => runtimeErrors.push(`pageerror: ${error.message}`));
  page.on("console", (message) => {
    if (message.type() === "error") runtimeErrors.push(`console: ${message.text()}`);
  });

  await waitForDashboard(page);
  invariant(await page.locator('[data-market-mode="combined"]').evaluate((node) => node.classList.contains("active")), "기본 비교모드가 저축은행 + 상호금융이 아님");
  invariant((await page.locator("#scope-pill").textContent()).trim() === "저축은행 + 상호금융", "기본 scope label이 통합모드가 아님");
  invariant(cleanNumber(await page.locator("#count").textContent()) > 0, "통합 12M 비교군이 비어 있음");
  invariant(!(await page.locator('[data-sector="cu"]').isDisabled()), "신협 selector가 비활성화됨");
  invariant(!(await page.locator('[data-sector="kfcc"]').isDisabled()), "새마을금고 selector가 비활성화됨");
  invariant(!(await page.locator('[data-sector="nh_local"]').isDisabled()), "농·축협 selector가 비활성화됨");
  invariant(await page.locator('[data-sector="cu"]').isChecked(), "기본 통합모드에서 신협이 선택되지 않음");
  invariant(await page.locator('[data-sector="kfcc"]').isChecked(), "기본 통합모드에서 새마을금고가 선택되지 않음");
  invariant(await page.locator('[data-sector="nh_local"]').isChecked(), "기본 통합모드에서 농·축협이 선택되지 않음");
  const kfccMeta = await strategySectorMeta(page, "kfcc");
  const nhMeta = await strategySectorMeta(page, "nh_local");
  invariant(kfccMeta?.strategy_rate_capability === true && kfccMeta?.selectable === true, "새마을금고 수집기준 최고금리 capability가 열리지 않음");
  invariant(nhMeta?.strategy_rate_capability === true && nhMeta?.selectable === true, "농·축협 수집기준 최고금리 capability가 열리지 않음");
  invariant(await page.locator("#market-flow").isVisible(), "저축은행 포함 모드에서 이력 block이 숨겨짐");
  invariant(await page.locator("#sim-form").isVisible(), "저축은행 포함 모드에서 시뮬레이터가 숨겨짐");
  await assertMarketIntelligence(page);
  await assertExternalMarketContext(page);
  await assertStrategyRoleSplit(page, "desktop");

  await selectMode(page, "mutual_finance", "상호금융");
  invariant(cleanNumber(await page.locator("#count").textContent()) > 0, "상호금융 12M 비교군이 비어 있음");
  invariant(await page.locator("#market-flow").isHidden(), "상호금융 단독에서 저축은행 이력 block이 노출됨");
  invariant(await page.locator("#sim-form").isHidden(), "상호금융 단독에서 고려저축은행 시뮬레이터가 열림");
  invariant(await page.locator("#market-intelligence").isVisible(), "상호금융 모드에서 C2 시장동향 패널이 숨겨짐");

  await page.locator('[data-sector="cu"]').uncheck();
  await page.locator('[data-sector="nh_local"]').uncheck();
  await waitForPositiveCount(page);
  invariant(await page.locator("#top5 tr").count() > 0, "새마을금고 단독 TOP5가 비어 있음");

  await page.locator('[data-sector="kfcc"]').uncheck();
  await page.locator('[data-sector="nh_local"]').check();
  await waitForPositiveCount(page);
  invariant(await page.locator("#top5 tr").count() > 0, "농·축협 단독 TOP5가 비어 있음");

  await page.locator('[data-sector="cu"]').check();
  await page.locator('[data-sector="kfcc"]').check();
  await selectMode(page, "combined", "저축은행 + 상호금융");
  invariant(cleanNumber(await page.locator("#count").textContent()) > 0, "통합 12M 비교군이 비어 있음");
  invariant(await page.locator('[data-sector="cu"]').isChecked(), "통합 복귀 후 신협 선택이 복원되지 않음");
  invariant(await page.locator('[data-sector="kfcc"]').isChecked(), "통합 복귀 후 새마을금고 선택이 복원되지 않음");
  invariant(await page.locator('[data-sector="nh_local"]').isChecked(), "통합 복귀 후 농·축협 선택이 복원되지 않음");
  invariant(await page.locator("#top5 tr").count() > 0, "통합 TOP5가 비어 있음");
  await assertStrategyRoleSplit(page, "desktop combined");

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
  page.on("console", (message) => {
    if (message.type() === "error") runtimeErrors.push(`console: ${message.text()}`);
  });

  await waitForDashboard(page);
  const kfccMeta = await strategySectorMeta(page, "kfcc");
  const nhMeta = await strategySectorMeta(page, "nh_local");
  invariant(kfccMeta?.strategy_rate_capability === true && kfccMeta?.selectable === true, "모바일 새마을금고 capability가 열리지 않음");
  invariant(nhMeta?.strategy_rate_capability === true && nhMeta?.selectable === true, "모바일 농·축협 capability가 열리지 않음");
  invariant(!(await page.locator('[data-sector="kfcc"]').isDisabled()), "모바일 새마을금고 selector가 비활성화됨");
  invariant(!(await page.locator('[data-sector="nh_local"]').isDisabled()), "모바일 농·축협 selector가 비활성화됨");
  invariant(await page.locator('[data-market-mode="combined"]').evaluate((node) => node.classList.contains("active")), "모바일 기본 비교모드가 통합모드가 아님");
  invariant(await page.locator('[data-sector="cu"]').isChecked(), "모바일 기본 통합모드에서 신협이 선택되지 않음");
  invariant(await page.locator('[data-sector="kfcc"]').isChecked(), "모바일 기본 통합모드에서 새마을금고가 선택되지 않음");
  invariant(await page.locator('[data-sector="nh_local"]').isChecked(), "모바일 기본 통합모드에서 농·축협이 선택되지 않음");
  invariant(await page.locator("#market-intelligence").count() === 1, "모바일 C2 Market Intelligence panel이 없음");
  await assertStrategyRoleSplit(page, "mobile");
  await assertNoHorizontalOverflow(page, "mobile combined");
  await selectMode(page, "mutual_finance", "상호금융");
  invariant(cleanNumber(await page.locator("#count").textContent()) > 0, "모바일 상호금융 12M 비교군이 비어 있음");
  invariant(await page.locator("#sim-form").isHidden(), "모바일 상호금융 모드에서 시뮬레이터가 열림");
  invariant(await page.locator("#market-intelligence").isVisible(), "모바일 상호금융 모드에서 C2 패널이 숨겨짐");
  await assertStrategyRoleSplit(page, "mobile mutual-finance");
  await assertNoHorizontalOverflow(page, "mobile mutual-finance");
  await page.screenshot({ path: path.join(workDir, "strategy-smoke-mobile.png"), fullPage: true });
  invariant(runtimeErrors.length === 0, `mobile browser runtime errors:\n${runtimeErrors.join("\n")}`);
  await context.close();
}

(async () => {
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  try {
    await runDesktop(browser);
    await runMobile(browser);
    console.log("strategy preview browser smoke: PASS (desktop 1280px, mobile 390px)");
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error.stack || error.message || String(error));
  process.exit(1);
});