const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("@playwright/test");

const baseUrl = process.env.STRATEGY_PREVIEW_BASE_URL || "http://127.0.0.1:4173";
const workDir = path.resolve("work");
fs.mkdirSync(workDir, { recursive: true });

function invariant(condition, message) {
  if (!condition) throw new Error(message);
}

async function snapshot(page) {
  return page.evaluate(() => {
    const panel = document.getElementById("preference-intelligence");
    const payload = JSON.parse(document.getElementById("rate-monitor-data")?.textContent || "{}");
    const intelligence = payload.strategy?.preference_intelligence || {};
    const bodyStyle = getComputedStyle(document.body);
    const head = document.querySelector(".head h2");
    const headStyle = head ? getComputedStyle(head) : null;
    const tableCell = document.querySelector(".tablewrap td");
    const tableCellStyle = tableCell ? getComputedStyle(tableCell) : null;
    const cards = [...(panel?.querySelectorAll(".ux-pref-sector") || [])];
    const text = panel?.textContent || "";
    const mutual = cards.find((node) => node.textContent.includes("상호금융 통합"));
    const savings = cards.find((node) => node.textContent.includes("저축은행"));
    const sourceChips = mutual
      ? [...mutual.querySelectorAll(".pref-v2-source span")].map((node) => node.textContent.trim())
      : [];
    const scopeTags = [...(panel?.querySelectorAll(".ux-pref-scope-tag") || [])].map(
      (node) => node.textContent.trim(),
    );
    const firstSavingsRow = savings?.querySelector(".pref-intel-table tbody tr");
    const firstSavingsCells = firstSavingsRow
      ? [...firstSavingsRow.querySelectorAll("td")].map((node) => node.textContent.trim())
      : [];
    const savingsScope = intelligence.scopes?.find(
      (item) => item.sector === "savings_bank" && Number(item.term_months) === 12,
    ) || null;
    const firstSavingsCategory = savingsScope?.categories?.[0] || null;
    return {
      viewport: { width: window.innerWidth, height: window.innerHeight },
      document: {
        clientWidth: document.documentElement.clientWidth,
        scrollWidth: document.documentElement.scrollWidth,
      },
      bodyFontSize: parseFloat(bodyStyle.fontSize),
      headingFontSize: headStyle ? parseFloat(headStyle.fontSize) : null,
      tableFontSize: tableCellStyle ? parseFloat(tableCellStyle.fontSize) : null,
      panelExists: Boolean(panel),
      preferenceV2: panel?.dataset.preferenceV2 || "",
      panelText: text,
      cardCount: cards.length,
      savingsVisible: Boolean(savings),
      mutualVisible: Boolean(mutual),
      sourceChips,
      scopeTags,
      firstSavingsCells,
      firstSavingsCategory,
      payload: {
        version: intelligence.version,
        categoryDenominator: intelligence.category_denominator,
        categoryCompositionDenominator: intelligence.category_composition_denominator,
        mutualPolicy: intelligence.mutual_finance_scope_policy,
        mutualScopeCount: Array.isArray(intelligence.mutual_finance_scopes)
          ? intelligence.mutual_finance_scopes.length
          : 0,
        defaultMutual: intelligence.mutual_finance_scopes?.find(
          (item) => item.scope_key === "cu+kfcc+nh_local" && Number(item.term_months) === 12,
        ) || null,
      },
    };
  });
}

function pct0(value) {
  return value === null || value === undefined || !Number.isFinite(Number(value))
    ? "—"
    : `${(Number(value) * 100).toFixed(0)}%`;
}

function lift1(value) {
  return value === null || value === undefined || !Number.isFinite(Number(value))
    ? "—"
    : `${Number(value) > 0 ? "+" : ""}${Number(value).toFixed(1)}%p`;
}

async function assertSingleMutualFallback(page, name) {
  for (const sector of ["kfcc", "nh_local"]) {
    const input = page.locator(`[data-sector="${sector}"]`);
    if (await input.isChecked()) await input.uncheck();
  }
  const cu = page.locator('[data-sector="cu"]');
  if (!(await cu.isChecked())) await cu.check();
  await page.waitForFunction(() => {
    const panel = document.getElementById("preference-intelligence");
    return panel?.textContent.includes("상호금융 통합")
      && panel?.textContent.includes("신협")
      && !panel?.textContent.includes("신협+새마을금고+농·축협");
  });

  const result = await page.evaluate(() => {
    const payload = JSON.parse(document.getElementById("rate-monitor-data")?.textContent || "{}");
    const intelligence = payload.strategy?.preference_intelligence || {};
    const panel = document.getElementById("preference-intelligence");
    const mutual = [...(panel?.querySelectorAll(".ux-pref-sector") || [])].find(
      (node) => node.textContent.includes("상호금융 통합"),
    );
    const cells = mutual?.querySelector(".pref-intel-table tbody tr")
      ? [...mutual.querySelector(".pref-intel-table tbody tr").querySelectorAll("td")].map(
          (node) => node.textContent.trim(),
        )
      : [];
    const cuScope = intelligence.scopes?.find(
      (item) => item.sector === "cu" && Number(item.term_months) === 12,
    ) || null;
    return {
      cells,
      firstCategory: cuScope?.categories?.[0] || null,
      sourceChipCount: mutual?.querySelectorAll(".pref-v2-source span").length || 0,
    };
  });
  invariant(result.firstCategory, `${name}: single-sector cu scope category missing`);
  invariant(result.cells.length >= 4, `${name}: single-sector mutual row missing`);
  invariant(
    result.cells[1] === pct0(result.firstCategory.market_product_share),
    `${name}: single-sector market penetration mismatch ${result.cells[1]}`,
  );
  invariant(
    result.cells[2] === pct0(result.firstCategory.top_tier_product_share),
    `${name}: single-sector top penetration mismatch ${result.cells[2]}`,
  );
  invariant(
    result.cells[3] === lift1(result.firstCategory.top_tier_lift_pp),
    `${name}: single-sector lift mismatch ${result.cells[3]}`,
  );
  invariant(result.sourceChipCount === 1, `${name}: single-sector source chips=${result.sourceChipCount}`);
}

