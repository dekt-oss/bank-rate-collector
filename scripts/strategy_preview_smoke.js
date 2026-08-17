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

async function runDesktop(browser) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await context.newPage();
  const runtimeErrors = [];
  page.on("pageerror", (error) => runtimeErrors.push(`pageerror: ${error.message}`));
  page.on("console", (message) => {
    if (message.type() === "error") runtimeErrors.push(`console: ${message.text()}`);
  });

  await waitForDashboard(page);
  invariant(cleanNumber(await page.locator("#count").textContent()) > 0, "저축은행 12M 비교군이 비어 있음");
  invariant(!(await page.locator('[data-sector="cu"]').isDisabled()), "신협 selector가 비활성화됨");
  invariant(await page.locator('[data-sector="kfcc"]').isDisabled(), "새마을금고 selector가 잘못 활성화됨");
  invariant(await page.locator('[data-sector="nh_local"]').isDisabled(), "농·축협 selector가 잘못 활성화됨");
  invariant(await page.locator("#market-flow").isVisible(), "저축은행 이력 block이 기본 모드에서 숨겨짐");
  invariant(await page.locator("#sim-form").isVisible(), "저축은행 시뮬레이터가 기본 모드에서 숨겨짐");
  invariant(await page.locator('[data-map-sector="savings_bank"]').count() === 1, "저축은행 지도 레이어가 없음");

  const busan = page.locator('#geo-map [data-region="부산"]');
  invariant(await busan.count() === 1, "저축은행 부산 지도 node가 없음");
  await busan.click();
  await page.waitForFunction(
    () => document.getElementById("map-title")?.textContent.trim() === "부산 구·군별 금리 지도",
    null,
    { timeout: 10_000 },
  );
  invariant(await page.locator("#map-back").isVisible(), "부산 drill-down에서 전국 보기 버튼이 보이지 않음");
  invariant(await page.locator("#busan-rate-list .busan-rate-item").count() > 0, "부산 canonical district 목록이 비어 있음");
  await page.locator("#map-back").click();

  await selectMode(page, "mutual_finance", "상호금융");
  invariant(cleanNumber(await page.locator("#count").textContent()) > 0, "신협 12M 비교군이 비어 있음");
  invariant(await page.locator("#market-flow").isHidden(), "상호금융 단독에서 저축은행 이력 block이 노출됨");
  invariant(await page.locator("#sim-form").isHidden(), "상호금융 단독에서 고려저축은행 시뮬레이터가 열림");
  const cuLayer = page.locator('[data-map-sector="cu"]');
  invariant(await cuLayer.count() === 1, "신협 source_query_region 지도 레이어가 없음");
  await cuLayer.click();
  await page.waitForFunction(
    () => document.getElementById("map-title")?.textContent.trim() === "신협 조회지역별 금리 분포",
    null,
    { timeout: 10_000 },
  );
  invariant(
    (await page.locator("#map-mode-label").textContent()).includes("원천 조회지역"),
    "신협 지도에 source_query_region 의미가 표시되지 않음",
  );
  invariant(await page.locator("#map-back").isHidden(), "신협 지도에서 부산 drill-down 복귀 버튼이 노출됨");

  await selectMode(page, "combined", "저축은행 + 상호금융");
  invariant(cleanNumber(await page.locator("#count").textContent()) > 0, "통합 12M 비교군이 비어 있음");
  invariant(await page.locator('[data-map-sector="savings_bank"]').count() === 1, "통합 모드 저축은행 지도 레이어가 없음");
  invariant(await page.locator('[data-map-sector="cu"]').count() === 1, "통합 모드 신협 지도 레이어가 없음");
  invariant(await page.locator("#top5 tr").count() > 0, "통합 TOP5가 비어 있음");

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
  await assertNoHorizontalOverflow(page, "mobile savings-bank");
  await selectMode(page, "mutual_finance", "상호금융");
  invariant(cleanNumber(await page.locator("#count").textContent()) > 0, "모바일 신협 12M 비교군이 비어 있음");
  invariant(await page.locator("#sim-form").isHidden(), "모바일 상호금융 모드에서 시뮬레이터가 열림");
  invariant(await page.locator('[data-map-sector="cu"]').count() === 1, "모바일 신협 지도 레이어가 없음");
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
