const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("@playwright/test");

const baseUrl = process.env.STRATEGY_PREVIEW_BASE_URL || "http://127.0.0.1:4173";
const prefix = process.env.MAIN_MAP_SMOKE_PREFIX || "main-map";
const workDir = path.resolve("work");
fs.mkdirSync(workDir, { recursive: true });

function invariant(condition, message) {
  if (!condition) throw new Error(message);
}

function overlapPairs(boxes) {
  const out = [];
  for (let i = 0; i < boxes.length; i += 1) {
    for (let j = i + 1; j < boxes.length; j += 1) {
      const a = boxes[i], b = boxes[j];
      const w = Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left));
      const h = Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top));
      if (w * h >= 12) out.push([a.text, b.text, Math.round(w * h)]);
    }
  }
  return out;
}

async function waitForMain(page) {
  await page.route("**/favicon.ico", (route) => route.fulfill({ status: 204, body: "" }));
  const response = await page.goto(`${baseUrl}/`, { waitUntil: "networkidle" });
  invariant(response && response.ok(), `index.html HTTP ${response ? response.status() : "no response"}`);
  await page.waitForSelector("#reg .main-map-shell", { timeout: 30_000 });
  await page.waitForFunction(
    () => document.querySelectorAll("#reg .main-map-label-name").length === 9,
    null,
    { timeout: 10_000 },
  );
}

async function measure(page, mode) {
  return page.evaluate((currentMode) => {
    const card = document.querySelector(".charts .card.wide.global");
    const stage = document.querySelector(currentMode === "busan" ? ".main-busan-stage" : ".main-map-stage");
    const names = [...document.querySelectorAll(currentMode === "busan" ? ".main-busan-label-name" : ".main-map-label-name")];
    const rect = (el) => {
      const r = el.getBoundingClientRect();
      return { text: el.textContent.trim(), left: r.left, top: r.top, right: r.right, bottom: r.bottom, width: r.width, height: r.height };
    };
    return {
      viewport: { width: window.innerWidth, height: window.innerHeight },
      document: { clientWidth: document.documentElement.clientWidth, scrollWidth: document.documentElement.scrollWidth },
      card: card ? rect(card) : null,
      stage: stage ? rect(stage) : null,
      labels: names.map(rect),
      busanPaths: document.querySelectorAll(".main-busan-stage #busan-boundaries path[id]").length,
    };
  }, mode);
}

async function captureScenario(browser, name, viewport) {
  const page = await browser.newPage({ viewport });
  await waitForMain(page);
  const card = page.locator(".charts .card.wide.global");
  await card.scrollIntoViewIfNeeded();

  const national = await measure(page, "national");
  invariant(national.document.scrollWidth <= national.document.clientWidth + 1, `${name} national horizontal overflow`);
  invariant(national.labels.length === 9, `${name} national direct label count ${national.labels.length}`);
  if (viewport.width >= 1001) invariant(national.card.width <= 990, `${name} desktop region card too wide: ${national.card.width}`);
  await card.screenshot({ path: path.join(workDir, `${prefix}-${name}-national.png`) });

  const busanPath = page.locator('#reg .main-map-stage svg path[data-region-key="부산"]').first();
  invariant(await busanPath.count() === 1, `${name} 부산 전국지도 path 없음`);
  await busanPath.click();
  await page.waitForSelector("#reg .main-busan-map-shell", { timeout: 10_000 });
  await page.waitForFunction(() => document.querySelectorAll(".main-busan-stage #busan-boundaries path[id]").length === 16);
  await page.waitForFunction(() => document.querySelectorAll(".main-busan-label-name").length === 16);

  const busan = await measure(page, "busan");
  invariant(busan.document.scrollWidth <= busan.document.clientWidth + 1, `${name} 부산 horizontal overflow`);
  invariant(busan.busanPaths === 16, `${name} 부산 path count ${busan.busanPaths}`);
  invariant(busan.labels.length === 16, `${name} 부산 label count ${busan.labels.length}`);
  await card.screenshot({ path: path.join(workDir, `${prefix}-${name}-busan.png`) });

  return {
    national: { ...national, overlaps: overlapPairs(national.labels) },
    busan: { ...busan, overlaps: overlapPairs(busan.labels) },
  };
}

(async () => {
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  try {
    const metrics = {
      baseUrl,
      desktop: await captureScenario(browser, "desktop", { width: 1440, height: 1000 }),
      mobile: await captureScenario(browser, "mobile", { width: 390, height: 844 }),
    };
    fs.writeFileSync(path.join(workDir, `${prefix}-layout-metrics.json`), JSON.stringify(metrics, null, 2));
    console.log(JSON.stringify({
      baseUrl,
      prefix,
      desktopNationalOverlaps: metrics.desktop.national.overlaps,
      desktopBusanOverlaps: metrics.desktop.busan.overlaps,
      mobileNationalOverlaps: metrics.mobile.national.overlaps,
      mobileBusanOverlaps: metrics.mobile.busan.overlaps,
      desktopCardWidth: metrics.desktop.national.card.width,
      mobileScrollWidth: metrics.mobile.busan.document.scrollWidth,
    }, null, 2));
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
