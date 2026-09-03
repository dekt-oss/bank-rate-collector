const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("@playwright/test");

const baseUrl = process.env.STRATEGY_PREVIEW_BASE_URL || "http://127.0.0.1:4173";
const workDir = path.resolve("work");
fs.mkdirSync(workDir, { recursive: true });

function invariant(condition, message) {
  if (!condition) throw new Error(message);
}

async function inspectRadar(page, label) {
  await page.goto(`${baseUrl}/strategy.html`, { waitUntil: "networkidle" });
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
  invariant(payload, `${label}: Radar payload missing`);
  invariant(payload.source_id === "fsb", `${label}: Radar source is not FSB`);
  invariant(payload.activation === "off_until_confirmed_evidence_is_reviewed_and_separately_approved", `${label}: Radar activation unexpectedly changed`);
  invariant(payload.policy?.unknown_is_special === false, `${label}: unknown promotion policy changed`);
  invariant(payload.policy?.ranking_population_changed === false, `${label}: ranking population changed`);
  invariant(Number(payload.counts?.unknown || 0) > 0, `${label}: live candidate produced no unknown evidence`);
  invariant(Number(payload.counts?.confirmed_special || 0) === 0, `${label}: synthetic confirmed special appeared`);
  invariant(Number(payload.counts?.confirmed_normal || 0) === 0, `${label}: synthetic confirmed normal appeared`);
  invariant(Array.isArray(payload.offers) && payload.offers.length === 0, `${label}: unknown evidence leaked into Radar offers`);

  const pageMetrics = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }));
  invariant(
    pageMetrics.scrollWidth <= pageMetrics.clientWidth + 1,
    `${label}: page horizontal overflow ${pageMetrics.scrollWidth} > ${pageMetrics.clientWidth}`,
  );

  await panel.screenshot({ path: path.join(workDir, `special-offer-radar-${label}.png`) });
  return {
    label,
    status: payload.status,
    counts: payload.counts,
    offers: payload.offers.length,
    pageMetrics,
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
