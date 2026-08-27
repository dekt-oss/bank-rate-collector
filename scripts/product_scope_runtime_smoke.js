const { chromium } = require("@playwright/test");

const baseUrl = process.env.STRATEGY_PREVIEW_BASE_URL || "http://127.0.0.1:4173";

function invariant(condition, message) {
  if (!condition) throw new Error(message);
}

function trackRuntimeErrors(page, runtimeErrors) {
  page.on("pageerror", (error) => runtimeErrors.push(`pageerror: ${error.message}`));
  page.on("console", (message) => {
    if (message.type() === "error" && !message.text().includes("Failed to load resource")) {
      runtimeErrors.push(`console: ${message.text()}`);
    }
  });
  page.on("response", (response) => {
    if (response.status() < 400) return;
    const url = new URL(response.url());
    if (url.pathname === "/favicon.ico") return;
    runtimeErrors.push(`http ${response.status()}: ${url.pathname}`);
  });
}

async function assertSearchShareableState(browser) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await context.newPage();
  const runtimeErrors = [];
  trackRuntimeErrors(page, runtimeErrors);

  const url = `${baseUrl}/?family=savings&savings=none&term=24`;
  const response = await page.goto(url, { waitUntil: "networkidle" });
  invariant(response && response.ok(), "search shareable URL failed to load");
  await page.waitForSelector('[data-product-family-toggle="savings"]', { timeout: 20_000 });
  await page.waitForSelector(".product-savings-detail", { timeout: 20_000 });

  const searchDeposit = page.locator('[data-product-family-toggle="deposit"]');
  const searchSavings = page.locator('[data-product-family-toggle="savings"]');
  invariant(
    await searchSavings.isChecked() && !(await searchDeposit.isChecked()),
    "search shared URL did not restore savings-only family state",
  );
  invariant(
    await page.locator('.product-savings-detail input[data-group="type"]:checked').count() === 0,
    "search shared URL did not restore zero savings subtype selection",
  );
  invariant(
    await page.locator('[data-global-term="24"]').getAttribute("aria-pressed") === "true",
    "search shared URL did not restore 24 month term",
  );
  invariant(
    await page.locator(".product-savings-detail .product-empty-state").isVisible(),
    "search zero-selection empty state is not visible",
  );
  invariant(
    (await page.locator(".product-savings-detail .product-empty-state").textContent()).includes(
      "선택된 적금 유형이 없습니다",
    ),
    "search zero-selection empty state copy is missing",
  );

  await page.locator('input[data-group="type"][value="installment_savings"]').check();
  await page.locator('[data-global-term="12"]').click();
  await page.waitForFunction(() => {
    const params = new URLSearchParams(location.search);
    return params.get("family") === "savings"
      && params.get("savings") === "installment_savings"
      && params.get("term") === "12";
  });

  await page.reload({ waitUntil: "networkidle" });
  await page.waitForSelector(".product-savings-detail", { timeout: 20_000 });
  invariant(
    await page.locator('input[data-group="type"][value="installment_savings"]').isChecked(),
    "search reload lost installment savings selection",
  );
  invariant(
    !(await page.locator('input[data-group="type"][value="flexible_savings"]').isChecked()),
    "search reload unexpectedly selected flexible savings",
  );
  invariant(
    await page.locator('[data-global-term="12"]').getAttribute("aria-pressed") === "true",
    "search reload lost 12 month term",
  );
  invariant(runtimeErrors.length === 0, `search product scope runtime errors:\n${runtimeErrors.join("\n")}`);
  await context.close();
}

async function waitForStrategyControls(page, expectedTerm) {
  await page.waitForSelector('[data-product-mode="deposit"]', {
    state: "attached",
    timeout: 30_000,
  });
  await page.waitForSelector('[data-product-family-toggle="deposit"]', { timeout: 30_000 });
  await page.waitForSelector("#strategy-scope-contract", { timeout: 30_000 });
  await page.waitForFunction(
    (term) => document.getElementById("product-scope-pill")?.textContent.includes(`${term}개월`),
    expectedTerm,
    { timeout: 30_000 },
  );
}

