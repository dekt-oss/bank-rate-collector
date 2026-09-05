const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("@playwright/test");

const baseUrl = process.env.STRATEGY_PREVIEW_BASE_URL || "http://127.0.0.1:4173";
const workDir = path.resolve("work");
fs.mkdirSync(workDir, { recursive: true });

function invariant(condition, message) {
  if (!condition) throw new Error(message);
}

async function waitForCockpit(page) {
  await page.route("**/favicon.ico", (route) => route.fulfill({ status: 204, body: "" }));
  const response = await page.goto(`${baseUrl}/strategy.html`, { waitUntil: "networkidle" });
  invariant(response && response.ok(), `strategy.html HTTP ${response ? response.status() : "no response"}`);
  await page.waitForFunction(
    () => {
      const cockpit = document.getElementById("public-structural-v2-cockpit");
      return Boolean(cockpit && cockpit.textContent.includes("실제 시장 위치"));
    },
    null,
    { timeout: 30_000 },
  );
}

async function ensurePredictionPanelVisible(page, label) {
  const cockpit = page.locator("#public-structural-v2-cockpit");
  if (await cockpit.isVisible()) return cockpit;

  const legacyDetails = page.locator("details.rds-details");
  if (await legacyDetails.count()) {
    const ownsCockpit = await legacyDetails.evaluate((details) => Boolean(
      details.querySelector("#public-structural-v2-cockpit"),
    ));
    if (ownsCockpit) {
      await legacyDetails.evaluate((details) => { details.open = true; });
      await cockpit.waitFor({ state: "visible", timeout: 10_000 });
      return cockpit;
    }
  }

  const toggle = page.locator("#prediction-toggle");
  invariant(await toggle.isVisible(), `${label}: 예측엔진 열기 버튼이 보이지 않음`);
  if (await toggle.getAttribute("aria-expanded") !== "true") await toggle.click();
  await cockpit.waitFor({ state: "visible", timeout: 10_000 });
  return cockpit;
}

async function assertNoHorizontalOverflow(page, label) {
  const metrics = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }));
  invariant(
    metrics.scrollWidth <= metrics.clientWidth + 1,
    `${label} horizontal overflow: ${metrics.scrollWidth} > ${metrics.clientWidth}`,
  );
}

async function assertUniqueLadderRates(cockpit, label) {
  const duplicates = await cockpit.locator(".psv2-rung").evaluateAll((nodes) => {
    const rates = nodes.map((node) => node.querySelector("strong")?.textContent?.trim()).filter(Boolean);
    return rates.filter((rate, index) => rates.indexOf(rate) !== index);
  });
  invariant(duplicates.length === 0, `${label}: Ladder 동일금리 marker 중복 ${JSON.stringify(duplicates)}`);
}

