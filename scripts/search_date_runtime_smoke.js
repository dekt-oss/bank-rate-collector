const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("@playwright/test");

const baseUrl = process.env.SEARCH_DATE_SMOKE_BASE_URL || "http://127.0.0.1:4173";
const workDir = path.resolve("work");
fs.mkdirSync(workDir, { recursive: true });

function invariant(condition, message) {
  if (!condition) throw new Error(message);
}

function numeric(text) {
  const digits = String(text || "").replace(/[^0-9]/g, "");
  return digits ? Number(digits) : 0;
}

async function waitForRenderedRows(page) {
  await page.waitForFunction(() => {
    const count = document.querySelector("#count");
    return count && /[0-9]/.test(count.textContent || "") && !count.textContent.includes("—");
  }, null, { timeout: 30_000 });
}

(async () => {
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    await page.route("**/favicon.ico", (route) => route.fulfill({ status: 204, body: "" }));

    const response = await page.goto(`${baseUrl}/?dfrom=2099-01-01`, { waitUntil: "networkidle" });
    invariant(response && response.ok(), `search page HTTP ${response ? response.status() : "no response"}`);
    await waitForRenderedRows(page);

    await page.waitForFunction(
      () => document.querySelector("#filter-mode-summary")?.textContent.includes("공시일 최근 30일"),
      null,
      { timeout: 10_000 },
    );
    const recoveredUrl = new URL(page.url());
    invariant(recoveredUrl.searchParams.get("dfrom") !== "2099-01-01",
      "future dfrom remained pinned after recovery");
    const recoveredCount = numeric(await page.locator("#count").innerText());
    invariant(recoveredCount > 0, "recovered default search still has zero rows");

    // 반대 방향도 잠근다. 정상적인 과거 공유 URL은 복구 대상이 아니다.
    const historicalFrom = "2020-01-01";
    const historicalResponse = await page.goto(
      `${baseUrl}/?dfrom=${historicalFrom}`,
      { waitUntil: "networkidle" },
    );
    invariant(historicalResponse && historicalResponse.ok(),
      `historical URL HTTP ${historicalResponse ? historicalResponse.status() : "no response"}`);
    await waitForRenderedRows(page);
    const historicalUrl = new URL(page.url());
    invariant(historicalUrl.searchParams.get("dfrom") === historicalFrom,
      `valid historical dfrom was rewritten: ${historicalUrl}`);
    invariant(
      (await page.locator("#filter-mode-summary").innerText()).includes("공시일 직접 지정"),
      "valid historical URL did not remain an explicit date filter",
    );

    await page.locator("#filter-toggle").click();
    const allRadio = page.locator('#asof-presets input[data-all-period="1"]');
    invariant(await allRadio.count() === 1, "전체 기간(1년 이전 포함) preset missing");
    const allLabel = allRadio.locator("xpath=..");
    const allCount = numeric(await allLabel.locator(".n").innerText());
    const staleCount = numeric(await page.locator("#stale-note b").innerText());
    const oneYearRadio = page.locator('#asof-presets input[data-from]').last();
    const oneYearCount = numeric(await oneYearRadio.locator("xpath=..").locator(".n").innerText());
    invariant(allCount >= oneYearCount,
      `all-period count ${allCount} < recent-one-year count ${oneYearCount}`);
    if (staleCount > 0) {
      invariant(allCount > oneYearCount,
        "stale rows exist but all-period search does not expand beyond recent one year");
    }

    await allRadio.check();
    await page.waitForFunction(
      () => document.querySelector("#filter-mode-summary")?.textContent.includes("공시일 전체"),
      null,
      { timeout: 10_000 },
    );
    let params = new URL(page.url()).searchParams;
    invariant(!params.get("dfrom"), "all-period preset must clear dfrom");
    invariant(!params.get("dto"), "all-period preset must clear dto");

    const recent30 = page.locator('#asof-presets input[data-from]').nth(1);
    await recent30.check();
    await page.waitForFunction(
      () => document.querySelector("#filter-mode-summary")?.textContent.includes("공시일 최근 30일"),
      null,
      { timeout: 10_000 },
    );
    params = new URL(page.url()).searchParams;
    invariant(!params.get("dto"), "recent preset must keep dto cleared");

    const metrics = {
      recoveredUrl: recoveredUrl.toString(),
      recoveredCount,
      historicalUrl: historicalUrl.toString(),
      allPeriodCount: allCount,
      recentOneYearCount: oneYearCount,
      staleCount,
      finalUrl: page.url(),
    };
    fs.writeFileSync(
      path.join(workDir, "search-date-runtime-metrics.json"),
      JSON.stringify(metrics, null, 2),
    );
    await page.screenshot({ path: path.join(workDir, "search-date-runtime.png"), fullPage: true });
    console.log(JSON.stringify(metrics, null, 2));
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
