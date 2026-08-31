const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("@playwright/test");

const baseUrl = process.env.STRATEGY_PREVIEW_BASE_URL || "http://127.0.0.1:4173";
const prefix = process.env.MAIN_MAP_SMOKE_PREFIX || "main-map";
const siteAccessPassword = process.env.SITE_ACCESS_PASSWORD || process.env.DASHBOARD_PASSWORD || "";
const baseHostname = new URL(baseUrl).hostname;
const localBase = baseHostname === "127.0.0.1" || baseHostname === "localhost";
const cropMode = process.env.EXPECT_MAIN_MAP_CROP;
const expectCrop = cropMode === "1" || (cropMode == null && localBase);
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

async function authenticateIfNeeded(page) {
  if (localBase) return;
  invariant(siteAccessPassword, "production main-map smoke requires SITE_ACCESS_PASSWORD");

  const loginUrl = new URL("/__login?returnTo=%2F", baseUrl).toString();
  const response = await page.goto(loginUrl, { waitUntil: "domcontentloaded" });
  invariant(response && response.ok(), `login HTTP ${response ? response.status() : "no response"}`);

  const passwordInput = page.locator('input[name="password"]');
  invariant(await passwordInput.count() === 1, "site access login form missing password input");
  await passwordInput.fill(siteAccessPassword);
  await Promise.all([
    page.waitForURL((url) => url.origin === new URL(baseUrl).origin && url.pathname === "/", { timeout: 10_000 }),
    page.locator('button[type="submit"]').click(),
  ]);
}

async function waitForMain(page) {
  await page.route("**/favicon.ico", (route) => route.fulfill({ status: 204, body: "" }));
  await authenticateIfNeeded(page);
  const response = await page.goto(`${baseUrl}/`, { waitUntil: "networkidle" });
  invariant(response && response.ok(), `index.html HTTP ${response ? response.status() : "no response"}`);
  await page.waitForSelector("#reg .main-map-shell", { timeout: 30_000 });
  await page.waitForFunction(
    () => document.querySelectorAll("#reg .main-map-label-name").length === 9,
    null,
    { timeout: 10_000 },
  );
  if (expectCrop) {
    await page.waitForFunction(
      () => document.querySelector("#reg .main-map-stage svg")?.dataset.mainlandJejuCrop === "1",
      null,
      { timeout: 10_000 },
    );
  }
}

async function measure(page, mode) {
  return page.evaluate((currentMode) => {
    const card = document.querySelector(".charts .card.wide.global");
    const stage = document.querySelector(currentMode === "busan" ? ".main-busan-stage" : ".main-map-stage");
    const names = [...document.querySelectorAll(currentMode === "busan" ? ".main-busan-label-name" : ".main-map-label-name")];
    const svg = currentMode === "national" ? document.querySelector(".main-map-stage svg") : null;
    const jeju = svg?.querySelector('#제주특별자치도');
    const rect = (el) => {
      const r = el.getBoundingClientRect();
      return { text: el.textContent.trim(), left: r.left, top: r.top, right: r.right, bottom: r.bottom, width: r.width, height: r.height };
    };
    const viewBox = svg?.viewBox?.baseVal
      ? { x: svg.viewBox.baseVal.x, y: svg.viewBox.baseVal.y, width: svg.viewBox.baseVal.width, height: svg.viewBox.baseVal.height }
      : null;
    const jejuBox = jeju?.getBBox ? jeju.getBBox() : null;
    return {
      viewport: { width: window.innerWidth, height: window.innerHeight },
      document: { clientWidth: document.documentElement.clientWidth, scrollWidth: document.documentElement.scrollWidth },
      card: card ? rect(card) : null,
      stage: stage ? rect(stage) : null,
      labels: names.map(rect),
      busanPaths: document.querySelectorAll(".main-busan-stage #busan-boundaries path[id]").length,
      crop: svg ? {
        applied: svg.dataset.mainlandJejuCrop === "1",
        omittedIslandSubpaths: Number(svg.dataset.omittedIslandSubpaths || 0),
        viewBox,
        jeju: jejuBox ? { x: jejuBox.x, y: jejuBox.y, width: jejuBox.width, height: jejuBox.height } : null,
      } : null,
    };
  }, mode);
}

async function assertJejuTooltip(page, name) {
  const jejuPath = page.locator('#reg .main-map-stage svg path#제주특별자치도').first();
  invariant(await jejuPath.count() === 1, `${name} 제주 path 없음`);
  await jejuPath.hover();
  await page.waitForFunction(() => {
    const tip = document.querySelector("#reg .main-map-stage .main-map-tooltip");
    return tip && !tip.hidden && tip.dataset.viewportFit === "1";
  }, null, { timeout: 5_000 });
  const fit = await page.evaluate(() => {
    const stage = document.querySelector("#reg .main-map-stage");
    const tip = stage?.querySelector(".main-map-tooltip");
    if (!stage || !tip) return null;
    const s = stage.getBoundingClientRect(), t = tip.getBoundingClientRect();
    return {
      stage: { left: s.left, top: s.top, right: s.right, bottom: s.bottom },
      tip: { left: t.left, top: t.top, right: t.right, bottom: t.bottom },
      text: tip.textContent.trim(),
    };
  });
  invariant(fit, `${name} 제주 tooltip 측정 실패`);
  invariant(fit.tip.left >= fit.stage.left - 1, `${name} 제주 tooltip left clipped`);
  invariant(fit.tip.right <= fit.stage.right + 1, `${name} 제주 tooltip right clipped`);
  invariant(fit.tip.top >= fit.stage.top - 1, `${name} 제주 tooltip top clipped`);
  invariant(fit.tip.bottom <= fit.stage.bottom + 1, `${name} 제주 tooltip bottom clipped`);
  invariant(fit.text.includes("제주"), `${name} 제주 tooltip 내용 누락`);
  return fit;
}

