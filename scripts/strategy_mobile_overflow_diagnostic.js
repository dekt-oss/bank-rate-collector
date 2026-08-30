const { chromium } = require("@playwright/test");
const baseUrl = process.env.STRATEGY_PREVIEW_BASE_URL || "http://127.0.0.1:4173";

function short(el) {
  const id = el.id ? `#${el.id}` : "";
  const cls = typeof el.className === "string" && el.className.trim()
    ? `.${el.className.trim().split(/\s+/).slice(0, 5).join(".")}` : "";
  return `${el.tagName.toLowerCase()}${id}${cls}`;
}

(async () => {
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  try {
    for (const width of [430, 390]) {
      const context = await browser.newContext({ viewport: { width, height: 900 } });
      const page = await context.newPage();
      await page.goto(`${baseUrl}/strategy.html`, { waitUntil: "networkidle" });
      const result = await page.evaluate(() => {
        const visible = (el) => {
          const s = getComputedStyle(el), r = el.getBoundingClientRect();
          return s.display !== "none" && s.visibility !== "hidden" && r.width > 0 && r.height > 0;
        };
        const label = (el) => {
          const id = el.id ? `#${el.id}` : "";
          const cls = typeof el.className === "string" && el.className.trim()
            ? `.${el.className.trim().split(/\s+/).slice(0, 5).join(".")}` : "";
          return `${el.tagName.toLowerCase()}${id}${cls}`;
        };
        const style = (el) => {
          const s = getComputedStyle(el), r = el.getBoundingClientRect();
          return {
            label: label(el), width: r.width, clientWidth: el.clientWidth, scrollWidth: el.scrollWidth,
            cssWidth: s.width, minWidth: s.minWidth, maxWidth: s.maxWidth,
            display: s.display, overflowX: s.overflowX,
            gridTemplateColumns: s.gridTemplateColumns, flexBasis: s.flexBasis,
            whiteSpace: s.whiteSpace, position: s.position,
          };
        };
        const selectors = ["article.card.sim", ".funding-position-table-wrap", ".chartwrap", ".ux-pref-sector.pref-intel-main"];
        return selectors.flatMap((selector) => [...document.querySelectorAll(selector)].filter(visible).map((host) => {
          const descendants = [...host.querySelectorAll("*")].filter(visible).map(style)
            .sort((a,b) => b.width - a.width).slice(0, 12);
          return { host: style(host), descendants };
        }));
      });
      console.log(JSON.stringify({ width, result }, null, 2));
      await context.close();
    }
  } finally {
    await browser.close();
  }
})().catch((error) => { console.error(error.stack || error); process.exit(1); });
