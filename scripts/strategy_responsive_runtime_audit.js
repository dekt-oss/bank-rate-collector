const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("@playwright/test");

const baseUrl = (process.env.PRODUCTION_URL || "http://127.0.0.1:4173").replace(/\/$/, "");
const password = process.env.DASHBOARD_PASSWORD || "";
const skipAuth = process.env.AUDIT_SKIP_AUTH === "1";
const outDir = path.resolve("work/strategy-responsive-audit");
fs.mkdirSync(outDir, { recursive: true });

const scenarios = [
  { name: "desktop-1440", width: 1440, height: 1000 },
  { name: "mobile-430", width: 430, height: 932 },
  { name: "mobile-390", width: 390, height: 844 },
];

function sanitize(value) {
  return String(value || "").replace(/\s+/g, " ").trim().slice(0, 220);
}

async function enterStrategy(page) {
  if (skipAuth) {
    const response = await page.goto(`${baseUrl}/strategy.html`, { waitUntil: "networkidle" });
    if (!response || !response.ok()) throw new Error(`strategy HTTP ${response ? response.status() : "no response"}`);
    return;
  }
  if (!password) throw new Error("DASHBOARD_PASSWORD secret is empty");
  const response = await page.goto(`${baseUrl}/__login?returnTo=%2Fstrategy.html`, { waitUntil: "domcontentloaded" });
  if (!response) throw new Error("login navigation returned no response");
  if (response.status() >= 500) throw new Error(`login HTTP ${response.status()}`);
  const input = page.locator('input[type="password"][name="password"]');
  await input.waitFor({ state: "visible", timeout: 20_000 });
  await input.fill(password);
  await page.locator('button[type="submit"]').click();
  await page.waitForTimeout(800);
  if (!/\/strategy\.html(?:[?#].*)?$/.test(page.url())) {
    const alert = await page.locator('[role="alert"]').textContent().catch(() => "");
    throw new Error(`site login rejected; current=${page.url()} alert=${sanitize(alert)}`);
  }
  await page.waitForLoadState("networkidle");
}

async function collectLayout(page) {
  return page.evaluate(() => {
    const visible = (el) => {
      const s = getComputedStyle(el);
      const r = el.getBoundingClientRect();
      return s.display !== "none" && s.visibility !== "hidden" && Number(s.opacity || 1) !== 0 && r.width > 0 && r.height > 0;
    };
    const rect = (el) => {
      const r = el.getBoundingClientRect();
      return { x: r.x, y: r.y, width: r.width, height: r.height, right: r.right, bottom: r.bottom };
    };
    const label = (el) => {
      const id = el.id ? `#${el.id}` : "";
      const cls = typeof el.className === "string" && el.className.trim()
        ? `.${el.className.trim().split(/\s+/).slice(0, 4).join(".")}`
        : "";
      return `${el.tagName.toLowerCase()}${id}${cls}`;
    };

    const doc = document.documentElement;
    const candidates = [...document.querySelectorAll(
      'svg,canvas,[id*="chart" i],[class*="chart" i],[id*="graph" i],[class*="graph" i],[id*="matrix" i],[class*="matrix" i],[id*="plot" i],[class*="plot" i],[id*="scatter" i],[class*="scatter" i]'
    )];
    const graphics = candidates.map((el) => ({
      label: label(el),
      visible: visible(el),
      rect: rect(el),
      scrollWidth: el.scrollWidth,
      clientWidth: el.clientWidth,
      childNodes: el.childNodes.length,
      svgPaths: el.tagName === "svg" ? el.querySelectorAll("path").length : null,
      svgCircles: el.tagName === "svg" ? el.querySelectorAll("circle").length : null,
      svgLines: el.tagName === "svg" ? el.querySelectorAll("line").length : null,
      text: (el.textContent || "").replace(/\s+/g, " ").trim().slice(0, 220),
    }));

    const overflow = [...document.querySelectorAll("main,section,article,.card,[class*='panel' i],[class*='table' i],[class*='chart' i],[class*='matrix' i]")]
      .filter(visible)
      .filter((el) => el.scrollWidth > el.clientWidth + 3)
      .map((el) => ({ label: label(el), clientWidth: el.clientWidth, scrollWidth: el.scrollWidth, rect: rect(el) }))
      .slice(0, 100);

    const buttons = [...document.querySelectorAll("button")]
      .filter(visible)
      .map((el) => ({
        text: (el.textContent || "").replace(/\s+/g, " ").trim().slice(0, 100),
        id: el.id || "",
        className: typeof el.className === "string" ? el.className : "",
        dataset: { ...el.dataset },
        rect: rect(el),
      }));

    return {
      location: location.href,
      viewport: { width: innerWidth, height: innerHeight },
      document: { clientWidth: doc.clientWidth, scrollWidth: doc.scrollWidth, clientHeight: doc.clientHeight, scrollHeight: doc.scrollHeight },
      bodyOverflowX: getComputedStyle(document.body).overflowX,
      graphics,
      overflow,
      buttons,
    };
  });
}

async function exerciseSectorButtons(page) {
  const results = [];
  const buttons = page.locator('button[data-sector], button[data-funding-sector], button[data-position-sector], button[data-matrix-sector]');
  const count = await buttons.count();
  for (let i = 0; i < Math.min(count, 24); i += 1) {
    const button = buttons.nth(i);
    if (!(await button.isVisible())) continue;
    const text = sanitize(await button.textContent());
    const disabled = await button.isDisabled().catch(() => false);
    if (disabled) {
      results.push({ text, disabled: true });
      continue;
    }
    try {
      await button.click({ timeout: 5_000 });
      await page.waitForTimeout(350);
      const layout = await collectLayout(page);
      results.push({
        text,
        disabled: false,
        documentOverflow: layout.document.scrollWidth - layout.document.clientWidth,
        visibleGraphics: layout.graphics.filter((g) => g.visible).length,
        zeroSizedVisibleGraphics: layout.graphics.filter((g) => g.visible && (g.rect.width < 2 || g.rect.height < 2)).map((g) => g.label),
      });
    } catch (error) {
      results.push({ text, disabled: false, error: String(error) });
    }
  }
  return results;
}

(async () => {
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  const report = { baseUrl, skipAuth, generatedAt: new Date().toISOString(), scenarios: [] };
  try {
    for (const scenario of scenarios) {
      const context = await browser.newContext({ viewport: { width: scenario.width, height: scenario.height } });
      const page = await context.newPage();
      const consoleErrors = [];
      const pageErrors = [];
      page.on("console", (msg) => {
        if (msg.type() === "error") consoleErrors.push(sanitize(msg.text()));
      });
      page.on("pageerror", (error) => pageErrors.push(sanitize(error.message || error)));

      await enterStrategy(page);
      const initial = await collectLayout(page);
      const sectorInteractions = await exerciseSectorButtons(page);
      const afterInteractions = await collectLayout(page);

      await page.screenshot({ path: path.join(outDir, `${scenario.name}.png`), fullPage: true });
      report.scenarios.push({ ...scenario, consoleErrors, pageErrors, initial, sectorInteractions, afterInteractions });
      await context.close();
    }
  } finally {
    await browser.close();
  }

  fs.writeFileSync(path.join(outDir, "report.json"), JSON.stringify(report, null, 2));
  const summary = report.scenarios.map((s) => ({
    name: s.name,
    documentOverflow: s.afterInteractions.document.scrollWidth - s.afterInteractions.document.clientWidth,
    overflowContainers: s.afterInteractions.overflow.length,
    visibleGraphics: s.afterInteractions.graphics.filter((g) => g.visible).length,
    zeroSizedVisibleGraphics: s.afterInteractions.graphics.filter((g) => g.visible && (g.rect.width < 2 || g.rect.height < 2)).map((g) => g.label),
    consoleErrors: s.consoleErrors,
    pageErrors: s.pageErrors,
  }));
  console.log(JSON.stringify(summary, null, 2));
  if (summary.some((s) => s.pageErrors.length > 0)) process.exitCode = 2;
})();
