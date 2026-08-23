const { chromium } = require("@playwright/test");

const baseUrl = process.env.STRATEGY_PREVIEW_BASE_URL || "http://127.0.0.1:4173";

function invariant(condition, message) {
  if (!condition) throw new Error(message);
}

async function run() {
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.CHROME_BIN || "/usr/bin/google-chrome",
    args: ["--no-sandbox", "--disable-dev-shm-usage"],
  });
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    const errors = [];
    page.on("pageerror", (error) => errors.push(`pageerror: ${error.message}`));
    page.on("console", (message) => {
      if (message.type() === "error") errors.push(`console: ${message.text()}`);
    });
    await page.route("**/favicon.ico", (route) => route.fulfill({ status: 204, body: "" }));
    const response = await page.goto(`${baseUrl}/strategy.html`, { waitUntil: "networkidle" });
    invariant(response && response.ok(), "strategy.html load failed");

    const result = await page.evaluate(async () => {
      const engine = document.getElementById("public-structural-v2-forecast-provider-engine");
      const bridge = document.getElementById("public-structural-v2-forecast-provider-bridge");
      const cockpitScript = document.getElementById("public-structural-v2-cockpit-script");
      const api = globalThis.PublicStructuralV2ForecastProvider;
      const surface = globalThis.PublicStructuralV2Surface;
      if (!engine || !bridge || !cockpitScript || !api || !surface) {
        throw new Error("Stage H provider runtime markers/globals missing");
      }
      const request = {
        generated_at: "2026-08-23T09:00:00+09:00",
        candidate_rates: [3.5, 3.55],
        baseline_new_money: 100,
        maturity_amount: 200,
        current_rollover_rate_pct: 60,
        current_own_rate: 3.5,
        term_months: 12,
      };
      const payload = {
        version: "inflow-public-forecast-v1",
        generated_at: request.generated_at,
        status: "ready",
        amount_unit: "KRW_100M",
        rate_unit: "percent",
        scenarios: [
          {
            rate_pct: 3.5,
            predicted_new_money: 100,
            predicted_rollover: 120,
            predicted_total: 220,
            incremental_total: 0,
            surface_interest_delta: 0,
          },
          {
            rate_pct: 3.55,
            predicted_new_money: 101,
            predicted_rollover: 121,
            predicted_total: 222,
            incremental_total: 2,
            surface_interest_delta: 0.1,
          },
        ],
      };
      const ready = await api.resolveForecast(request, async () => payload);
      let leaked = false;
      try {
        await api.resolveForecast(request, async () => ({ ...payload, private_model: "x" }));
        leaked = true;
      } catch (error) {
        if (!String(error.message || error).includes("unknown_fields:private_model")) throw error;
      }
      const unavailable = await api.resolveForecast(request, async () => {
        throw new api.ProviderUnavailableError();
      });
      return {
        engineBeforeBridge:
          Boolean(engine.compareDocumentPosition(bridge) & Node.DOCUMENT_POSITION_FOLLOWING),
        bridgeBeforeCockpit:
          Boolean(bridge.compareDocumentPosition(cockpitScript) & Node.DOCUMENT_POSITION_FOLLOWING),
        hasCompatibilitySurface: typeof surface.buildSurface === "function",
        hasFrame: typeof surface.buildSurfaceFrame === "function",
        hasAttach: typeof surface.attachForecast === "function",
        readyStatus: ready.status,
        readyRates: ready.scenarios.map((row) => row.rate_pct),
        unavailableStatus: unavailable.status,
        unavailableCount: unavailable.scenarios.length,
        leaked,
        cockpitVisible: Boolean(document.getElementById("public-structural-v2-cockpit")),
      };
    });

    invariant(result.engineBeforeBridge, "provider engine must load before bridge");
    invariant(result.bridgeBeforeCockpit, "provider bridge must load before cockpit runtime");
    invariant(result.hasCompatibilitySurface, "compatibility buildSurface bridge missing");
    invariant(result.hasFrame && result.hasAttach, "provider-agnostic surface API missing");
    invariant(result.readyStatus === "ready", "async sanitized provider did not resolve ready");
    invariant(JSON.stringify(result.readyRates) === JSON.stringify([3.5, 3.55]), "rate axis drift");
    invariant(result.unavailableStatus === "unavailable", "unavailable provider status mismatch");
    invariant(result.unavailableCount === 0, "unavailable provider leaked scenarios");
    invariant(result.leaked === false, "private metadata leak was accepted");
    invariant(result.cockpitVisible, "Cockpit missing after provider bridge");
    invariant(errors.length === 0, `browser errors:\n${errors.join("\n")}`);
  } finally {
    await browser.close();
  }
  console.log("Public Structural v2 Stage H provider runtime smoke passed");
}

run().catch((error) => {
  console.error(error);
  process.exit(1);
});
