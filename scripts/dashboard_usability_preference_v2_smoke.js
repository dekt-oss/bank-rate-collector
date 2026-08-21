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
    const sourceChips = mutual ? [...mutual.querySelectorAll(".pref-v2-source span")].map((node) => node.textContent.trim()) : [];
    const scopeTags = [...(panel?.querySelectorAll(".ux-pref-scope-tag") || [])].map((node) => node.textContent.trim());
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
      payload: {
        version: intelligence.version,
        categoryDenominator: intelligence.category_denominator,
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
  invariant(result.document.scrollWidth <= result.document.clientWidth + 1, `${name}: horizontal overflow ${result.document.scrollWidth} > ${result.document.clientWidth}`);
  invariant(result.panelExists && result.preferenceV2 === "1", `${name}: preference v2 panel missing`);
  invariant(result.payload.version === "preference-intelligence-v2", `${name}: payload version=${result.payload.version}`);
  invariant(result.payload.categoryDenominator === "preference_bearing_products_present_only", `${name}: denominator=${result.payload.categoryDenominator}`);
  invariant(result.payload.mutualPolicy === "pooled_selected_mutual_sectors", `${name}: mutual policy=${result.payload.mutualPolicy}`);
  invariant(result.payload.mutualScopeCount === 28, `${name}: mutual scope count=${result.payload.mutualScopeCount}`);
  invariant(Boolean(result.payload.defaultMutual), `${name}: default pooled mutual 12m scope missing`);
  invariant(result.cardCount === 2, `${name}: default combined preference card count=${result.cardCount}`);
  invariant(result.savingsVisible && result.mutualVisible, `${name}: savings/mutual pooled cards not both visible`);
  invariant(result.panelText.includes("전체 우대조건 상품"), `${name}: preference-bearing denominator header missing`);
  invariant(result.panelText.includes("비중 분모:"), `${name}: denominator explanation missing`);
  invariant(result.panelText.includes("원천별 판별 가능"), `${name}: source coverage evidence missing`);
  invariant(result.sourceChips.length === 3, `${name}: mutual source coverage chips=${result.sourceChips.length}`);
  invariant(result.scopeTags.some((value) => value.includes("상호금융 통합")), `${name}: pooled mutual scope tag missing`);

  if (name === "desktop") {
    invariant(result.bodyFontSize >= 17, `desktop: body font ${result.bodyFontSize}`);
    invariant(result.headingFontSize >= 19, `desktop: section heading font ${result.headingFontSize}`);
    invariant(result.tableFontSize == null || result.tableFontSize >= 12.5, `desktop: table font ${result.tableFontSize}`);
  } else {
    invariant(result.bodyFontSize >= 16, `mobile: body font ${result.bodyFontSize}`);
  }

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
