const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("@playwright/test");

const baseUrl = process.env.STRATEGY_PREVIEW_BASE_URL || "http://127.0.0.1:4173";
const workDir = path.resolve("work");
const requireLiveUnknown = process.env.RADAR_REQUIRE_LIVE_UNKNOWN !== "0";
const requireNoConfirmed = process.env.RADAR_REQUIRE_NO_CONFIRMED !== "0";
fs.mkdirSync(workDir, { recursive: true });

function invariant(condition, message) {
  if (!condition) throw new Error(message);
}

async function inspectRadar(page, label) {
  await page.goto(`${baseUrl}/strategy.html`, { waitUntil: "networkidle" });
  const diagnostics = await page.evaluate(() => {
    const dataNode = document.getElementById("rate-monitor-data");
    let parsed = null;
    let parseError = null;
    try {
      parsed = JSON.parse(dataNode?.textContent || "{}");
    } catch (error) {
      parseError = String(error);
    }
    return {
      readyState: document.readyState,
      dataNodePresent: Boolean(dataNode),
      dataBytes: dataNode?.textContent?.length || 0,
      marketFlowPresent: Boolean(document.getElementById("market-flow")),
      radarScriptPresent: Boolean(document.getElementById("special-offer-radar-script")),
      radarStylePresent: Boolean(document.getElementById("special-offer-radar-style")),
      radarPanelPresent: Boolean(document.getElementById("special-offer-radar")),
      strategyPresent: Boolean(parsed?.strategy),
      radarPayloadPresent: Boolean(parsed?.strategy?.special_offer_radar),
      radarCounts: parsed?.strategy?.special_offer_radar?.counts || null,
      parseError,
    };
  });
  fs.writeFileSync(
    path.join(workDir, `special-offer-radar-${label}-dom.json`),
    `${JSON.stringify(diagnostics, null, 2)}\n`,
    "utf8",
  );
  console.log(`${label} Radar DOM diagnostics: ${JSON.stringify(diagnostics)}`);

  invariant(diagnostics.dataNodePresent, `${label}: rate-monitor-data missing`);
  invariant(!diagnostics.parseError, `${label}: rate-monitor-data JSON parse failed: ${diagnostics.parseError}`);
  invariant(diagnostics.strategyPresent, `${label}: Strategy payload missing`);
  invariant(diagnostics.radarPayloadPresent, `${label}: Radar payload missing`);
  invariant(diagnostics.marketFlowPresent, `${label}: market-flow anchor missing`);
  invariant(diagnostics.radarScriptPresent, `${label}: Radar runtime script missing`);
  invariant(diagnostics.radarStylePresent, `${label}: Radar style missing`);

  const panel = page.locator("#special-offer-radar");
  invariant((await panel.count()) === 1, `${label}: special-offer Radar panel missing`);
  invariant(await panel.isVisible(), `${label}: special-offer Radar panel hidden`);

  const text = await panel.textContent();
  invariant(text.includes("시장 특판 Radar"), `${label}: Radar title missing`);
  invariant(text.includes("공개 OFF"), `${label}: release gate label missing`);
  invariant(text.includes("판정 미제공"), `${label}: unknown coverage label missing`);
  invariant(text.includes("특판으로 간주하지 않음"), `${label}: fail-closed copy missing`);
  invariant((await panel.locator(".special-radar-metric").count()) === 4, `${label}: metric count != 4`);
  invariant((await panel.locator("form").count()) === 0, `${label}: mutation form exposed`);
  invariant((await panel.locator('[type="submit"]').count()) === 0, `${label}: submit action exposed`);

  const payload = await page.evaluate(() => {
    const raw = document.getElementById("rate-monitor-data")?.textContent || "{}";
    return JSON.parse(raw)?.strategy?.special_offer_radar || null;
  });
  invariant(payload, `${label}: Radar payload missing after DOM install`);
  invariant(payload.source_id === "fsb", `${label}: Radar source is not FSB`);
  invariant(payload.activation === "off_until_confirmed_evidence_is_reviewed_and_separately_approved", `${label}: Radar activation unexpectedly changed`);
  invariant(payload.policy?.unknown_is_special === false, `${label}: unknown promotion policy changed`);
  invariant(payload.policy?.ranking_population_changed === false, `${label}: ranking population changed`);
  invariant(Array.isArray(payload.offers), `${label}: Radar offers is not an array`);
  if (requireLiveUnknown) {
    invariant(Number(payload.counts?.unknown || 0) > 0, `${label}: live candidate produced no unknown evidence`);
  }
  if (requireNoConfirmed) {
    invariant(Number(payload.counts?.confirmed_special || 0) === 0, `${label}: synthetic confirmed special appeared`);
    invariant(Number(payload.counts?.confirmed_normal || 0) === 0, `${label}: synthetic confirmed normal appeared`);
    invariant(payload.offers.length === 0, `${label}: unknown evidence leaked into Radar offers`);
  }

  const pageMetrics = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }));
  invariant(
    pageMetrics.scrollWidth <= pageMetrics.clientWidth + 1,
    `${label}: page horizontal overflow ${pageMetrics.scrollWidth} > ${pageMetrics.clientWidth}`,
  );

  const radarLayout = await page.evaluate(() => {
    const panel = document.getElementById("special-offer-radar");
    const metrics = panel?.querySelector(".special-radar-metrics");
    const cards = [...(metrics?.querySelectorAll(".special-radar-metric") || [])];
    const rect = (node) => {
      const box = node.getBoundingClientRect();
      return {
        left: box.left,
        right: box.right,
        top: box.top,
        bottom: box.bottom,
        width: box.width,
        height: box.height,
      };
    };
    return {
      viewportWidth: window.innerWidth,
      panel: panel ? rect(panel) : null,
      metrics: metrics ? {
        ...rect(metrics),
        clientWidth: metrics.clientWidth,
        scrollWidth: metrics.scrollWidth,
      } : null,
      cards: cards.map(rect),
    };
  });
  invariant(radarLayout.panel && radarLayout.metrics, `${label}: Radar layout metrics missing`);
  invariant(radarLayout.cards.length === 4, `${label}: Radar layout card count != 4`);
  invariant(
    radarLayout.metrics.scrollWidth <= radarLayout.metrics.clientWidth + 1,
    `${label}: Radar metrics require horizontal scrolling ${radarLayout.metrics.scrollWidth} > ${radarLayout.metrics.clientWidth}`,
  );
  for (const [index, card] of radarLayout.cards.entries()) {
    invariant(
      card.left >= radarLayout.panel.left - 1 && card.right <= radarLayout.panel.right + 1,
      `${label}: Radar metric ${index + 1} clipped (${card.left}-${card.right}) outside panel (${radarLayout.panel.left}-${radarLayout.panel.right})`,
    );
  }
  if (radarLayout.viewportWidth <= 760 && radarLayout.viewportWidth > 340) {
    const [first, second, third, fourth] = radarLayout.cards;
    invariant(Math.abs(first.top - second.top) <= 2, `${label}: first Radar row is not two columns`);
    invariant(third.top > first.top + 4, `${label}: second Radar row did not wrap below first row`);
    invariant(Math.abs(third.top - fourth.top) <= 2, `${label}: second Radar row is not two columns`);
    invariant(Math.abs(first.left - third.left) <= 2, `${label}: Radar grid columns are misaligned`);
  }

  await panel.screenshot({ path: path.join(workDir, `special-offer-radar-${label}.png`) });
  return {
    label,
    status: payload.status,
    counts: payload.counts,
    offers: payload.offers.length,
    pageMetrics,
    radarLayout,
  };
}

(async () => {
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  try {
    const desktopContext = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    const desktopPage = await desktopContext.newPage();
    const desktop = await inspectRadar(desktopPage, "desktop");
    await desktopContext.close();

    const mobileContext = await browser.newContext({ viewport: { width: 390, height: 844 } });
    const mobilePage = await mobileContext.newPage();
    const mobile = await inspectRadar(mobilePage, "mobile");
    await mobileContext.close();

    fs.writeFileSync(
      path.join(workDir, "special-offer-radar-runtime-metrics.json"),
      `${JSON.stringify({ desktop, mobile }, null, 2)}\n`,
      "utf8",
    );
    console.log(JSON.stringify({ desktop, mobile }));
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
