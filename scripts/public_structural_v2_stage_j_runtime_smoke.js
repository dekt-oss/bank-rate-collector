const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("@playwright/test");

const baseUrl = process.env.STRATEGY_PREVIEW_BASE_URL || "http://127.0.0.1:4173";
const workDir = path.resolve("work");
fs.mkdirSync(workDir, { recursive: true });

const MARKET_CONFIG = {
  version: "public-structural-v2-market-position-v1",
  rate_normalization_decimals: 4,
  counterfactual: "replace_anchor_product",
  top10_share: 0.10,
  top25_share: 0.25,
  crowding_windows_pp: [0.05, 0.10],
};
const OUR_INSTITUTION = "고려저축은행";
const ECONOMICS_RADIUS_PP = 0.15;
const MIN_DENSE_TIE_COMPETITORS = 3;

function invariant(condition, message) {
  if (!condition) throw new Error(message);
}

function closeEnough(left, right, tolerance = 1e-9) {
  return Math.abs(Number(left) - Number(right)) <= tolerance;
}

function percentileCutoff(values, share) {
  const ordered = [...values].sort((a, b) => b - a);
  return ordered[Math.max(1, Math.ceil(ordered.length * share)) - 1];
}

function median(values) {
  const ordered = [...values].sort((a, b) => a - b);
  const mid = Math.floor(ordered.length / 2);
  return ordered.length % 2 ? ordered[mid] : (ordered[mid - 1] + ordered[mid]) / 2;
}

function manualPosition(marketRows, anchorId, currentRate, proposalRate) {
  const normalized = marketRows.map((row) => ({
    product_id: row.product_id,
    rate: Number(Number(row.rate).toFixed(4)),
  }));
  const anchorRows = normalized.filter((row) => row.product_id === anchorId);
  invariant(anchorRows.length === 1, `manual anchor count ${anchorRows.length}`);
  invariant(closeEnough(anchorRows[0].rate, currentRate), "manual anchor rate mismatch");
  const proposal = Number(Number(proposalRate).toFixed(4));
  const competitors = normalized.filter((row) => row.product_id !== anchorId);
  const peerRates = competitors.map((row) => row.rate);
  const counterfactual = [...peerRates, proposal];
  const higher = peerRates.filter((rate) => rate > proposal).length;
  const ties = peerRates.filter((rate) => rate === proposal).length;
  return {
    universe_count: counterfactual.length,
    rank_best: higher + 1,
    rank_worst: higher + ties + 1,
    tie_competitor_count: ties,
    top10_cutoff: percentileCutoff(counterfactual, 0.10),
    top25_cutoff: percentileCutoff(counterfactual, 0.25),
    median_rate: median(counterfactual),
    market_max_rate: Math.max(...counterfactual),
    within_5bp_count: peerRates.filter((rate) => Math.abs(rate - proposal) <= 0.05 + 1e-12).length,
  };
}

function rankText(position) {
  return position.rank_best === position.rank_worst
    ? `${position.rank_best}위 / ${position.universe_count}개`
    : `${position.rank_best}~${position.rank_worst}위 / ${position.universe_count}개`;
}

async function waitForCockpit(page) {
  await page.route("**/favicon.ico", (route) => route.fulfill({ status: 204, body: "" }));
  const response = await page.goto(`${baseUrl}/strategy.html`, { waitUntil: "networkidle" });
  invariant(response && response.ok(), `strategy.html HTTP ${response ? response.status() : "no response"}`);
  await page.waitForFunction(
    () => Boolean(document.getElementById("public-structural-v2-cockpit")?.textContent.includes("실제 시장 위치")),
    null,
    { timeout: 30_000 },
  );
  await page.waitForFunction(
    () => Boolean(globalThis.PublicStructuralV2MarketPosition?.marketPosition),
    null,
    { timeout: 10_000 },
  );
}

