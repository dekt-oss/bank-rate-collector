const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("@playwright/test");

const baseUrl = process.env.STRATEGY_PREVIEW_BASE_URL || "http://127.0.0.1:4173";
const workDir = path.resolve("work");
fs.mkdirSync(workDir, { recursive: true });

function invariant(condition, message) {
  if (!condition) throw new Error(message);
}

async function openStrategy(page) {
  await page.route("**/favicon.ico", (route) => route.fulfill({ status: 204, body: "" }));
  const response = await page.goto(`${baseUrl}/strategy.html`, { waitUntil: "networkidle" });
  invariant(response && response.ok(), `strategy.html HTTP ${response ? response.status() : "no response"}`);
  await page.waitForSelector("#institution-funding-position", { state: "visible", timeout: 30_000 });
}

async function payload(page) {
  return page.evaluate(() => {
    const raw = document.getElementById("rate-monitor-data")?.textContent || "{}";
    return JSON.parse(raw)?.strategy?.institution_funding_positions || null;
  });
}

async function assertFundingPanel(page, label) {
  const data = await payload(page);
  invariant(data?.available === true, `${label}: institution funding payload unavailable`);
  invariant(data?.sectors?.savings_bank, `${label}: production savings-bank funding sector missing`);
  invariant(data?.sectors?.nh_local, `${label}: production NH funding sector missing`);
  invariant(data?.contract?.direct_peer?.nh_local_requested_count === 16, `${label}: calibrated NH Direct Peer N is not 16`);
  invariant(Array.isArray(data?.contract?.direct_peer?.enabled_sectors) && data.contract.direct_peer.enabled_sectors.includes("nh_local"), `${label}: NH Direct Peer is not explicitly enabled`);
  invariant(data?.sectors?.savings_bank?.direct_peer?.enabled === false, `${label}: savings-bank Direct Peer must stay disabled before sector-specific calibration`);

  const tabs = page.locator("#funding-position-tabs button");
  invariant(await tabs.count() >= 2, `${label}: funding sector tabs missing`);
  const activeText = (await page.locator("#funding-position-tabs button.active").textContent()).trim();
  invariant(activeText === "저축은행", `${label}: default funding tab is not 저축은행: ${activeText}`);

  const status = (await page.locator("#funding-position-status").textContent()).trim();
  invariant(status.includes("기준") && status.includes("공시") && status.includes("개월 경과"), `${label}: freshness metadata missing`);
  invariant(status.includes("동월 관측") || status.includes("부분 관측"), `${label}: measured coverage wording missing`);

  const note = (await page.locator("#funding-position-note").textContent()).trim();
  invariant(note.includes("ECOS 업권 수신잔액과 합계 일치를 전제하지 않고"), `${label}: ECOS contract boundary missing`);
  invariant(note.includes("연관성 지표"), `${label}: association-not-causation boundary missing`);

  const countText = (await page.locator("#funding-position-count").textContent()).trim();
  invariant(countText.includes("총"), `${label}: table truncation disclosure missing`);
  invariant(await page.locator("#funding-position-table-body tbody tr").count() > 0, `${label}: funding table empty`);

  await page.locator('#funding-position-sort button[data-sort="growth6"]').click();
  invariant(await page.locator('#funding-position-sort button[data-sort="growth6"]').evaluate((node) => node.classList.contains("active")), `${label}: 6M sort did not activate`);
  await page.locator('#funding-position-sort button[data-sort="sectorPeer"]').click();
  invariant(await page.locator('#funding-position-sort button[data-sort="sectorPeer"]').evaluate((node) => node.classList.contains("active")), `${label}: sector-median sort did not activate`);
  invariant(await page.locator('#funding-position-sort button[data-sort="directPeer"]').count() === 0, `${label}: disabled sector exposed Direct Peer sort`);

  const nhTab = page.locator('#funding-position-tabs button[data-sector="nh_local"]');
  invariant(await nhTab.count() === 1, `${label}: NH funding tab missing`);
  await nhTab.click();

  const nh = (await payload(page)).sectors.nh_local;
  invariant(nh.direct_peer?.enabled === true, `${label}: NH Direct Peer payload disabled`);
  invariant(nh.direct_peer?.requested_count === 16, `${label}: NH Direct Peer payload N mismatch`);
  invariant(Array.isArray(nh.rows) && nh.rows.length > 0, `${label}: NH payload rows empty`);
  invariant(nh.rows.every((row) => row.direct_peer_count === 16), `${label}: NH row has Direct Peer shortfall or wrong count`);
  invariant(nh.rows.every((row) => ["sigungu", "sido", "nationwide"].includes(row.direct_peer_scope)), `${label}: NH row has invalid Direct Peer scope`);

  const nhStatus = (await page.locator("#funding-position-status").textContent()).trim();
  invariant(nhStatus.includes("반기 공시"), `${label}: NH cadence label missing`);
  invariant(nhStatus.includes("Direct Peer 16"), `${label}: NH Direct Peer status badge missing`);
  invariant(await page.locator("#funding-position-table-body tbody tr").count() > 0, `${label}: NH funding table empty after tab switch`);
  invariant(await page.locator('th:has-text("Direct Peer 16 대비")').count() === 1, `${label}: NH Direct Peer column missing`);

  const directSort = page.locator('#funding-position-sort button[data-sort="directPeer"]');
  invariant(await directSort.count() === 1, `${label}: NH Direct Peer sort missing`);
  await directSort.click();
  invariant(await directSort.evaluate((node) => node.classList.contains("active")), `${label}: NH Direct Peer sort did not activate`);

  const nhNote = (await page.locator("#funding-position-note").textContent()).trim();
  invariant(nhNote.includes("시군구→시도→전국"), `${label}: Direct Peer fallback contract missing`);
  invariant(nhNote.includes("수신규모가 가까운 16개"), `${label}: Direct Peer size-neighbor contract missing`);
}

async function runViewport(browser, viewport, name) {
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  const runtimeErrors = [];
  page.on("pageerror", (error) => runtimeErrors.push(`pageerror: ${error.message}`));
  page.on("console", (message) => {
    if (message.type() === "error") runtimeErrors.push(`console: ${message.text()}`);
  });
  await openStrategy(page);
  await assertFundingPanel(page, name);
  await page.screenshot({ path: path.join(workDir, `institution-funding-${name}.png`), fullPage: true });
  invariant(runtimeErrors.length === 0, `${name} browser runtime errors:\n${runtimeErrors.join("\n")}`);
  await context.close();
}

(async () => {
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.CHROME_BIN || "/usr/bin/google-chrome",
    args: ["--no-sandbox", "--disable-dev-shm-usage"],
  });
  try {
    await runViewport(browser, { width: 1280, height: 900 }, "desktop");
    await runViewport(browser, { width: 390, height: 844 }, "mobile");
  } finally {
    await browser.close();
  }
})();
