const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("@playwright/test");

const baseUrl = process.env.SEARCH_BASELINE_BASE_URL || "http://127.0.0.1:4174";
const sourceSha = process.env.SEARCH_BASELINE_SOURCE_SHA || "unknown";
const workDir = path.resolve("work/search-baseline");
fs.mkdirSync(workDir, { recursive: true });

function invariant(condition, message) {
  if (!condition) throw new Error(message);
}

function cleanNumber(value) {
  return Number(String(value || "").replaceAll(",", "").replace(/[^0-9.-]/g, ""));
}

async function waitForRendered(page) {
  await page.waitForFunction(
    () => {
      const count = document.getElementById("count");
      const rows = document.querySelectorAll("#rows > tr:not(.skeleton)");
      return Boolean(count && count.textContent.trim() !== "—" && rows.length > 0);
    },
    null,
    { timeout: 45_000 },
  );
}

async function openSearch(page) {
  await page.route("**/favicon.ico", (route) => route.fulfill({ status: 204, body: "" }));
  const response = await page.goto(`${baseUrl}/index.html`, { waitUntil: "networkidle" });
  invariant(response && response.ok(), `index.html HTTP ${response ? response.status() : "no response"}`);
  await waitForRendered(page);
}

async function assertNoHorizontalOverflow(page, label) {
  const metrics = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
    bodyClientWidth: document.body.clientWidth,
    bodyScrollWidth: document.body.scrollWidth,
  }));
  invariant(
    metrics.scrollWidth <= metrics.clientWidth + 1,
    `${label} document horizontal overflow: ${metrics.scrollWidth} > ${metrics.clientWidth}`,
  );
  invariant(
    metrics.bodyScrollWidth <= metrics.bodyClientWidth + 1,
    `${label} body horizontal overflow: ${metrics.bodyScrollWidth} > ${metrics.bodyClientWidth}`,
  );
  return metrics;
}

async function groupState(page) {
  return page.evaluate(() => {
    const output = {};
    for (const input of document.querySelectorAll('input[type="checkbox"][data-group]')) {
      const key = input.dataset.group;
      if (!output[key]) output[key] = { total: 0, checked: 0, values: [], checkedValues: [] };
      output[key].total += 1;
      output[key].values.push(input.value);
      if (input.checked) {
        output[key].checked += 1;
        output[key].checkedValues.push(input.value);
      }
    }
    for (const item of Object.values(output)) {
      item.values.sort();
      item.checkedValues.sort();
    }
    return output;
  });
}

async function presetState(page) {
  return page.locator("#presets [data-preset]").evaluateAll((buttons) => buttons.map((button) => {
    const clone = button.cloneNode(true);
    clone.querySelectorAll(".n").forEach((node) => node.remove());
    return {
      id: button.dataset.preset,
      label: clone.textContent.trim().replace(/\s+/g, " "),
      countText: button.querySelector(".n")?.textContent.trim() || null,
      pressed: button.getAttribute("aria-pressed") === "true",
    };
  }));
}

async function chartState(page) {
  return page.evaluate(() => ({
    hidden: document.getElementById("charts")?.hidden ?? true,
    histogramChildren: document.getElementById("hist")?.children.length ?? 0,
    histogramAria: document.getElementById("hist")?.getAttribute("aria-label") || "",
    histogramBadge: document.getElementById("hist-badge")?.textContent.trim() || "",
    termChildren: document.getElementById("terms")?.children.length ?? 0,
    termBadge: document.getElementById("terms-badge")?.textContent.trim() || "",
    regionTiles: document.querySelectorAll("#reg .regtile").length,
    histogramCaption: document.getElementById("hist-cap")?.textContent.trim() || "",
    termCaption: document.getElementById("terms-cap")?.textContent.trim() || "",
    regionCaption: document.getElementById("reg-cap")?.textContent.trim() || "",
  }));
}

