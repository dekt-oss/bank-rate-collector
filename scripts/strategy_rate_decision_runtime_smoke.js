const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("@playwright/test");

const baseUrl = process.env.STRATEGY_PREVIEW_BASE_URL || "http://127.0.0.1:4173";
const workDir = path.resolve("work");
fs.mkdirSync(workDir, { recursive: true });

function invariant(condition, message) {
  if (!condition) throw new Error(message);
}

function numberFromText(text) {
  const match = String(text || "").replace(/,/g, "").match(/-?\d+(?:\.\d+)?/);
  return match ? Number(match[0]) : null;
}

async function ensureSimulatorVisible(page, label) {
  await page.route("**/favicon.ico", (route) => route.fulfill({ status: 204, body: "" }));
  const response = await page.goto(`${baseUrl}/strategy.html`, { waitUntil: "networkidle" });
  invariant(response && response.ok(), `${label}: strategy.html HTTP ${response ? response.status() : "no response"}`);
  const simulator = page.locator(".strategy-rate-decision-simulator");
  await simulator.waitFor({ state: "attached", timeout: 30_000 });
  const detail = page.locator("#lean-planning-detail");
  const toggle = page.locator("#prediction-toggle");
  invariant(await detail.isVisible(), `${label}: 금리설계 상세 disclosure가 보이지 않음`);
  invariant(await detail.evaluate((node) => node.open), `${label}: 금리설계 상세가 기본 펼침 상태가 아님`);
  invariant(await toggle.isVisible(), `${label}: 예측엔진 토글이 보이지 않음`);
  invariant((await toggle.getAttribute("aria-expanded")) === "true", `${label}: 예측엔진이 기본 expanded 상태가 아님`);
  await simulator.waitFor({ state: "visible", timeout: 10_000 });
  return simulator;
}

async function populateScenarioInputs(page) {
  await page.locator("#baseline-new").fill("100");
  await page.locator("#maturity-amount").fill("200");
  await page.locator("#rollover-rate").fill("60");
}