async function assertCandidateTableVisualSpace(cockpit, viewport, label) {
  const metrics = await cockpit.locator(".psv2-table-wrap").evaluate((wrapper) => {
    const table = wrapper.querySelector(".psv2-table");
    const head = wrapper.querySelector("thead");
    const body = wrapper.querySelector("tbody");
    const firstRow = wrapper.querySelector("tbody tr");
    const cells = firstRow ? [...firstRow.querySelectorAll("td")] : [];
    const overflowingCells = [...wrapper.querySelectorAll("th,td")]
      .filter((cell) => cell.scrollWidth > cell.clientWidth + 1)
      .map((cell) => cell.textContent.trim());
    const rects = cells.map((cell, index) => {
      const rect = cell.getBoundingClientRect();
      return { index, left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom };
    });
    const overlaps = [];
    for (let i = 0; i < rects.length; i += 1) {
      for (let j = i + 1; j < rects.length; j += 1) {
        const a = rects[i];
        const b = rects[j];
        const width = Math.min(a.right, b.right) - Math.max(a.left, b.left);
        const height = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
        if (width > 1 && height > 1) overlaps.push([a.index + 1, b.index + 1]);
      }
    }
    return {
      wrapperClientWidth: wrapper.clientWidth,
      wrapperScrollWidth: wrapper.scrollWidth,
      tableWidth: table?.getBoundingClientRect().width || 0,
      headDisplay: head ? getComputedStyle(head).display : null,
      bodyDisplay: body ? getComputedStyle(body).display : null,
      rowDisplay: firstRow ? getComputedStyle(firstRow).display : null,
      cellDisplays: cells.map((cell) => getComputedStyle(cell).display),
      firstRowHeight: firstRow?.getBoundingClientRect().height || 0,
      cellCount: cells.length,
      overflowingCells,
      overlaps,
    };
  });
  invariant(metrics.overflowingCells.length === 0, `${label}: 후보금리 cell text overflow ${JSON.stringify(metrics.overflowingCells)}`);
  invariant(metrics.overlaps.length === 0, `${label}: 후보금리 cell box overlap ${JSON.stringify(metrics.overlaps)}`);
  if (viewport.width <= 520) {
    invariant(metrics.cellCount === 8, `${label}: mobile 후보금리 카드 cell 수 ${metrics.cellCount}`);
    invariant(metrics.headDisplay === "none", `${label}: mobile 후보금리 header가 숨겨지지 않음`);
    invariant(metrics.bodyDisplay === "grid", `${label}: mobile 후보금리 tbody가 grid가 아님`);
    invariant(metrics.rowDisplay === "grid", `${label}: mobile 후보금리 row가 grid가 아님`);
    invariant(metrics.cellDisplays.every((display) => display === "block"), `${label}: mobile 후보금리 cell이 block이 아님`);
    invariant(metrics.tableWidth <= metrics.wrapperClientWidth + 1, `${label}: mobile 후보금리 카드가 wrapper보다 넓음`);
    invariant(metrics.wrapperScrollWidth <= metrics.wrapperClientWidth + 1, `${label}: mobile 후보금리 카드에 불필요한 가로스크롤이 남음`);
    invariant(metrics.firstRowHeight >= 100, `${label}: mobile 후보금리 카드 높이가 비정상 ${metrics.firstRowHeight}`);
  }
}

async function waitForFactualFinder(page, label) {
  await page.waitForFunction(
    () => {
      const finder = document.getElementById("public-structural-v2-factual-rate-finder");
      return Boolean(
        finder
        && finder.dataset.finderSignature
        && finder.querySelectorAll(".psv2-finder-item").length === 6,
      );
    },
    null,
    { timeout: 10_000 },
  );
  const finder = page.locator("#public-structural-v2-factual-rate-finder");
  invariant(await finder.isVisible(), `${label}: Stage G factual finder가 보이지 않음`);
  const text = await finder.textContent();
  invariant(text.includes("시장조건 충족 금리"), `${label}: Stage G 제목이 없음`);
  invariant(text.includes("조건충족 값 · 자동 결정 아님"), `${label}: 자동결정 금지 문구가 없음`);
  invariant(text.includes("상위 10% 진입선 도달"), `${label}: TOP10 도달 조건이 없음`);
  invariant(text.includes("상위 10% 진입선 초과"), `${label}: TOP10 초과 조건이 없음`);
  invariant(text.includes("상위 25% 진입선 도달"), `${label}: TOP25 도달 조건이 없음`);
  invariant(text.includes("상위 25% 진입선 초과"), `${label}: TOP25 초과 조건이 없음`);
  invariant(text.includes("시장 최고 동률"), `${label}: 시장 최고 동률 조건이 없음`);
  invariant(text.includes("시장 최고 초과"), `${label}: 시장 최고 초과 조건이 없음`);
  invariant(text.includes("competitor-only"), `${label}: competitor-only 기준 설명이 없음`);
  invariant(text.includes("1bp"), `${label}: UI 선택단위 설명이 없음`);
  ["억원", "달성확률", "추천금리", "최적금리", "beta", "gamma"].forEach((forbidden) => {
    invariant(!text.includes(forbidden), `${label}: factual finder에 금지 표현 ${forbidden} 유입`);
  });
  return finder;
}

