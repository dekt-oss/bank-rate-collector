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
    invariant(numeric(await page.locator("#count").innerText()) > 0,
      "recovered default search still has zero rows");

    await page.locator("#filter-toggle").click();
    const oldRadio = page.locator('#asof-presets input[data-old="1"]');
    invariant(await oldRadio.count() === 1, "1년 이전 preset missing");
    const oldLabel = oldRadio.locator("xpath=..");
    const oldCount = numeric(await oldLabel.innerText());
    const staleCount = numeric(await page.locator("#stale-note b").innerText());
    invariant(oldCount > 0, "1년 이전 preset count is zero");
    invariant(oldCount === staleCount,
      `1년 이전 preset count ${oldCount} != stale count ${staleCount}`);

    await oldRadio.check();
    await page.waitForFunction(
      () => document.querySelector("#filter-mode-summary")?.textContent.includes("공시일 1년 이전"),
      null,
      { timeout: 10_000 },
    );
    let params = new URL(page.url()).searchParams;
    invariant(!params.get("dfrom"), "1년 이전 preset must clear dfrom");
    invariant(Boolean(params.get("dto")), "1년 이전 preset must set dto");

    const recent30 = page.locator('#asof-presets input[data-from]').nth(1);
    await recent30.check();
    await page.waitForFunction(
      () => document.querySelector("#filter-mode-summary")?.textContent.includes("공시일 최근 30일"),
      null,
      { timeout: 10_000 },
    );
    params = new URL(page.url()).searchParams;
    invariant(!params.get("dto"), "recent preset must clear stale dto");

    const metrics = {
      recoveredUrl: recoveredUrl.toString(),
      recoveredCount: numeric(await page.locator("#count").innerText()),
      oldPresetCount: oldCount,
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
