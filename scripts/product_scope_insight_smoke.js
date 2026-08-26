const { chromium } = require("@playwright/test");

const baseUrl = process.env.STRATEGY_PREVIEW_BASE_URL || "http://127.0.0.1:4173";

function invariant(condition, message) {
  if (!condition) throw new Error(message);
}

function latestCommonSpread(payload, term) {
  const scopes = payload.strategy?.product_history?.scopes || {};
  const points = (scope) => new Map(
    (scopes[scope]?.[String(term)]?.rate_trend?.points || [])
      .filter((point) => Number.isFinite(Number(point.mean_max_rate)))
      .map((point) => [String(point.date), point]),
  );
  const installment = points("savings_installment");
  const flexible = points("savings_flexible");
  const dates = [...installment.keys()].filter((date) => flexible.has(date)).sort();
  const date = dates.at(-1);
  if (!date) return null;
  const installmentRate = Number(installment.get(date).mean_max_rate);
  const flexibleRate = Number(flexible.get(date).mean_max_rate);
  if (!Number.isFinite(installmentRate) || !Number.isFinite(flexibleRate)) return null;
  const spread = installmentRate - flexibleRate;
  return {
    date,
    spread,
    leader: spread > 0.0001 ? "정기적금 우위" : spread < -0.0001 ? "자유적금 우위" : "유형간 동일",
  };
}

(async () => {
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await context.newPage();
  const runtimeErrors = [];
  page.on("pageerror", (error) => runtimeErrors.push(`pageerror: ${error.message}`));
  page.on("console", (message) => {
    if (message.type() === "error") runtimeErrors.push(`console: ${message.text()}`);
  });

  try {
    const response = await page.goto(
      `${baseUrl}/strategy.html?family=savings&savings=installment_savings,flexible_savings&term=12`,
      { waitUntil: "networkidle" },
    );
    invariant(response && response.ok(), "strategy savings insight URL failed to load");
    await page.waitForFunction(
      () => document.querySelector('[data-product-mode="savings"]')?.classList.contains("active")
        && document.getElementById("savings-subtype-trend")
        && !document.getElementById("savings-subtype-trend").hidden,
      null,
      { timeout: 30_000 },
    );

    const result = await page.evaluate(() => {
      const payload = JSON.parse(document.getElementById("rate-monitor-data").textContent);
      const policy = payload.strategy?.product_history?.savings_trend_display_policy?.terms?.["12"] || null;
      const insight = document.querySelector(".savings-subtype-insight");
      const badge = document.getElementById("savings-subtype-gap-badge");
      const kpi = document.getElementById("savings-subtype-spread-kpi");
      return {
        payload,
        policy,
        insightVisible: Boolean(insight && !insight.hidden),
        badgeVisible: Boolean(badge && !badge.hidden && insight && !insight.hidden),
        badgeText: badge?.textContent || "",
        kpiVisible: Boolean(kpi && !kpi.hidden && insight && !insight.hidden),
        spreadValue: document.getElementById("savings-subtype-spread-value")?.textContent || "",
        spreadDetail: document.getElementById("savings-subtype-spread-detail")?.textContent || "",
      };
    });

    invariant(result.policy, "12 month savings trend display policy is missing");
    if (result.policy.display_mode === "split") {
      const expected = latestCommonSpread(result.payload, 12);
      invariant(result.insightVisible, "split policy did not expose savings subtype insight row");
      invariant(result.badgeVisible, "split policy did not expose gap badge");
      invariant(result.badgeText.includes("유형별 차이 확대"), "gap badge copy is missing");
      invariant(expected, "split policy has no common subtype observation for spread KPI");
      invariant(result.kpiVisible, "split policy did not expose spread KPI");
      const expectedValue = `${expected.spread >= 0 ? "+" : ""}${expected.spread.toFixed(2)}%p`;
      invariant(
        result.spreadValue === expectedValue,
        `spread KPI mismatch: expected=${expectedValue} actual=${result.spreadValue}`,
      );
      invariant(
        result.spreadDetail.includes(expected.leader),
        `spread KPI leader mismatch: expected=${expected.leader} actual=${result.spreadDetail}`,
      );
    } else {
      invariant(!result.insightVisible, "combined policy should keep gap badge and spread KPI hidden");
    }

    invariant(runtimeErrors.length === 0, `savings insight runtime errors:\n${runtimeErrors.join("\n")}`);
    console.log(`product scope insight smoke: PASS mode=${result.policy.display_mode}`);
  } finally {
    await context.close();
    await browser.close();
  }
})().catch((error) => {
  console.error(error.stack || error.message || String(error));
  process.exit(1);
});