async function collectDefaultState(page, label) {
  const groups = await groupState(page);
  const presets = await presetState(page);
  const charts = await chartState(page);
  const overflow = await assertNoHorizontalOverflow(page, label);
  const countText = (await page.locator("#count").textContent()).trim();
  const resultCount = cleanNumber(countText);
  const visibleRows = await page.locator("#rows > tr:not(.detail)").count();
  const pinnedRows = await page.locator("#rows > tr.pinned").count();
  const shownValue = await page.locator("#shown").inputValue();
  const shownLimit = shownValue === "all" ? null : Number(shownValue);
  const bodyRows = Math.max(0, resultCount - pinnedRows);
  const expectedVisibleRows = Math.min(bodyRows, shownLimit == null ? bodyRows : shownLimit) + pinnedRows;
  const advancedHidden = await page.locator("#advanced-filters").isHidden();
  const filterToggleExpanded = await page.locator("#filter-toggle").getAttribute("aria-expanded");
  const basisText = (await page.locator("#basis").textContent()).trim().replace(/\s+/g, " ");
  const filterSummary = (await page.locator("#filter-mode-summary").textContent()).trim().replace(/\s+/g, " ");
  const defaultRegion = groups.region?.checkedValues || [];

  invariant(resultCount > 0, `${label}: default result count must be positive`);
  invariant(pinnedRows >= 0 && pinnedRows <= 1, `${label}: pinned row count changed: ${pinnedRows}`);
  invariant(
    visibleRows === expectedVisibleRows,
    `${label}: rendered rows ${visibleRows} != expected ${expectedVisibleRows} `
      + `(result=${resultCount}, shown=${shownValue}, pinned=${pinnedRows})`,
  );
  invariant(advancedHidden, `${label}: advanced filters should be collapsed by default`);
  invariant(filterToggleExpanded === "false", `${label}: advanced toggle aria-expanded must be false`);
  invariant(basisText.includes("최고금리(우대 포함)"), `${label}: highest-rate basis label missing`);
  invariant(filterSummary.includes("공시일 최근 30일"), `${label}: recent-30-day default summary missing`);
  invariant(
    JSON.stringify(defaultRegion) === JSON.stringify(["경기", "부산", "서울"]),
    `${label}: default regions changed: ${JSON.stringify(defaultRegion)}`,
  );

  for (const key of ["sector", "type", "term", "channel", "scope", "method", "prefStatus"]) {
    invariant(groups[key]?.total > 0, `${label}: group ${key} is missing`);
    invariant(
      groups[key].checked === groups[key].total,
      `${label}: group ${key} is not fully selected by default`,
    );
  }

  const expectedPresets = [
    ["sb-dep", "부산 저축은행 · 1년 정기예금"],
    ["sb-sav", "부산 저축은행 · 1년 적금"],
    ["mg-dep", "부산 상호금융 · 1년 정기예금"],
    ["mg-sav", "부산 상호금융 · 1년 적금"],
  ];
  invariant(presets.length === expectedPresets.length, `${label}: preset count changed: ${presets.length}`);
  expectedPresets.forEach(([id, expectedLabel], index) => {
    const actual = presets[index];
    invariant(actual.id === id, `${label}: preset ${index} id changed: ${actual.id}`);
    invariant(actual.label === expectedLabel, `${label}: preset ${id} label changed: ${actual.label}`);
    invariant(actual.pressed === false, `${label}: preset ${id} unexpectedly active at default`);
  });

  invariant(!charts.hidden, `${label}: charts are hidden after data load`);
  invariant(charts.histogramChildren > 0, `${label}: histogram did not render`);
  invariant(charts.termChildren > 0, `${label}: term-range chart did not render`);
  invariant(charts.regionTiles > 0, `${label}: region chart did not render`);

  const fields = await page.evaluate(() => ({
    q: document.getElementById("q")?.value || "",
    rmin: document.getElementById("rmin")?.value || "",
    tmin: document.getElementById("tmin")?.value || "",
    tmax: document.getElementById("tmax")?.value || "",
    dfrom: document.getElementById("dfrom")?.value || "",
    dto: document.getElementById("dto")?.value || "",
    hideZero: document.getElementById("hide-zero")?.checked || false,
    shown: document.getElementById("shown")?.value || "",
    mine: document.getElementById("mine")?.value || "",
    busanDetail: document.querySelector('[data-detail="gu"]')?.getAttribute("aria-expanded") || null,
    busanSelectedText: document.querySelector('[data-detail="gu"]')?.parentElement?.textContent.trim().replace(/\s+/g, " ") || null,
  }));
  invariant(
    fields.q === "" && fields.rmin === "" && fields.tmin === "" && fields.tmax === "",
    `${label}: scalar defaults changed`,
  );
  invariant(fields.dto === "", `${label}: default dto should be empty`);
  invariant(fields.dfrom !== "", `${label}: recent-30-day dfrom should be populated`);
  invariant(fields.hideZero === false, `${label}: hide-zero should be off by default`);
  invariant(fields.shown === "100", `${label}: shown default must be 100`);

  return {
    label,
    sourceSha,
    url: page.url(),
    resultCount,
    countText,
    visibleRows,
    pinnedRows,
    shownLimit,
    expectedVisibleRows,
    basisText,
    filterSummary,
    advancedHidden,
    filterToggleExpanded,
    groups,
    presets,
    charts,
    fields,
    overflow,
    firstRows: await page.locator("#rows > tr:not(.detail)").evaluateAll((rows) => rows.slice(0, 3).map((row) => row.textContent.trim().replace(/\s+/g, " "))),
  };
}

async function assertCurrentAllSemantics(page, label) {
  await page.locator("#reset").click();
  await page.waitForTimeout(100);

  const allButton = page.locator('[data-all="type"]');
  invariant((await allButton.textContent()).trim() === "전체 선택", `${label}: current all button label changed`);
  const before = await page.locator('input[data-group="type"]:checked').count();
  await allButton.click();
  const afterAllClick = await page.locator('input[data-group="type"]:checked').count();
  invariant(
    afterAllClick === before && before > 0,
    `${label}: current all button no longer idempotently selects all`,
  );

  const values = await page.locator('input[data-group="type"]').evaluateAll((nodes) => nodes.map((node) => node.value));
  for (const value of values) {
    const box = page.locator(`input[data-group="type"][value="${value}"]`);
    await box.uncheck();
  }
  const afterLastOff = await page.locator('input[data-group="type"]:checked').count();
  const total = await page.locator('input[data-group="type"]').count();
  invariant(
    afterLastOff === total,
    `${label}: current last-checkbox auto-recovery changed: ${afterLastOff}/${total}`,
  );

  return {
    allButtonLabel: (await page.locator('[data-all="type"]').textContent()).trim(),
    checkedBefore: before,
    checkedAfterAllClick: afterAllClick,
    checkedAfterLastUnchecked: afterLastOff,
    total,
    behavior: "all-button-selects-all-only; last-checkbox-off-auto-restores-all",
  };
}

