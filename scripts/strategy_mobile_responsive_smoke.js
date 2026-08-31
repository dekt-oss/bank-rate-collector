const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("@playwright/test");

const baseUrl = process.env.STRATEGY_PREVIEW_BASE_URL || "http://127.0.0.1:4173";
const workDir = path.resolve("work");
fs.mkdirSync(workDir, { recursive: true });

function invariant(condition, message) {
  if (!condition) throw new Error(message);
}

async function inspect(browser, label, viewport) {
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  const runtimeErrors = [];
  page.on("pageerror", (error) => runtimeErrors.push(`pageerror: ${error.message}`));
  page.on("console", (message) => {
    if (message.type() === "error") runtimeErrors.push(`console: ${message.text()}`);
  });
  await page.route("**/favicon.ico", (route) => route.fulfill({ status: 204, body: "" }));

  const response = await page.goto(`${baseUrl}/strategy.html`, { waitUntil: "networkidle" });
  invariant(response && response.ok(), `${label}: strategy HTTP ${response?.status()}`);
  await page.waitForSelector('html[data-strategy-mobile-responsive="v1"]', { timeout: 30_000 });

  const predictionToggle = page.locator("#prediction-toggle");
  const predictionPanel = page.locator("#prediction-panel");
  if (await predictionToggle.isVisible()) {
    if (await predictionPanel.isHidden()) await predictionToggle.click();
    await page.locator("#baseline-new").waitFor({ state: "visible", timeout: 10_000 });
  }

  const result = await page.evaluate(() => {
    const dims = (selector) => {
      const node = document.querySelector(selector);
      if (!node) return null;
      const rect = node.getBoundingClientRect();
      return {
        clientWidth: node.clientWidth,
        scrollWidth: node.scrollWidth,
        width: rect.width,
        height: rect.height,
      };
    };
    const visibleGraphics = [...document.querySelectorAll("svg,canvas")]
      .filter((node) => {
        const style = getComputedStyle(node);
        const rect = node.getBoundingClientRect();
        return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
      })
      .map((node) => {
        const rect = node.getBoundingClientRect();
        return { id: node.id || node.className?.baseVal || node.className || node.tagName, width: rect.width, height: rect.height };
      });
    const zeroGraphics = visibleGraphics.filter((item) => item.width <= 0 || item.height <= 0);
    const trendPaths = document.querySelectorAll("#trend-series path").length;
    const trendNoData = document.getElementById("trend-series")?.textContent?.includes("이력 데이터가 없습니다") || false;
    const modelEvidence = document.querySelector("details.decision-model-evidence");
    return {
      page: {
        clientWidth: document.documentElement.clientWidth,
        scrollWidth: document.documentElement.scrollWidth,
      },
      simulator: dims("#planning-zone .sim"),
      simform: dims("#planning-zone .simform"),
      chartWrap: dims("#market-flow .chartwrap"),
      trendChart: dims("#trend-chart"),
      preference: dims("#preference-intelligence .pref-intel-main"),
      funding: dims("#institution-funding-position .funding-position-table-wrap"),
      visibleGraphics,
      zeroGraphics,
      trendPaths,
      trendNoData,
      modelEvidenceExists: Boolean(modelEvidence),
      modelEvidenceOpen: Boolean(modelEvidence?.open),
    };
  });

  invariant(runtimeErrors.length === 0, `${label}: runtime errors ${runtimeErrors.join(" | ")}`);
  invariant(result.visibleGraphics.length > 0, `${label}: visible graphic 없음`);
  invariant(result.zeroGraphics.length === 0, `${label}: 0-size graphic ${JSON.stringify(result.zeroGraphics)}`);
  invariant(result.trendPaths > 0 || result.trendNoData, `${label}: trend graph가 path/명시적 no-data 어느 쪽도 아님`);
  invariant(result.modelEvidenceExists && !result.modelEvidenceOpen, `${label}: 모델 근거 기본 접힘 계약 위반`);

  if (viewport.width <= 760) {
    invariant(result.page.scrollWidth <= result.page.clientWidth + 1, `${label}: page overflow ${JSON.stringify(result.page)}`);
    for (const [name, box] of Object.entries({
      simulator: result.simulator,
      simform: result.simform,
      chartWrap: result.chartWrap,
      preference: result.preference,
      funding: result.funding,
    })) {
      if (!box) continue;
      invariant(box.scrollWidth <= box.clientWidth + 1, `${label}: ${name} overflow ${JSON.stringify(box)}`);
    }
    if (result.chartWrap && result.trendChart) {
      invariant(result.trendChart.width <= result.chartWrap.width + 1, `${label}: trend SVG가 chartwrap보다 큼 ${JSON.stringify({ chartWrap: result.chartWrap, trendChart: result.trendChart })}`);
    }
  }

  await page.screenshot({ path: path.join(workDir, `strategy-mobile-responsive-${label}.png`), fullPage: true });
  console.log(label, JSON.stringify(result));
  await context.close();
}

(async () => {
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  try {
    await inspect(browser, "desktop-1440", { width: 1440, height: 1000 });
    await inspect(browser, "mobile-430", { width: 430, height: 932 });
    await inspect(browser, "mobile-390", { width: 390, height: 844 });
    console.log("strategy mobile responsive smoke: PASS (1440/430/390)");
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error.stack || error.message || String(error));
  process.exit(1);
});