async function captureScenario(browser, name, viewport) {
  const page = await browser.newPage({ viewport });
  await waitForMain(page);
  const card = page.locator(".charts .card.wide.global");
  await card.scrollIntoViewIfNeeded();

  const national = await measure(page, "national");
  const nationalOverlaps = overlapPairs(national.labels);
  invariant(national.document.scrollWidth <= national.document.clientWidth + 1, `${name} national horizontal overflow`);
  invariant(national.labels.length === 9, `${name} national direct label count ${national.labels.length}`);
  if (viewport.width >= 1001) {
    const maxWidth = expectCrop ? 750 : 990;
    invariant(national.card.width <= maxWidth, `${name} desktop region card too wide: ${national.card.width}`);
    if (expectCrop) invariant(national.stage.width >= 430, `${name} desktop national map remains too small: ${national.stage.width}`);
  }
  if (expectCrop) {
    invariant(national.crop?.applied, `${name} mainland+Jeju crop not applied`);
    invariant(national.crop.omittedIslandSubpaths > 0, `${name} island subpaths were not pruned`);
    invariant(national.crop.viewBox && national.crop.viewBox.width < 700, `${name} national viewBox not tightened`);
    invariant(national.crop.jeju && national.crop.jeju.width > 0 && national.crop.jeju.height > 0, `${name} Jeju main island missing`);
    invariant(nationalOverlaps.length === 0, `${name} national label overlaps: ${JSON.stringify(nationalOverlaps)}`);
  }
  const jejuTooltip = expectCrop ? await assertJejuTooltip(page, name) : null;
  await card.screenshot({ path: path.join(workDir, `${prefix}-${name}-national.png`) });

  const busanPath = page.locator('#reg .main-map-stage svg path[data-region-key="부산"]').first();
  invariant(await busanPath.count() === 1, `${name} 부산 전국지도 path 없음`);
  await busanPath.click();
  await page.waitForSelector("#reg .main-busan-map-shell", { timeout: 10_000 });
  await page.waitForFunction(() => document.querySelectorAll(".main-busan-stage #busan-boundaries path[id]").length === 16);
  await page.waitForFunction(() => document.querySelectorAll(".main-busan-label-name").length === 16);

  const busan = await measure(page, "busan");
  const busanOverlaps = overlapPairs(busan.labels);
  invariant(busan.document.scrollWidth <= busan.document.clientWidth + 1, `${name} 부산 horizontal overflow`);
  invariant(busan.busanPaths === 16, `${name} 부산 path count ${busan.busanPaths}`);
  invariant(busan.labels.length === 16, `${name} 부산 label count ${busan.labels.length}`);
  if (expectCrop) {
    invariant(busanOverlaps.length === 0, `${name} 부산 label overlaps: ${JSON.stringify(busanOverlaps)}`);
  }
  await card.screenshot({ path: path.join(workDir, `${prefix}-${name}-busan.png`) });

  return {
    national: { ...national, overlaps: nationalOverlaps, jejuTooltip },
    busan: { ...busan, overlaps: busanOverlaps },
  };
}

(async () => {
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  try {
    const metrics = {
      baseUrl,
      expectCrop,
      desktop: await captureScenario(browser, "desktop", { width: 1440, height: 1000 }),
      mobile: await captureScenario(browser, "mobile", { width: 390, height: 844 }),
    };
    fs.writeFileSync(path.join(workDir, `${prefix}-layout-metrics.json`), JSON.stringify(metrics, null, 2));
    console.log(JSON.stringify({
      baseUrl,
      prefix,
      expectCrop,
      desktopNationalOverlaps: metrics.desktop.national.overlaps,
      desktopBusanOverlaps: metrics.desktop.busan.overlaps,
      mobileNationalOverlaps: metrics.mobile.national.overlaps,
      mobileBusanOverlaps: metrics.mobile.busan.overlaps,
      desktopCardWidth: metrics.desktop.national.card.width,
      desktopStageWidth: metrics.desktop.national.stage.width,
      desktopViewBox: metrics.desktop.national.crop?.viewBox,
      omittedIslandSubpaths: metrics.desktop.national.crop?.omittedIslandSubpaths,
      desktopJejuTooltip: metrics.desktop.national.jejuTooltip,
      mobileScrollWidth: metrics.mobile.busan.document.scrollWidth,
    }, null, 2));
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