async function chooseActualDenseTie(page) {
  const fixture = await page.evaluate(({ institution }) => {
    const dataNode = document.getElementById("rate-monitor-data");
    if (!dataNode) throw new Error("rate-monitor-data:missing");
    const data = JSON.parse(String(dataNode.textContent || "").replace(/<\\\//g, "</"));
    return fetch(data.table_url, { cache: "no-store" })
      .then((response) => {
        if (!response.ok) throw new Error(`strategy-table:http_${response.status}`);
        return response.json();
      })
      .then((table) => {
        const columns = table.columns || [];
        const index = Object.fromEntries(columns.map((name, i) => [name, i]));
        const decode = (column, value) => {
          const lookup = table.lookups?.[column];
          return lookup && value !== null && value !== undefined ? lookup[value] : value;
        };
        const get = (row, name) => name in index ? decode(name, row[index[name]]) : null;
        const rows = (table.rows || []).map((row) => ({
          sector: get(row, "sector"),
          product_type: get(row, "product_type"),
          term_months: Number(get(row, "term_months")),
          max_rate: Number(get(row, "max_rate")),
          product_id: String(get(row, "product_id") ?? ""),
          institution: String(get(row, "institution") ?? ""),
          product: String(get(row, "product") ?? ""),
          source_effective_at: String(get(row, "source_effective_at") ?? ""),
        })).filter((row) => Number.isFinite(row.max_rate));

        const aggregate = (term) => {
          const map = new Map();
          for (const row of rows) {
            if (row.sector !== "savings_bank" || row.product_type !== "term_deposit" ||
                row.term_months !== term || !row.product_id) continue;
            const key = `${row.sector}\0${row.product_id}\0${term}`;
            const old = map.get(key);
            if (!old || row.max_rate > old.max_rate ||
                (row.max_rate === old.max_rate && row.source_effective_at > old.source_effective_at)) {
              map.set(key, row);
            }
          }
          return [...map.values()];
        };

        const terms = [...new Set(rows.filter((row) => row.sector === "savings_bank" &&
          row.product_type === "term_deposit").map((row) => row.term_months))]
          .filter((term) => [6, 12, 24, 36].includes(term));
        const candidates = [];
        for (const term of terms) {
          const products = aggregate(term);
          const anchor = products.filter((row) => row.institution === institution)
            .sort((a, b) => b.max_rate - a.max_rate || a.product_id.localeCompare(b.product_id))[0];
          if (!anchor) continue;
          const anchorId = `${anchor.sector}:${anchor.product_id}`;
          const marketRows = products.map((row) => ({
            product_id: `${row.sector}:${row.product_id}`,
            rate: Number(Number(row.max_rate).toFixed(4)),
          }));
          const peers = marketRows.filter((row) => row.product_id !== anchorId);
          const groups = new Map();
          for (const row of peers) {
            const rate = Number(Number(row.rate).toFixed(4));
            if (Math.abs(rate * 100 - Math.round(rate * 100)) > 1e-9) continue;
            groups.set(rate, (groups.get(rate) || 0) + 1);
          }
          for (const [rate, count] of groups.entries()) {
            candidates.push({
              term,
              dense_rate: rate,
              dense_tie_competitors: count,
              current_rate: Number(Number(anchor.max_rate).toFixed(4)),
              anchor_id: anchorId,
              market_rows: marketRows,
            });
          }
        }
        candidates.sort((a, b) =>
          b.dense_tie_competitors - a.dense_tie_competitors ||
          a.term - b.term || b.dense_rate - a.dense_rate,
        );
        if (!candidates.length) throw new Error("actual dense-tie candidate를 찾지 못함");
        return candidates[0];
      });
  }, { institution: OUR_INSTITUTION });

  invariant(
    fixture.dense_tie_competitors >= MIN_DENSE_TIE_COMPETITORS,
    `actual dense tie가 충분하지 않음: ${fixture.dense_tie_competitors}`,
  );
  invariant(fixture.market_rows.length >= 2, "actual market universe가 비정상적으로 작음");

  await page.locator('[data-market-mode="savings_bank"]').click();
  const termButton = page.locator(`#term-segment button[data-term="${fixture.term}"]`);
  invariant(await termButton.count() === 1, `term ${fixture.term} button 없음`);
  await termButton.click();

  const engine = await page.evaluate(({ fixture, config }) => {
    const api = globalThis.PublicStructuralV2MarketPosition;
    const dense = api.marketPosition({
      rows: fixture.market_rows,
      anchor_product_id: fixture.anchor_id,
      current_own_rate: fixture.current_rate,
      proposal_rate: fixture.dense_rate,
    }, config);
    const self = api.marketPosition({
      rows: fixture.market_rows,
      anchor_product_id: fixture.anchor_id,
      current_own_rate: fixture.current_rate,
      proposal_rate: fixture.current_rate,
    }, config);
    return { dense, self };
  }, { fixture, config: MARKET_CONFIG });

  const manualDense = manualPosition(
    fixture.market_rows,
    fixture.anchor_id,
    fixture.current_rate,
    fixture.dense_rate,
  );
  const manualSelf = manualPosition(
    fixture.market_rows,
    fixture.anchor_id,
    fixture.current_rate,
    fixture.current_rate,
  );

  for (const key of [
    "universe_count", "rank_best", "rank_worst", "tie_competitor_count",
    "top10_cutoff", "top25_cutoff", "median_rate", "market_max_rate", "within_5bp_count",
  ]) {
    invariant(closeEnough(engine.dense[key], manualDense[key]), `dense handcalc mismatch ${key}: ${engine.dense[key]} vs ${manualDense[key]}`);
  }
  for (const key of ["universe_count", "rank_best", "rank_worst", "tie_competitor_count"]) {
    invariant(closeEnough(engine.self[key], manualSelf[key]), `self replacement mismatch ${key}`);
  }
  invariant(engine.self.universe_count === fixture.market_rows.length, "anchor replacement가 universe N을 바꿈");
  invariant(
    engine.self.tie_competitor_count === manualSelf.tie_competitor_count,
    "anchor self-count가 tie에 포함됨",
  );

  await page.locator("#base-n").fill(Number(fixture.dense_rate).toFixed(2));
  await page.locator("#bonus-n").fill("0.00");
  await page.waitForFunction(
    (expected) => document.querySelector("#public-structural-v2-cockpit .psv2-card strong")?.textContent?.trim() === expected,
    `${Number(fixture.dense_rate).toFixed(2)}%`,
    { timeout: 10_000 },
  );

  const marketCard = page.locator("#public-structural-v2-cockpit .psv2-card.market");
  invariant(await marketCard.isVisible(), "market position card가 보이지 않음");
  const uiRank = (await marketCard.locator("strong.green").textContent()).trim();
  invariant(uiRank === rankText(manualDense), `UI rank mismatch: ${uiRank} vs ${rankText(manualDense)}`);
  const marketText = await marketCard.textContent();
  invariant(marketText.includes(`동률 ${manualDense.tie_competitor_count}개`), "UI dense tie count mismatch");
  invariant(marketText.includes(`TOP10 ${manualDense.top10_cutoff.toFixed(2)}%`), "UI TOP10 handcalc mismatch");

  return {
    term: fixture.term,
    dense_rate: fixture.dense_rate,
    dense_tie_competitors: fixture.dense_tie_competitors,
    universe_count: manualDense.universe_count,
    rank_best: manualDense.rank_best,
    rank_worst: manualDense.rank_worst,
    top10_cutoff: manualDense.top10_cutoff,
    top25_cutoff: manualDense.top25_cutoff,
    current_rate: fixture.current_rate,
    market_rows: fixture.market_rows,
    anchor_id: fixture.anchor_id,
  };
}

async function populateStructuralInputs(page) {
  await page.locator("#baseline-new").fill("100");
  await page.locator("#maturity-amount").fill("200");
  await page.locator("#rollover-rate").fill("60");
  await page.waitForFunction(
    () => {
      const cockpit = document.getElementById("public-structural-v2-cockpit");
      return Boolean(
        cockpit?.textContent.includes("Response Surface") &&
        cockpit?.querySelectorAll(".psv2-table tbody tr").length >= 2 &&
        cockpit?.querySelector(".psv2-chart"),
      );
    },
    null,
    { timeout: 10_000 },
  );
}

async function assertFixed5bpAndMarginalBoundary(page, actual) {
  const result = await page.evaluate(({ actual, config, radius }) => {
    const marketApi = globalThis.PublicStructuralV2MarketPosition;
    const decisionApi = globalThis.PublicStructuralV2DecisionContract;
    const position = marketApi.marketPosition({
      rows: actual.market_rows,
      anchor_product_id: actual.anchor_id,
      current_own_rate: actual.current_rate,
      proposal_rate: actual.dense_rate,
    }, config);
    const candidate = decisionApi.buildCandidateRateSets({
      current_rate: actual.current_rate,
      proposal_rate: actual.dense_rate,
      top25_cutoff: position.top25_cutoff,
      top10_cutoff: position.top10_cutoff,
      market_max_rate: position.market_max_rate,
      economics_min_rate: Math.max(0, actual.current_rate - radius),
      economics_max_rate: actual.current_rate + radius,
    });
    const tableRows = [...document.querySelectorAll("#public-structural-v2-cockpit .psv2-table tbody tr")]
      .map((row) => {
        const cells = [...row.querySelectorAll("td")];
        const rateText = row.querySelector(".rate-label")?.textContent || "";
        const rateMatch = rateText.match(/-?\d+(?:\.\d+)?/);
        return {
          rate: rateMatch ? Number(rateMatch[0]) : null,
          note: row.querySelector(".rate-note")?.textContent?.trim() || "",
          cost: cells[7]?.textContent?.trim() || "",
        };
      });
    return { candidate, tableRows, cockpitText: document.getElementById("public-structural-v2-cockpit")?.textContent || "" };
  }, { actual, config: MARKET_CONFIG, radius: ECONOMICS_RADIUS_PP });

  const grid = result.candidate.economics_grid.map(Number);
  invariant(grid.length >= 2, "actual economics grid가 2개 미만");
  for (let i = 1; i < grid.length; i += 1) {
    invariant(closeEnough(grid[i] - grid[i - 1], 0.05, 1e-8), `economics grid가 5bp 아님: ${grid[i - 1]} -> ${grid[i]}`);
  }

  const renderedRates = new Map(result.tableRows.filter((row) => Number.isFinite(row.rate)).map((row) => [row.rate.toFixed(2), row]));
  for (const rate of grid) {
    invariant(renderedRates.has(rate.toFixed(2)), `5bp grid rate ${rate.toFixed(2)}가 candidate table에 없음`);
  }

  const costRows = result.tableRows.filter((row) => row.cost && row.cost !== "—");
  invariant(costRows.length >= grid.length - 1, "fixed 5bp marginal 표면비용 행이 부족함");
  for (const row of costRows) {
    invariant(!/NaN|Infinity/i.test(row.cost), `marginal cost 비정상 값: ${row.cost}`);
    invariant(/억원/.test(row.cost), `marginal cost가 amount 단위가 아님: ${row.cost}`);
  }
  invariant(!result.cockpitText.includes("한계조달원가"), "uncalibrated denominator ratio가 UI에 노출됨");
  invariant(!result.cockpitText.includes("달성확률"), "probability 표현이 Cockpit에 노출됨");
  invariant(!/confidence interval|prediction interval/i.test(result.cockpitText), "통계구간으로 오해할 문구가 노출됨");
  invariant(result.cockpitText.includes("stress range"), "stress range 표현이 없음");
  invariant(result.cockpitText.includes("다음 5bp 표면비용"), "task-based 5bp 비용 진입점이 없음");

  return {
    economics_grid_count: grid.length,
    economics_grid_min: grid[0],
    economics_grid_max: grid[grid.length - 1],
    rendered_marginal_cost_rows: costRows.length,
    ratio_metric_exposed: false,
  };
}

async function assertNoHorizontalOverflow(page, label) {
  const metrics = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }));
  invariant(metrics.scrollWidth <= metrics.clientWidth + 1, `${label} horizontal overflow ${metrics.scrollWidth} > ${metrics.clientWidth}`);
  return metrics;
}