async function runViewport(browser, name, viewport) {
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  await page.route("**/favicon.ico", (route) => route.fulfill({ status: 204, body: "" }));
  const response = await page.goto(`${baseUrl}/strategy.html`, { waitUntil: "networkidle" });
  invariant(response && response.ok(), `${name}: strategy HTTP ${response ? response.status() : "no response"}`);
  await page.waitForSelector('#preference-intelligence[data-preference-v2="1"]', { timeout: 30_000 });
  await page.waitForFunction(
    () => document.querySelector("#preference-intelligence")?.textContent.includes("상호금융 통합"),
    null,
    { timeout: 10_000 },
  );

  const result = await snapshot(page);
  invariant(errors.length === 0, `${name}: runtime errors=${JSON.stringify(errors)}`);
  invariant(
    result.document.scrollWidth <= result.document.clientWidth + 1,
    `${name}: horizontal overflow ${result.document.scrollWidth} > ${result.document.clientWidth}`,
  );
  invariant(result.panelExists && result.preferenceV2 === "1", `${name}: preference v2 panel missing`);
  invariant(result.payload.version === "preference-intelligence-v2", `${name}: payload version=${result.payload.version}`);
  invariant(
    result.payload.categoryDenominator === "preference_bearing_products_present_only",
    `${name}: denominator=${result.payload.categoryDenominator}`,
  );
  invariant(
    result.payload.categoryCompositionDenominator === "normalized_preference_category_occurrences_present_only",
    `${name}: composition denominator=${result.payload.categoryCompositionDenominator}`,
  );
  invariant(result.payload.mutualPolicy === "pooled_selected_mutual_sectors", `${name}: mutual policy=${result.payload.mutualPolicy}`);
  invariant(result.payload.mutualScopeCount === 16, `${name}: mutual scope count=${result.payload.mutualScopeCount}`);
  invariant(Boolean(result.payload.defaultMutual), `${name}: default pooled mutual 12m scope missing`);
  invariant(result.cardCount === 2, `${name}: default combined preference card count=${result.cardCount}`);
  invariant(result.savingsVisible && result.mutualVisible, `${name}: savings/mutual pooled cards not both visible`);
  invariant(result.panelText.includes("전체 우대상품 침투율"), `${name}: product penetration header missing`);
  invariant(result.panelText.includes("상위금리군 침투율"), `${name}: top penetration header missing`);
  invariant(result.panelText.includes("침투율 차이"), `${name}: penetration lift header missing`);
  invariant(result.panelText.includes("침투율 분모:"), `${name}: denominator explanation missing`);
  invariant(result.panelText.includes("원천별 판별 가능"), `${name}: source coverage evidence missing`);
  invariant(result.sourceChips.length === 3, `${name}: mutual source coverage chips=${result.sourceChips.length}`);
  invariant(result.scopeTags.some((value) => value.includes("상호금융 통합")), `${name}: pooled mutual scope tag missing`);
  if (result.firstSavingsCategory && result.firstSavingsCells.length >= 4) {
    invariant(
      result.firstSavingsCells[1] === pct0(result.firstSavingsCategory.market_product_share),
      `${name}: rendered market penetration mismatch`,
    );
    invariant(
      result.firstSavingsCells[2] === pct0(result.firstSavingsCategory.top_tier_product_share),
      `${name}: rendered top penetration mismatch`,
    );
    invariant(
      result.firstSavingsCells[3] === lift1(result.firstSavingsCategory.top_tier_lift_pp),
      `${name}: rendered penetration lift mismatch`,
    );
  }

  if (name === "desktop") {
    invariant(result.bodyFontSize >= 17, `desktop: body font ${result.bodyFontSize}`);
    invariant(result.headingFontSize >= 19, `desktop: section heading font ${result.headingFontSize}`);
    invariant(result.tableFontSize == null || result.tableFontSize >= 12.5, `desktop: table font ${result.tableFontSize}`);
  } else {
    invariant(result.bodyFontSize >= 16, `mobile: body font ${result.bodyFontSize}`);
  }

  await assertSingleMutualFallback(page, name);

  await page.screenshot({
    path: path.join(workDir, `dashboard-usability-preference-v2-${name}.png`),
    fullPage: true,
  });
  await context.close();
  return result;
}

(async () => {
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  try {
    const result = {
      baseUrl,
      desktop: await runViewport(browser, "desktop", { width: 1440, height: 1000 }),
      mobile: await runViewport(browser, "mobile", { width: 390, height: 844 }),
    };
    fs.writeFileSync(
      path.join(workDir, "dashboard-usability-preference-v2-metrics.json"),
      JSON.stringify(result, null, 2),
    );
    console.log(JSON.stringify({
      bodyFontDesktop: result.desktop.bodyFontSize,
      headingFontDesktop: result.desktop.headingFontSize,
      tableFontDesktop: result.desktop.tableFontSize,
      preferenceCardsDesktop: result.desktop.cardCount,
      mutualSourceChips: result.desktop.sourceChips,
      bodyFontMobile: result.mobile.bodyFontSize,
      mobileScrollWidth: result.mobile.document.scrollWidth,
    }, null, 2));
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