async function assertUrlRoundTrip(page, label) {
  await page.locator("#reset").click();
  await page.locator("#tmin").fill("12");
  await page.locator("#tmax").fill("12");
  await page.waitForTimeout(350);
  await page.waitForFunction(() => {
    const p = new URLSearchParams(location.search);
    return p.get("tmin") === "12" && p.get("tmax") === "12";
  });

  const before = {
    url: page.url(),
    count: cleanNumber(await page.locator("#count").textContent()),
    histogramAria: await page.locator("#hist").getAttribute("aria-label"),
    termCaption: (await page.locator("#terms-cap").textContent()).trim(),
  };
  invariant(before.count > 0, `${label}: exact-12 URL exercise unexpectedly has zero rows`);

  await page.reload({ waitUntil: "networkidle" });
  await waitForRendered(page);
  const after = {
    url: page.url(),
    count: cleanNumber(await page.locator("#count").textContent()),
    tmin: await page.locator("#tmin").inputValue(),
    tmax: await page.locator("#tmax").inputValue(),
    histogramAria: await page.locator("#hist").getAttribute("aria-label"),
    termCaption: (await page.locator("#terms-cap").textContent()).trim(),
  };
  invariant(
    after.tmin === "12" && after.tmax === "12",
    `${label}: URL did not restore exact 12-month scalar fields`,
  );
  invariant(after.count === before.count, `${label}: URL round-trip count changed ${before.count} -> ${after.count}`);
  invariant(after.histogramAria === before.histogramAria, `${label}: URL round-trip histogram basis changed`);
  invariant(after.termCaption === before.termCaption, `${label}: URL round-trip term chart caption changed`);
  await assertNoHorizontalOverflow(page, `${label} exact-12 URL round-trip`);

  return { before, after };
}

async function runViewport(browser, label, viewport) {
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  const runtimeErrors = [];
  page.on("pageerror", (error) => runtimeErrors.push(`pageerror: ${error.message}`));
  page.on("console", (message) => {
    if (message.type() === "error") runtimeErrors.push(`console: ${message.text()}`);
  });

  await openSearch(page);
  const defaultState = await collectDefaultState(page, label);
  await page.screenshot({
    path: path.join(workDir, `search-baseline-${label}.png`),
    fullPage: true,
  });

  const allSemantics = await assertCurrentAllSemantics(page, label);
  const urlRoundTrip = await assertUrlRoundTrip(page, label);
  invariant(runtimeErrors.length === 0, `${label} browser runtime errors:\n${runtimeErrors.join("\n")}`);

  const evidence = {
    schema: "search-runtime-baseline-v1",
    capturedAt: new Date().toISOString(),
    sourceSha,
    viewport,
    defaultState,
    currentAllSemantics: allSemantics,
    exact12UrlRoundTrip: urlRoundTrip,
    runtimeErrors,
  };
  fs.writeFileSync(
    path.join(workDir, `search-baseline-${label}.json`),
    JSON.stringify(evidence, null, 2) + "\n",
    "utf8",
  );
  await context.close();
  return evidence;
}

(async () => {
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  try {
    const desktop = await runViewport(browser, "desktop-1440", { width: 1440, height: 1000 });
    const mobile = await runViewport(browser, "mobile-390", { width: 390, height: 844 });
    const summary = {
      schema: "search-runtime-baseline-summary-v1",
      sourceSha,
      desktop: {
        resultCount: desktop.defaultState.resultCount,
        visibleRows: desktop.defaultState.visibleRows,
        pinnedRows: desktop.defaultState.pinnedRows,
        presets: desktop.defaultState.presets,
        overflow: desktop.defaultState.overflow,
        exact12Count: desktop.exact12UrlRoundTrip.after.count,
      },
      mobile: {
        resultCount: mobile.defaultState.resultCount,
        visibleRows: mobile.defaultState.visibleRows,
        pinnedRows: mobile.defaultState.pinnedRows,
        presets: mobile.defaultState.presets,
        overflow: mobile.defaultState.overflow,
        exact12Count: mobile.exact12UrlRoundTrip.after.count,
      },
    };
    fs.writeFileSync(
      path.join(workDir, "search-baseline-summary.json"),
      JSON.stringify(summary, null, 2) + "\n",
      "utf8",
    );
    console.log(JSON.stringify(summary));
    console.log("search runtime baseline: PASS (desktop 1440px, mobile 390px)");
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error.stack || error.message || String(error));
  process.exit(1);
});