async function assertPrimaryFlow(page, simulator, label) {
  const text = await simulator.textContent();
  invariant(text.includes("금리결정 시뮬레이터"), `${label}: simulator 제목이 없음`);
  invariant(text.includes("금리 → 결과 계산"), `${label}: 금리 계산 mode가 없음`);
  invariant(text.includes("희망금액 → 금리 찾기"), `${label}: 희망금액 역산 mode가 없음`);
  invariant(text.includes("조건 입력") && text.includes("결과 출력"), `${label}: 입력/결과 구분이 없음`);
  invariant((await simulator.locator(".rds-input-panel").isVisible()), `${label}: 조건 입력 panel이 보이지 않음`);
  invariant((await simulator.locator(".rds-output-panel").isVisible()), `${label}: 결과 출력 panel이 보이지 않음`);
  invariant((await simulator.locator('[data-rds-enrollment="all"].active').count()) === 1, `${label}: 가입방식 기본값이 전체가 아님`);\n  invariant(await simulator.locator(".rds-rate-mode").isVisible(), `${label}: 금리 mode에서 검토금리 입력이 숨겨짐`);\n  invariant(await simulator.locator(".rds-target-mode").isHidden(), `${label}: 금리 mode에서 희망금액 입력이 함께 노출됨`);
  invariant(!text.includes("추천금리"), `${label}: 금지 표현 추천금리 노출`);
  invariant(!text.includes("최적금리"), `${label}: 금지 표현 최적금리 노출`);
  invariant(!text.includes("필요금리"), `${label}: 금지 표현 필요금리 노출`);

  const details = simulator.locator("details.rds-details");
  invariant((await details.count()) === 1, `${label}: 상세 분석 disclosure가 없음`);
  invariant(!(await details.evaluate((node) => node.open)), `${label}: legacy 상세 분석이 기본 펼침 상태임`);
  await page.waitForFunction(
    () => {
      const detail = document.querySelector("details.rds-details");
      const results = document.querySelector(".prediction-results");
      const response = document.querySelector(".rate-response-wrap");
      const cockpit = document.getElementById("public-structural-v2-cockpit");
      return Boolean(
        detail
        && results
        && response
        && cockpit
        && detail.contains(results)
        && detail.contains(response)
        && detail.contains(cockpit),
      );
    },
    null,
    { timeout: 10_000 },
  );
  invariant(await page.locator("#public-structural-v2-cockpit").isHidden(), `${label}: legacy cockpit이 primary로 노출됨`);
  invariant(await page.locator(".prediction-results").isHidden(), `${label}: legacy v1 결과가 primary로 노출됨`);
  invariant(await page.locator(".rate-response-wrap").isHidden(), `${label}: legacy scenario table이 primary로 노출됨`);

  await populateScenarioInputs(page);
  const rateInput = page.locator("#rds-review-rate");
  const proposalText = await page.locator("#sim-max").textContent();
  const proposal = numberFromText(proposalText);
  invariant(Number.isFinite(proposal), `${label}: 현재 제안금리를 읽지 못함`);
  await rateInput.fill(proposal.toFixed(2));
  await rateInput.dispatchEvent("change");

  await page.waitForFunction(
    () => {
      const total = document.getElementById("rds-total")?.textContent || "";
      const rank = document.getElementById("rds-rank")?.textContent || "";
      return total !== "—" && rank !== "—";
    },
    null,
    { timeout: 10_000 },
  );
  const totalText = await page.locator("#rds-total").textContent();
  const total = numberFromText(totalText);
  invariant(Number.isFinite(total), `${label}: rate mode 총수신이 계산되지 않음`);
  invariant((await page.locator("#rds-nearby").textContent()).trim().length > 0, `${label}: 주변 경쟁상품 결과가 비어 있음`);
  invariant(
    (await page.locator("#rds-nearby thead").textContent()).includes("업권"),
    `${label}: 주변 경쟁상품 표에 업권 열이 없음`,
  );

  const targetTab = page.locator('[data-rds-mode="target"]');
  await targetTab.click();
  invariant(await page.locator(".rds-target-mode").isVisible(), `${label}: 목표금액 입력이 보이지 않음`);\n  invariant(await page.locator(".rds-rate-mode").isHidden(), `${label}: 희망금액 mode에서 검토금리 입력이 함께 노출됨`);
  await page.waitForFunction(
    () => {
      const rank = document.getElementById("rds-rank")?.textContent || "";
      const nearby = document.getElementById("rds-nearby")?.textContent || "";
      const peers = document.getElementById("rds-peers")?.textContent || "";
      return rank === "—" && nearby.includes("계산이 차단") && peers.includes("계산이 차단");
    },
    null,
    { timeout: 10_000 },
  );
  const targetInput = page.locator("#rds-target-total");
  await targetInput.fill(String(Math.max(0, Math.floor(total))));
  await targetInput.dispatchEvent("change");
  await page.waitForFunction(
    () => {
      const note = document.getElementById("rds-rate-note")?.textContent || "";
      const rank = document.getElementById("rds-rank")?.textContent || "";
      return note.trim().length > 0 && rank !== "—";
    },
    null,
    { timeout: 10_000 },
  );
  const targetText = await simulator.textContent();
  invariant((await page.locator("#rds-rate-title").textContent()) === "추천 검토금리", `${label}: 목표금액 결과가 추천 검토금리로 표시되지 않음`);
  invariant((await page.locator("#rds-delta-title").textContent()) === "목표 대비", `${label}: 목표금액 결과가 목표 대비로 표시되지 않음`);
  invariant(targetText.includes("existing candidate") || targetText.includes("후보"), `${label}: 목표금액 bounded candidate 의미가 사라짐`);
  invariant(targetText.includes("보간/외삽/자동 최적화 아님"), `${label}: no-interpolation disclosure가 없음`);
}

async function assertNoHorizontalOverflow(page, label) {
  const metrics = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }));
  invariant(
    metrics.scrollWidth <= metrics.clientWidth + 1,
    `${label}: horizontal overflow ${metrics.scrollWidth} > ${metrics.clientWidth}`,
  );
}

async function runViewport(browser, viewport, label) {
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  const runtimeErrors = [];
  page.on("pageerror", (error) => runtimeErrors.push(`pageerror: ${error.message}`));
  page.on("console", (message) => {
    if (message.type() === "error") runtimeErrors.push(`console: ${message.text()}`);
  });

  const simulator = await ensureSimulatorVisible(page, label);
  await assertPrimaryFlow(page, simulator, label);
  await assertNoHorizontalOverflow(page, label);
  await simulator.screenshot({ path: path.join(workDir, `strategy-rate-decision-${label}.png`) });
  invariant(runtimeErrors.length === 0, `${label}: browser runtime errors:\n${runtimeErrors.join("\n")}`);
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
    process.stdout.write("Strategy Rate Decision Simulator render smoke passed\n");
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