async function assertSyntheticOffGridMeaning(page, label) {
  const result = await page.evaluate(() => {
    const output = PublicStructuralV2FactualRateFinder.factualRateConstraints({
      rows: [
        { product_id: "anchor", rate: 3.5 },
        { product_id: "p1", rate: 3.8015 },
        { product_id: "p2", rate: 3.7 },
      ],
      anchor_product_id: "anchor",
      current_own_rate: 3.5,
      selection_step_pp: 0.01,
    });
    return {
      tie: output.conditions.find((row) => row.target === "market_max" && row.relation === "tie"),
      exceed: output.conditions.find((row) => row.target === "market_max" && row.relation === "exceed"),
    };
  });
  invariant(result.tie.status === "unavailable", `${label}: off-grid 시장 최고 동률이 ready로 오판됨`);
  invariant(result.tie.benchmark_rate_pct === 3.8015, `${label}: off-grid benchmark 정밀도 손실`);
  invariant(result.tie.reason === "exact_tie_not_selectable_on_ui_grid", `${label}: off-grid unavailable reason 손실`);
  invariant(result.exceed.minimum_selectable_rate_pct === 3.81, `${label}: off-grid 시장 최고 초과 최소금리 오류`);
}

async function assertFinderProposalIndependence(page, finder, label) {
  const beforeSignature = await finder.getAttribute("data-finder-signature");
  const beforeProposal = await page.locator("#sim-max").textContent();
  const base = page.locator("#base-n");
  const baseValue = Number(await base.inputValue());
  invariant(Number.isFinite(baseValue), `${label}: 기본금리 입력값을 읽지 못함`);
  await base.fill((baseValue + 0.01).toFixed(2));
  await page.waitForFunction(
    (previous) => document.getElementById("sim-max")?.textContent !== previous,
    beforeProposal,
    { timeout: 5_000 },
  );
  await page.waitForFunction(
    () => Boolean(document.getElementById("public-structural-v2-factual-rate-finder")?.dataset.finderSignature),
    null,
    { timeout: 5_000 },
  );
  const afterSignature = await page.locator("#public-structural-v2-factual-rate-finder").getAttribute("data-finder-signature");
  invariant(afterSignature === beforeSignature, `${label}: 제안금리 변경이 competitor-only finder benchmark를 움직임`);
}

async function populateStructuralInputs(page) {
  await page.locator("#baseline-new").fill("100");
  await page.locator("#maturity-amount").fill("200");
  await page.locator("#rollover-rate").fill("60");
  await page.waitForFunction(
    () => {
      const panel = document.getElementById("prediction-panel");
      const cockpit = document.getElementById("public-structural-v2-cockpit");
      return Boolean(
        panel?.classList.contains("psv2-active")
        && cockpit?.textContent.includes("Response Surface")
        && cockpit?.textContent.includes("후보금리 비교"),
      );
    },
    null,
    { timeout: 10_000 },
  );
  await page.waitForFunction(
    () => {
      const rates = [...document.querySelectorAll("#public-structural-v2-cockpit .psv2-rung strong")]
        .map((node) => node.textContent.trim());
      return new Set(rates).size === rates.length;
    },
    null,
    { timeout: 5_000 },
  );
}

async function assertLegacySurfacesAreNotPrimary(page, label) {
  const placement = await page.evaluate(() => {
    const details = document.querySelector("details.rds-details");
    const inspect = (selector) => {
      const node = document.querySelector(selector);
      if (!node) return { exists: false, insideDetails: false, visible: false };
      const style = getComputedStyle(node);
      const rect = node.getBoundingClientRect();
      return {
        exists: true,
        insideDetails: Boolean(details?.contains(node)),
        visible: !node.hidden && style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0,
      };
    };
    return {
      predictionResults: inspect(".prediction-results"),
      rateResponse: inspect(".rate-response-wrap"),
    };
  });
  const predictionLeak = placement.predictionResults.exists
    && placement.predictionResults.visible
    && !placement.predictionResults.insideDetails;
  const rateResponseLeak = placement.rateResponse.exists
    && placement.rateResponse.visible
    && !placement.rateResponse.insideDetails;
  invariant(!predictionLeak, `${label}: v1 결과 카드가 상세분석 밖 primary에 남아 있음`);
  invariant(!rateResponseLeak, `${label}: 구형 scenario table이 상세분석 밖 primary에 남아 있음`);
}