async function assertNoLabelCollisions(page, label) {
  const result = await page.evaluate(() => {
    const overlaps = (selector) => {
      const nodes = [...document.querySelectorAll(selector)].filter((node) => {
        const style = getComputedStyle(node);
        const rect = node.getBoundingClientRect();
        return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
      });
      const rects = nodes.map((node, index) => {
        const rect = node.getBoundingClientRect();
        return { index, text: node.textContent.trim(), left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom };
      });
      const collisions = [];
      for (let i = 0; i < rects.length; i += 1) {
        for (let j = i + 1; j < rects.length; j += 1) {
          const a = rects[i];
          const b = rects[j];
          const width = Math.min(a.right, b.right) - Math.max(a.left, b.left);
          const height = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
          if (width > 1 && height > 1) collisions.push([a.text, b.text]);
        }
      }
      return collisions;
    };
    const ladderLabels = overlaps("#public-structural-v2-cockpit .psv2-rung label");
    const ladderRates = overlaps("#public-structural-v2-cockpit .psv2-rung strong");
    const tableOverflow = [...document.querySelectorAll("#public-structural-v2-cockpit .psv2-table th, #public-structural-v2-cockpit .psv2-table td")]
      .filter((cell) => cell.scrollWidth > cell.clientWidth + 1)
      .map((cell) => cell.textContent.trim());
    const tooltipCount = document.querySelectorAll("#public-structural-v2-cockpit [title], #public-structural-v2-cockpit [data-tooltip]").length;
    return { ladderLabels, ladderRates, tableOverflow, tooltipCount };
  });
  invariant(result.ladderLabels.length === 0, `${label} ladder label collision ${JSON.stringify(result.ladderLabels)}`);
  invariant(result.ladderRates.length === 0, `${label} ladder rate collision ${JSON.stringify(result.ladderRates)}`);
  invariant(result.tableOverflow.length === 0, `${label} candidate text overflow ${JSON.stringify(result.tableOverflow)}`);
  return {
    ...result,
    tooltip_mode: result.tooltipCount ? "hover-elements-present" : "inline-no-hover-tooltip-dependency",
  };
}