async function assertStrategyShareableState(browser) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await context.newPage();
  const runtimeErrors = [];
  trackRuntimeErrors(page, runtimeErrors);

  let response = await page.goto(
    `${baseUrl}/strategy.html?family=savings&savings=none&term=24`,
    { waitUntil: "networkidle" },
  );
  invariant(response && response.ok(), "strategy zero-selection shared URL failed to load");
  await waitForStrategyControls(page, 24);
  await page.waitForFunction(
    () => document.querySelector('[data-product-mode="savings"]')?.classList.contains("active")
      && document.getElementById("product-scope-pill")?.textContent.includes("24개월"),
    null,
    { timeout: 20_000 },
  );
  invariant(
    await page.locator('[data-savings-type]:checked').count() === 0,
    "strategy shared URL did not restore zero savings subtype selection",
  );
  invariant(
    await page.locator("#strategy-product-empty").isVisible(),
    "strategy zero-selection empty state is not visible",
  );
  invariant(
    (await page.locator("#strategy-product-empty").textContent()).includes("선택된 적금 유형이 없습니다"),
    "strategy zero-selection empty state copy is missing",
  );
  invariant(
    Number((await page.locator("#count").textContent()).replaceAll(",", "")) === 0,
    "strategy zero savings subtype selection should produce an empty comparison set",
  );

  await page.locator('[data-savings-type="installment_savings"]').check();
  await page.locator('[data-savings-type="flexible_savings"]').check();
  await page.locator('[data-scope-term="12"]').click();
  await page.waitForFunction(() => {
    const params = new URLSearchParams(location.search);
    const savings = new Set((params.get("savings") || "").split(",").filter(Boolean));
    return params.get("family") === "savings"
      && params.get("term") === "12"
      && savings.has("installment_savings")
      && savings.has("flexible_savings");
  });
  await page.waitForFunction(
    () => Number(document.getElementById("count")?.textContent.replaceAll(",", "") || 0) > 0,
    null,
    { timeout: 20_000 },
  );

  const policyState = await page.evaluate(() => {
    const panel = document.getElementById("savings-subtype-trend");
    const note = document.getElementById("savings-subtype-policy-note");
    const chart = panel?.querySelector(".savings-subtype-chart-scroll");
    const text = note?.textContent || "";
    return {
      panelVisible: Boolean(panel && !panel.hidden),
      note: text,
      chartVisible: Boolean(chart && !chart.hidden),
      installmentLines: panel?.querySelectorAll("path.line.installment").length || 0,
      flexibleLines: panel?.querySelectorAll("path.line.flexible").length || 0,
    };
  });
  invariant(policyState.panelVisible, "savings-all adaptive trend policy panel is not visible");
  invariant(
    policyState.note.includes("두 추이를 분리 표시") || policyState.note.includes("통합 추이 유지"),
    `adaptive trend policy decision is missing: ${policyState.note}`,
  );
  if (policyState.note.includes("두 추이를 분리 표시")) {
    invariant(policyState.chartVisible, "split policy did not expose subtype trend chart");
    invariant(
      policyState.installmentLines > 0 && policyState.flexibleLines > 0,
      "split policy did not render both installment and flexible trend lines",
    );
  } else {
    invariant(!policyState.chartVisible, "combined policy should keep subtype trend chart hidden");
  }

  const sharedUrl = page.url();
  response = await page.goto(sharedUrl, { waitUntil: "networkidle" });
  invariant(response && response.ok(), "strategy shared URL reload failed");
  await waitForStrategyControls(page, 12);
  await page.waitForFunction(
    () => document.querySelector('[data-product-mode="savings"]')?.classList.contains("active")
      && document.getElementById("product-scope-pill")?.textContent.includes("12개월"),
    null,
    { timeout: 20_000 },
  );
  invariant(
    await page.locator('[data-savings-type]:checked').count() === 2,
    "strategy shared URL reload lost savings subtype selections",
  );

  const savingsCount = Number((await page.locator("#count").textContent()).replaceAll(",", ""));
  await page.locator('[data-product-family-toggle="deposit"]').check();
  await page.waitForFunction(() => {
    const params = new URLSearchParams(location.search);
    const pill = document.getElementById("product-scope-pill")?.textContent || "";
    const contract = document.getElementById("strategy-scope-contract")?.textContent || "";
    return params.get("family") === "combined"
      && params.get("term") === "12"
      && pill.includes("예금 + 적금")
      && contract.includes("예금 + 적금");
  });
  await page.waitForFunction(
    (minimum) => Number(document.getElementById("count")?.textContent.replaceAll(",", "") || 0) >= minimum,
    savingsCount,
    { timeout: 20_000 },
  );
  invariant(
    await page.locator('[data-product-family-toggle="deposit"]').isChecked()
      && await page.locator('[data-product-family-toggle="savings"]').isChecked(),
    "strategy combined mode did not keep both product families checked",
  );
  invariant(
    await page.locator("#prediction-toggle").isVisible()
      && await page.locator("#prediction-panel").isVisible(),
    "combined product scope must keep prediction details visible while calculations remain deposit-only",
  );
  invariant(
    !(await page.locator("#strategy-product-empty").isVisible()),
    "combined product scope should not expose the savings-only empty state",
  );
  await page.waitForFunction(
    () => {
      const rows = [...document.querySelectorAll("#top5 tr")].filter((row) => row.querySelector(".bank"));
      const ownPosition = document.querySelector('#top5 [data-own-position="row"],#top5 [data-own-position="empty"]');
      return rows.length > 0
        && rows.every((row) => row.querySelector(".product-family-badge"))
        && Boolean(ownPosition);
    },
    null,
    { timeout: 20_000 },
  );

  await page.waitForFunction(
    () => document.querySelectorAll(".decision-integrated-insight .insight").length === 3,
    null,
    { timeout: 20_000 },
  );
  const readability = await page.evaluate(() => {
    const activeTerm = document.querySelector('[data-scope-term="12"]');
    const inactiveTerm = document.querySelector('[data-scope-term="24"]');
    const familyControl = document.querySelector('.strategy-family-checks label');
    const bank = document.querySelector(".top5-card .bank");
    const insights = document.querySelector(".insightcard .insights");
    const insightTitle = document.querySelector(".insightcard .insight b");
    const scopeContract = document.getElementById("strategy-scope-contract");
    const ownPosition = document.querySelector('#top5 [data-own-position="row"],#top5 [data-own-position="empty"]');
    const style = (node) => node ? getComputedStyle(node) : null;
    const top5Rows = [...document.querySelectorAll("#top5 tr")]
      .filter((row) => row.querySelector(".bank"));
    const familyBadges = [...document.querySelectorAll("#top5 .product-family-badge")];
    const visibleInsightCards = [...document.querySelectorAll(".decision-integrated-insight .insight")]
      .filter((node) => {
        const computed = style(node);
        return computed?.display !== "none" && node.getBoundingClientRect().width > 0;
      });
    const insightRows = new Set(
      visibleInsightCards.map((node) => Math.round(node.getBoundingClientRect().top)),
    );
    const insightMetrics = visibleInsightCards
      .map((node) => node.querySelector(".insight-metric"))
      .filter(Boolean);
    const insightEvidence = visibleInsightCards
      .map((node) => node.querySelector(".insight-evidence"))
      .filter(Boolean);
    const insightActions = visibleInsightCards
      .map((node) => node.querySelector(".insight-action"))
      .filter(Boolean);
    return {
      activeTermBackground: style(activeTerm)?.backgroundColor || "",
      inactiveTermBackground: style(inactiveTerm)?.backgroundColor || "",
      termFontSize: Number.parseFloat(style(activeTerm)?.fontSize || "0"),
      familyControlFontSize: Number.parseFloat(style(familyControl)?.fontSize || "0"),
      bankFontSize: Number.parseFloat(style(bank)?.fontSize || "0"),
      bankFontWeight: Number.parseInt(style(bank)?.fontWeight || "0", 10),
      top5RowCount: top5Rows.length,
      familyBadgeCount: familyBadges.length,
      familyBadgeLabels: familyBadges.map((node) => String(node.textContent || "").trim()),
      scopeContractText: String(scopeContract?.textContent || ""),
      ownPositionKind: ownPosition?.getAttribute("data-own-position") || "",
      ownPositionText: String(ownPosition?.textContent || ""),
      insightColumns: style(insights)?.gridTemplateColumns || "",
      insightTitleFontSize: Number.parseFloat(style(insightTitle)?.fontSize || "0"),
      insightCardCount: visibleInsightCards.length,
      insightRowCount: insightRows.size,
      insightMetricCount: insightMetrics.length,
      insightMetricMinFontSize: insightMetrics.length
        ? Math.min(...insightMetrics.map((node) => Number.parseFloat(style(node)?.fontSize || "0")))
        : 0,
      insightMetricMinWeight: insightMetrics.length
        ? Math.min(...insightMetrics.map((node) => Number.parseInt(style(node)?.fontWeight || "0", 10)))
        : 0,
      insightEvidenceCount: insightEvidence.length,
      insightActionCount: insightActions.length,
      allEvidenceLabeled: insightEvidence.every((node) => String(node.textContent || "").startsWith("판단 근거 · ")),
      allActionsLabeled: insightActions.every((node) => String(node.textContent || "").startsWith("권고 행동 · ")),
    };
  });
  invariant(
    readability.activeTermBackground !== readability.inactiveTermBackground,
    "active and inactive global term controls are not visually distinct",
  );
  invariant(readability.termFontSize >= 12, "global term control remains too small");
  invariant(readability.familyControlFontSize >= 12, "product family control remains too small");
  invariant(readability.bankFontSize >= 12, "TOP5 bank label remains too small");
  invariant(readability.bankFontWeight >= 800, "TOP5 bank label remains too faint");
  invariant(
    readability.top5RowCount > 0 && readability.familyBadgeCount === readability.top5RowCount,
    `TOP5 product family badges are incomplete: rows=${readability.top5RowCount}, badges=${readability.familyBadgeCount}`,
  );
  invariant(
    readability.familyBadgeLabels.every((label) => label === "예금" || label === "적금"),
    `TOP5 product family badge label is invalid: ${readability.familyBadgeLabels.join(", ")}`,
  );
  invariant(
    readability.scopeContractText.includes("통합 이력 미생성")
      && readability.scopeContractText.includes("예금 단독에서만 사용"),
    `combined scope boundary is unclear: ${readability.scopeContractText}`,
  );
  invariant(
    readability.ownPositionKind === "row" || readability.ownPositionKind === "empty",
    `own position marker is missing: ${readability.ownPositionKind}`,
  );
  if (readability.ownPositionKind === "row") {
    invariant(
      readability.ownPositionText.includes("고려저축은행")
        && readability.ownPositionText.includes("당사 위치"),
      `own position row lacks decision context: ${readability.ownPositionText}`,
    );
  }
  invariant(
    readability.insightColumns.trim().split(/\s+/).length === 3,
    `desktop insight grid does not expose three columns: ${readability.insightColumns}`,
  );
  invariant(
    readability.insightCardCount === 3 && readability.insightRowCount === 1,
    `desktop decision insights must stay on one row: cards=${readability.insightCardCount}, rows=${readability.insightRowCount}`,
  );
  invariant(readability.insightTitleFontSize >= 12, "insight title remains too small");
  invariant(
    readability.insightMetricCount === 3
      && readability.insightMetricMinFontSize >= 26
      && readability.insightMetricMinWeight >= 800,
    `decision insight metrics are not visually emphasized: count=${readability.insightMetricCount}, size=${readability.insightMetricMinFontSize}, weight=${readability.insightMetricMinWeight}`,
  );
  invariant(
    readability.insightEvidenceCount === 3
      && readability.insightActionCount === 3
      && readability.allEvidenceLabeled
      && readability.allActionsLabeled,
    "decision insights do not expose explicit evidence/action roles",
  );

  const combinedUrl = page.url();
  response = await page.goto(combinedUrl, { waitUntil: "networkidle" });
  invariant(response && response.ok(), "strategy combined shared URL reload failed");
  await waitForStrategyControls(page, 12);
  await page.waitForFunction(
    () => {
      const contract = document.getElementById("strategy-scope-contract")?.textContent || "";
      return document.getElementById("product-scope-pill")?.textContent.includes("예금 + 적금")
        && contract.includes("통합 이력 미생성")
        && contract.includes("예금 단독에서만 사용");
    },
    null,
    { timeout: 20_000 },
  );
  invariant(
    await page.locator('[data-product-family-toggle="deposit"]').isChecked()
      && await page.locator('[data-product-family-toggle="savings"]').isChecked(),
    "strategy combined shared URL reload lost product family selections",
  );
  invariant(runtimeErrors.length === 0, `strategy product scope runtime errors:\n${runtimeErrors.join("\n")}`);
  await context.close();
}

(async () => {
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  try {
    await assertSearchShareableState(browser);
    await assertStrategyShareableState(browser);
    console.log("product scope runtime smoke: PASS");
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error.stack || error.message || String(error));
  process.exit(1);
});