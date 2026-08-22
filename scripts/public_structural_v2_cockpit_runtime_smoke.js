const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("@playwright/test");

const baseUrl = process.env.STRATEGY_PREVIEW_BASE_URL || "http://127.0.0.1:4173";
const workDir = path.resolve("work");
fs.mkdirSync(workDir, { recursive: true });

function invariant(condition, message) {
  if (!condition) throw new Error(message);
}

async function waitForCockpit(page) {
  await page.route("**/favicon.ico", (route) => route.fulfill({ status: 204, body: "" }));
  const response = await page.goto(`${baseUrl}/strategy.html`, { waitUntil: "networkidle" });
  invariant(response && response.ok(), `strategy.html HTTP ${response ? response.status() : "no response"}`);
  await page.waitForFunction(
    () => {
      const cockpit = document.getElementById("public-structural-v2-cockpit");
      return Boolean(cockpit && cockpit.textContent.includes("실제 시장 위치"));
    },
    null,
    { timeout: 30_000 },
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

async function assertUniqueLadderRates(cockpit, label) {
  const duplicates = await cockpit.locator(".psv2-rung").evaluateAll((nodes) => {
    const rates = nodes.map((node) => node.querySelector("strong")?.textContent?.trim()).filter(Boolean);
    return rates.filter((rate, index) => rates.indexOf(rate) !== index);
  });
  invariant(duplicates.length === 0, `${label}: Ladder 동일금리 marker 중복 ${JSON.stringify(duplicates)}`);
}

async function assertCandidateTableVisualSpace(cockpit, viewport, label) {
  const metrics = await cockpit.locator(".psv2-table-wrap").evaluate((wrapper) => {
    const table = wrapper.querySelector(".psv2-table");
    const overflowingCells = [...wrapper.querySelectorAll("th,td")]
      .filter((cell) => cell.scrollWidth > cell.clientWidth + 1)
      .map((cell) => cell.textContent.trim());
    return {
      wrapperClientWidth: wrapper.clientWidth,
      wrapperScrollWidth: wrapper.scrollWidth,
      tableWidth: table?.getBoundingClientRect().width || 0,
      overflowingCells,
    };
  });
  invariant(metrics.overflowingCells.length === 0, `${label}: 후보금리 cell text overflow ${JSON.stringify(metrics.overflowingCells)}`);
  if (viewport.width <= 520) {
    invariant(metrics.tableWidth >= 1239, `${label}: mobile 후보금리표 최소폭 부족 ${metrics.tableWidth}`);
    invariant(
      metrics.wrapperScrollWidth > metrics.wrapperClientWidth,
      `${label}: mobile 후보금리표가 wrapper 내부 가로스크롤을 확보하지 못함`,
    );
  }
}

async function populateStructuralInputs(page) {
  await page.locator("#baseline-new").fill("100");
  await page.locator("#maturity-amount").fill("200");
  await page.locator("#rollover-rate").fill("60");
  await page.waitForFunction(
    () => {
      const panel = document.getElementById("prediction-panel");
      const cockpit = document.getElementById("public-structural-v2-cockpit");
      return Boolean(
        panel?.classList.contains("psv2-active")
        && cockpit?.textContent.includes("Response Surface")
        && cockpit?.textContent.includes("후보금리 비교"),
      );
    },
    null,
    { timeout: 10_000 },
  );
  await page.waitForFunction(
    () => {
      const rates = [...document.querySelectorAll("#public-structural-v2-cockpit .psv2-rung strong")]
        .map((node) => node.textContent.trim());
      return new Set(rates).size === rates.length;
    },
    null,
    { timeout: 5_000 },
  );
}

async function runViewport(browser, viewport, label) {
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  const runtimeErrors = [];
  page.on("pageerror", (error) => runtimeErrors.push(`pageerror: ${error.message}`));
  page.on("console", (message) => {
    if (message.type() === "error") runtimeErrors.push(`console: ${message.text()}`);
  });

  await waitForCockpit(page);
  const cockpit = page.locator("#public-structural-v2-cockpit");
  invariant(await cockpit.isVisible(), `${label}: v2 Cockpit이 보이지 않음`);
  const marketOnlyText = await cockpit.textContent();
  invariant(marketOnlyText.includes("실제 시장 위치"), `${label}: 실제 시장 위치 카드가 없음`);
  invariant(marketOnlyText.includes("입력 3개 필요"), `${label}: 입력 전 scenario 경계가 없음`);
  invariant(marketOnlyText.includes("Market Position Ladder"), `${label}: Ladder가 없음`);
  invariant(!marketOnlyText.includes("추천금리"), `${label}: 금지된 추천금리 표현이 있음`);
  invariant(!marketOnlyText.includes("최적금리"), `${label}: 금지된 최적금리 표현이 있음`);
  await assertUniqueLadderRates(cockpit, `${label} market-only`);

  await populateStructuralInputs(page);
  const fullText = await cockpit.textContent();
  invariant(fullText.includes("시장 사실 ≠ 수신금액의 직접 원인"), `${label}: 인과 경계 문구가 없음`);
  invariant(fullText.includes("stress range"), `${label}: stress range가 없음`);
  invariant(fullText.includes("직전 5bp 표면비용"), `${label}: 5bp 비용 비교가 없음`);
  invariant(await cockpit.locator(".psv2-chart").count() === 1, `${label}: Response Surface SVG가 없음`);
  invariant(await cockpit.locator(".psv2-table tbody tr").count() >= 2, `${label}: 후보금리 표가 비어 있음`);
  invariant(await page.locator(".prediction-results").isHidden(), `${label}: v1 결과 카드가 primary로 남아 있음`);
  invariant(await page.locator(".rate-response-wrap").isHidden(), `${label}: 구형 scenario table이 primary로 남아 있음`);
  await assertUniqueLadderRates(cockpit, `${label} full`);
  await assertCandidateTableVisualSpace(cockpit, viewport, label);

  await assertNoHorizontalOverflow(page, label);
  await cockpit.screenshot({ path: path.join(workDir, `public-structural-v2-cockpit-${label}.png`) });
  invariant(runtimeErrors.length === 0, `${label} browser runtime errors:\n${runtimeErrors.join("\n")}`);
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
  console.log("Public Structural v2 Cockpit runtime smoke passed");
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