async function assertTaskSmoke(page, label) {
  const cockpit = page.locator("#public-structural-v2-cockpit");
  const text = await cockpit.textContent();
  invariant(await cockpit.locator(".psv2-card.market").isVisible(), `${label}: 시장위치 task 실패`);
  invariant(text.includes("실제 시장 위치"), `${label}: factual label 없음`);
  invariant(text.includes("미보정 구조 시나리오"), `${label}: scenario label 없음`);
  invariant(text.includes("시장 사실 ≠ 수신금액의 직접 원인"), `${label}: factual/scenario 분리 문구 없음`);
  invariant(text.includes("다음 5bp 표면비용"), `${label}: 5bp 비용 task 실패`);
  invariant(text.includes("stress range"), `${label}: stress band task 실패`);
  invariant(!/confidence interval|prediction interval|달성확률/i.test(text), `${label}: stress band 오해 문구 있음`);
  return {
    market_position_visible: true,
    factual_scenario_separated: true,
    five_bp_cost_visible: true,
    stress_range_non_probability_wording: true,
  };
}

async function runViewport(browser, viewport, label, actualSeed = null) {
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  const runtimeErrors = [];
  page.on("pageerror", (error) => runtimeErrors.push(`pageerror: ${error.message}`));
  page.on("console", (message) => {
    if (message.type() === "error") runtimeErrors.push(`console: ${message.text()}`);
  });

  await waitForCockpit(page);
  const actual = actualSeed || await chooseActualDenseTie(page);
  if (actualSeed) {
    await page.locator('[data-market-mode="savings_bank"]').click();
    await page.locator(`#term-segment button[data-term="${actual.term}"]`).click();
    await page.locator("#base-n").fill(Number(actual.dense_rate).toFixed(2));
    await page.locator("#bonus-n").fill("0.00");
  }
  await populateStructuralInputs(page);
  const grid = await assertFixed5bpAndMarginalBoundary(page, actual);
  const overflow = await assertNoHorizontalOverflow(page, label);
  const collisions = await assertNoLabelCollisions(page, label);
  const tasks = await assertTaskSmoke(page, label);

  invariant(runtimeErrors.length === 0, `${label} browser runtime errors:\n${runtimeErrors.join("\n")}`);
  await page.locator("#public-structural-v2-cockpit").screenshot({
    path: path.join(workDir, `public-structural-v2-stage-j-${label}.png`),
  });
  await context.close();
  return { actual, grid, overflow, collisions, tasks };
}

