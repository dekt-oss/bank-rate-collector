const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("@playwright/test");

const baselineUrl = process.env.STRATEGY_DENSITY_BASELINE_URL || "http://127.0.0.1:4174";
const candidateUrl = process.env.STRATEGY_DENSITY_CANDIDATE_URL || "http://127.0.0.1:4173";
const minReductionPct = Number(process.env.STRATEGY_DENSITY_MIN_REDUCTION_PCT || "20");
const workDir = path.resolve("work");
fs.mkdirSync(workDir, { recursive: true });

function invariant(condition, message) {
  if (!condition) throw new Error(message);
}

async function readyPage(browser, baseUrl, viewport) {
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  await page.route("**/favicon.ico", (route) => route.fulfill({ status: 204, body: "" }));
  const response = await page.goto(baseUrl + "/strategy.html", { waitUntil: "networkidle" });
  invariant(response && response.ok(), baseUrl + ": strategy HTTP failure");
  await page.waitForFunction(
    () => {
      const count = document.getElementById("count");
      const error = document.getElementById("error");
      return Boolean(count && error && error.hidden && count.textContent.trim() !== "—");
    },
    null,
    { timeout: 30_000 },
  );
  return { context, page };
}

async function measure(browser, label, viewport) {
  const baseline = await readyPage(browser, baselineUrl, viewport);
  const candidate = await readyPage(browser, candidateUrl, viewport);
  await candidate.page.waitForSelector('html[data-strategy-lean-ia="v3"]', { timeout: 30_000 });

  const evaluate = async (page) => page.evaluate(() => {
    const visible = (node) => {
      if (!node || node.hidden) return false;
      const style = getComputedStyle(node);
      const rect = node.getBoundingClientRect();
      return style.display !== "none" && style.visibility !== "hidden" && rect.height > 0 && rect.width > 0;
    };
    const selectors = [
      "#external-market-context",
      "#market-funding-competition",
      "#market-intelligence",
      "#market-flow",
      "#planning-zone",
      ".top5-card",
      "#institution-funding-position",
      "#preference-intelligence",
      "#special-offer-radar",
      "#scope-evidence",
      "#relative-pricing-r1",
      "#rate-funding-matrix",
      "#workspace-detail-disclosure",
      ".ux-decision-menu",
      ".ux-decision-readiness",
      ".decision-integrated-insight",
    ];
    const visibleNodes = (selector) => [...document.querySelectorAll(selector)].filter(visible);
    return {
      scrollHeight: Math.max(document.documentElement.scrollHeight, document.body.scrollHeight),
      clientHeight: document.documentElement.clientHeight,
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
      visibleBySelector: Object.fromEntries(selectors.map((selector) => [
        selector,
        visibleNodes(selector).length,
      ])),
      heightBySelector: Object.fromEntries(selectors.map((selector) => [
        selector,
        Number(visibleNodes(selector).reduce((sum, node) => sum + node.getBoundingClientRect().height, 0).toFixed(1)),
      ])),
      leanIa: document.documentElement.dataset.strategyLeanIa || "",
    };
  });

  const baselineMetrics = await evaluate(baseline.page);
  const candidateMetrics = await evaluate(candidate.page);
  const reductionPct = ((baselineMetrics.scrollHeight - candidateMetrics.scrollHeight) / baselineMetrics.scrollHeight) * 100;

  invariant(
    candidateMetrics.scrollWidth <= candidateMetrics.clientWidth + 1,
    label + ": candidate horizontal overflow",
  );
  await baseline.page.screenshot({
    path: path.join(workDir, "strategy-density-baseline-" + label + ".png"),
    fullPage: true,
  });
  await candidate.page.screenshot({
    path: path.join(workDir, "strategy-density-candidate-" + label + ".png"),
    fullPage: true,
  });

  await baseline.context.close();
  await candidate.context.close();

  return {
    viewport,
    baseline: baselineMetrics,
    candidate: candidateMetrics,
    reductionPct: Number(reductionPct.toFixed(2)),
  };
}

(async () => {
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  try {
    const metrics = {
      baselineUrl,
      candidateUrl,
      minReductionPct,
      desktop: await measure(browser, "desktop", { width: 1440, height: 1000 }),
      mobile: await measure(browser, "mobile", { width: 390, height: 844 }),
    };
    fs.writeFileSync(
      path.join(workDir, "strategy-lean-ia-density-metrics.json"),
      JSON.stringify(metrics, null, 2) + "\n",
      "utf8",
    );
    console.log(JSON.stringify(metrics, null, 2));
    for (const label of ["desktop", "mobile"]) {
      invariant(
        metrics[label].reductionPct >= minReductionPct,
        label + ": document height reduction " + metrics[label].reductionPct.toFixed(2) + "% < " + minReductionPct + "%",
      );
    }
    console.log("Strategy Lean IA density comparison: PASS");
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error.stack || error.message || String(error));
  process.exit(1);
});