async function runViewport(browser, viewport, label) {
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  const runtimeErrors = [];
  page.on("pageerror", (error) => runtimeErrors.push(`pageerror: ${error.message}`));
  page.on("console", (message) => {
    if (message.type() === "error") runtimeErrors.push(`console: ${message.text()}`);
  });

  await waitForCockpit(page);
  const cockpit = await ensurePredictionPanelVisible(page, label);
  invariant(await cockpit.isVisible(), `${label}: v2 Cockpit이 보이지 않음`);
  const marketOnlyText = await cockpit.textContent();
  invariant(marketOnlyText.includes("실제 시장 위치"), `${label}: 실제 시장 위치 카드가 없음`);
  invariant(marketOnlyText.includes("입력 3개 필요"), `${label}: 입력 전 scenario 경계가 없음`);
  invariant(marketOnlyText.includes("Market Position Ladder"), `${label}: Ladder가 없음`);
  invariant(!marketOnlyText.includes("추천금리"), `${label}: 금지된 추천금리 표현이 있음`);
  invariant(!marketOnlyText.includes("최적금리"), `${label}: 금지된 최적금리 표현이 있음`);
  await assertUniqueLadderRates(cockpit, `${label} market-only`);

  const finder = await waitForFactualFinder(page, label);
  const marketOnlySignature = await finder.getAttribute("data-finder-signature");
  await assertSyntheticOffGridMeaning(page, label);
  await assertFinderProposalIndependence(page, finder, label);

  await populateStructuralInputs(page);
  const fullText = await cockpit.textContent();
  invariant(fullText.includes("시장 사실 ≠ 수신금액의 직접 원인"), `${label}: 인과 경계 문구가 없음`);
  invariant(fullText.includes("stress range"), `${label}: stress range가 없음`);
  invariant(fullText.includes("직전 5bp 표면비용"), `${label}: 5bp 비용 비교가 없음`);
  invariant(await cockpit.locator(".psv2-chart").count() === 1, `${label}: Response Surface SVG가 없음`);
  invariant(await cockpit.locator(".psv2-table tbody tr").count() >= 2, `${label}: 후보금리 표가 비어 있음`);
  await assertLegacySurfacesAreNotPrimary(page, label);
  await assertUniqueLadderRates(cockpit, `${label} full`);
  await assertCandidateTableVisualSpace(cockpit, viewport, label);

  const fullFinder = await waitForFactualFinder(page, `${label} full`);
  const fullSignature = await fullFinder.getAttribute("data-finder-signature");
  invariant(fullSignature === marketOnlySignature, `${label}: 구조 시나리오 입력이 factual finder 결과를 움직임`);

  await assertNoHorizontalOverflow(page, label);
  await cockpit.screenshot({ path: path.join(workDir, `public-structural-v2-cockpit-${label}.png`) });
  invariant(runtimeErrors.length === 0, `${label} browser runtime errors:\n${runtimeErrors.join("\n")}`);
  await context.close();
}

(async () => {
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.CHROME_BIN || "/usr/bin/google-chrome",
    args: ["--no-sandbox", "--disable-dev-shm-usage"],
  });
  try {
    await runViewport(browser, { width: 1280, height: 900 }, "desktop");
    await runViewport(browser, { width: 390, height: 844 }, "mobile");
  } finally {
    await browser.close();
  }
  console.log("Public Structural v2 Cockpit runtime smoke passed");
})().catch((error) => {
  console.error(error);
  process.exit(1);
});