(async () => {
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.CHROME_BIN || "/usr/bin/google-chrome",
    args: ["--no-sandbox", "--disable-dev-shm-usage"],
  });
  try {
    const desktop = await runViewport(browser, { width: 1280, height: 900 }, "desktop");
    const actualSeed = desktop.actual;
    const mobile = await runViewport(browser, { width: 390, height: 844 }, "mobile", actualSeed);
    const metrics = {
      version: "public-structural-v2-stage-j-runtime-v1",
      actual_market_spot_check: {
        term_months: actualSeed.term,
        dense_tie_rate_pct: actualSeed.dense_rate,
        dense_tie_competitors: actualSeed.dense_tie_competitors,
        universe_count: actualSeed.universe_count,
        rank_best: actualSeed.rank_best,
        rank_worst: actualSeed.rank_worst,
        top10_cutoff_pct: actualSeed.top10_cutoff,
        top25_cutoff_pct: actualSeed.top25_cutoff,
        self_replacement_checked: true,
        factual_handcalc_checked: true,
      },
      structural_grid: desktop.grid,
      viewports: {
        desktop: { overflow: desktop.overflow, collisions: desktop.collisions, tasks: desktop.tasks },
        mobile: { overflow: mobile.overflow, collisions: mobile.collisions, tasks: mobile.tasks },
      },
      release_gate: "verified_by_workflow_shell_off_build",
    };
    fs.writeFileSync(
      path.join(workDir, "public-structural-v2-stage-j-metrics.json"),
      JSON.stringify(metrics, null, 2) + "\n",
      "utf8",
    );
    console.log(`STAGE_J_METRICS=${JSON.stringify(metrics)}`);
  } finally {
    await browser.close();
  }
  console.log("Public Structural v2 Stage J runtime smoke passed");
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
