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
  await page.waitForSelector('[data-product-family="savings"]', { timeout: 20_000 });
  await page.waitForSelector(".product-savings-detail", { timeout: 20_000 });

  invariant(
    await page.locator('[data-product-family="savings"]').getAttribute("aria-pressed") === "true",
    "search shared URL did not restore savings family",
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
  await page.waitForSelector('[data-product-mode="deposit"]', { timeout: 30_000 });
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