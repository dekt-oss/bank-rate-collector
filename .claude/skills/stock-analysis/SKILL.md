---
name: stock-analysis
metadata:
  version: "2.0"
description: Analyze a named listed stock or 특정 상장종목의 투자매력을 분석한다. Use for "종목 분석", "주가 분석", "살 만한가", "밸류에이션", "최근 이슈", "업데이트", "다시 봐줘" and equivalent English requests to analyze, value, update, or review a named public company or ticker. Supports initiation, update, event, and focused reviews covering valuation, forward revisions, business quality, catalysts, risks, technicals, flows, and shareholder returns. Do not use for market-only commentary, private-company analysis, or whole-portfolio construction without a specific listed security.
---

# Stock Analysis

Produce a source-grounded, repeatable equity analysis for one specified listed security. Separate company quality, valuation, and entry timing. Keep the core judgment objective and security-specific; add portfolio-fit commentary only when the user explicitly requests it.

## Default analytical frame

- Use a **12-month investment-attractiveness horizon** for the headline score unless the user specifies another horizon.
- Evaluate the **3-year structural thesis** separately so a strong long-term story does not automatically imply an attractive current entry.
- Use the primary listing and reporting currency unless the user requests an ADR, secondary listing, or another currency.
- Treat all scores as evidence summaries, not mechanical price forecasts.

## 1. Select the mode

Honor an explicit user request before any automatic decision.

- **Initiation mode**: First comprehensive review, “analyze from scratch,” or no reliable prior analysis is available.
- **Update mode**: A prior analysis or snapshot is available and the user asks to revisit, update, or check what changed.
- **Event mode**: The request centers on earnings, guidance, a transaction, regulation, product launch, capital raise, sharp price move, or another defined event.
- **Focused mode**: The user requests only valuation, earnings outlook, technicals, flows, shareholder return, news, one catalyst, or another bounded question.

Search only the current conversation and available project or attached files for a prior analysis. Do not claim a prior score or thesis unless it is actually found. If history is unavailable, use Initiation mode without asking the user to repeat information already present.

## 2. Resolve the security before analysis

Confirm:

1. Company name, ticker, exchange, and primary listing.
2. Reporting and trading currency.
3. Share class, ADR ratio, stock split, and material corporate-action adjustments when relevant.
4. Price timestamp: live, delayed, latest close, or another explicit reference point.

If the name is ambiguous, resolve it from context or current public sources. Ask only when materially different securities remain plausible.

## 3. Establish the evidence cutoff

Use current public information and available market-data, finance, research, filing, or browsing tools. Read [references/source-policy.md](references/source-policy.md) before collecting data.

Do not issue a current valuation or purchase-attractiveness score without a usable reference price. When current data access is unavailable, provide a clearly labeled analytical framework or stale-data review and omit the current score. Record this state in the snapshot as `reference_price.verified: false` with null value/timestamp, `overall_basis: price_unverified`, and `analysis_status: restricted` (pass `price_verified: false` to the score script).

Record separate dates for:

- reference price;
- latest reported financial period;
- consensus estimates;
- ownership or flow data;
- industry-size forecasts.

## 4. Load the sector playbook

Classify the company by its principal earnings engine, not only its exchange sector label. Read the relevant section of [references/sector-playbooks.md](references/sector-playbooks.md).

- Use sector-specific KPIs and valuation methods.
- Use a generic fallback only when no playbook fits.
- Do not force EV/EBITDA on banks or insurers, P/E on pre-revenue biotechnology, or headline spot earnings on highly cyclical commodity producers.
- If a conglomerate has multiple material engines, use a sum-of-the-parts frame when defensible.

## 5. Build the analytical chain

### A. Current market expectation

Infer what the current price appears to assume about growth, margins, capital intensity, risk, or terminal economics. Distinguish this inference from sourced facts. Quantify wherever the data allows, in this order of preference: (1) reverse DCF; (2) growth rate implied by the current multiple; (3) margin implied by the current price; (4) residual non-core value under a sum-of-the-parts; (5) implicit value assigned to a new business after deducting a conservative core-business value. If quantification is not reliably possible, state that explicitly instead of inventing an estimate.

### B. Business quality and financial resilience

Assess:

- revenue durability and customer concentration;
- pricing power and gross or operating margin structure;
- cash conversion and working-capital behavior;
- ROIC or an industry-appropriate return metric versus cost of capital;
- leverage, liquidity, refinancing, dilution, and off-balance-sheet obligations;
- accounting quality and the gap between reported, adjusted, and cash earnings.

### C. Forward outlook — build a quantified growth bridge (core deliverable)

This is the analytical center of the report. A narrative outlook without a driver-level bridge is not acceptable output.

Required, in this order:

1. **Decompose current revenue** into the units that actually generate it — segment, plant/site, product line, modality, or geography — with each unit's share of revenue and its price/volume driver.
2. **Build a forward bridge, driver by driver**, for the next 2-3 fiscal years: base revenue + each driver's incremental contribution = forecast revenue. Show the increments as numbers, and state which single driver carries the largest share of growth.
3. **Ground each material increment in evidence of its own**: the addressable market's size and CAGR (with source and forecast window), the capacity or technology that lets the company capture it, and the resulting implied share. State the arithmetic: industry size x CAGR x company share, or capacity x utilization x price.
4. **Cross-check the implied company CAGR against the industry CAGR.** Growing in line with the market means share is being held, not gained — say so explicitly, because it changes what can justify a premium multiple.
5. **Bridge revenue to profit**: margin path by year with the specific cost items that move it (labor, depreciation from new capacity, mix, FX), then to EPS including share count and dilution.
6. **Separate what the consensus model already contains from what it does not** (a recent acquisition, an unannounced plant, a pending contract) and quantify the unmodeled item separately, including its margin effect on the consolidated entity.

Where a number cannot be sourced, mark it `N/A` and say what it would take to fill it. Never fabricate a driver number to complete the bridge.

Measure revision direction over approximately 30 and 90 days when available.

Use the latest reported period and forward 1-2 fiscal years. Include the most decision-relevant estimates: revenue, operating profit or EBITDA, EPS, free cash flow, margins, and sector KPIs.

Measure revision direction over approximately 30 and 90 days when available. Report estimate dispersion and analyst coverage when material. Do not treat a stale target-price average as a substitute for earnings analysis.

### D. Valuation

Use at least two defensible methods when data permits:

1. sector-appropriate relative valuation against 2–5 economically comparable peers;
2. the company’s own historical range through a comparable cycle;
3. a scenario-based intrinsic or normalized valuation method when supportable.

Use the broad market multiple only as context, not as the principal comparator. Explain differences in growth, margins, balance sheet, cyclicality, geography, and accounting before declaring a discount or premium.

### E. Catalysts and structural thesis

For each major catalyst, trace:

`capability -> commercial product or capacity -> customer adoption -> revenue -> margin -> cash return`

State the current stage, expected timing, evidence, execution dependencies, and whether the market already prices it. For an industry growth claim, report forecast year, market definition, base year, endpoint, CAGR, and source date. Do not equate total addressable market with the company’s obtainable revenue.

### F. Industry, macro, and micro drivers

Create a sensitivity map for material variables such as rates, FX, commodity prices, regulation, inventory, capacity, demand, pricing, customer budgets, and competitive intensity. For each material driver state:

- direction of impact;
- transmission mechanism;
- likely lag;
- sensitivity: low, medium, or high;
- current environment.

Avoid double-counting the same factor in macro, outlook, catalysts, and risk scores.

### G. Technicals, flows, and positioning

Use the latest available price series. Assess trend, 20/60/120-day moving-average position, 52-week range, key support/resistance zones, volatility, gap risk, and overbought/oversold evidence when available.

For Korean stocks, assess foreign, institutional, and retail flows over relevant windows. For overseas stocks, use defensible proxies such as institutional ownership changes, short interest, options skew, ETF exposure, or fund positioning. State when data are lagged or unavailable.

### H. Capital allocation and shareholder return

Assess dividends, buybacks, cancellations, issuance, stock-based compensation, acquisitions, debt reduction, and reinvestment. Prefer net buyback yield and change in diluted share count over announced authorization alone.

### I. Risks and falsification

State:

- the strongest bear case;
- the most important assumption that could be wrong;
- measurable conditions that would weaken or invalidate the thesis;
- liquidity, governance, dilution, regulatory, technological, and cycle risks as applicable.

## 6. Construct bear, base, and bull scenarios

Use explicit operating assumptions and avoid pseudo-precision.

For each scenario include:

- revenue or sector KPI assumptions;
- margin or cash-flow assumptions;
- valuation method and multiple or discount rate;
- implied value or value range;
- upside or downside versus the reference price;
- key event that would make the scenario more likely.

Use a valuation range rather than a point target when uncertainty is high. Do not produce a scenario target when the available data cannot support one.

## 7. Score three separate questions

Read [references/scoring-rubric.md](references/scoring-rubric.md). Score components on a 0–10 scale using evidence anchors.

### Fundamental attractiveness

- valuation and scenario payoff: 25%
- earnings outlook and revisions: 20%
- business quality and financial resilience: 20%
- catalysts and monetization: 15%
- downside resilience and thesis risk: 15%
- capital allocation and shareholder return: 5%

### Entry timing

- technical setup: 40%
- flows and positioning: 30%
- event setup: 20%
- short-term sentiment: 10%

### Overall purchase attractiveness

Use:

`overall = fundamental attractiveness × 70% + entry timing × 30%`

Timing coverage gates apply: below 50% timing data coverage, do not produce an overall score (report the partial timing score as reference only); 50-69% caps the status at provisional. Use [scripts/calculate_scores.py](scripts/calculate_scores.py) when code execution is available. The script renormalizes missing components, reports coverage, and flags a provisional result. Otherwise calculate transparently and apply the same rules.

Use these labels:

- 8.5–10.0: very high attractiveness
- 7.0–8.4: positive / staged entry
- 5.5–6.9: neutral
- 4.0–5.4: low attractiveness
- below 4.0: very low attractiveness

Also report evidence confidence as A, B, C, or D. Never lower the investment score merely because data are missing, and never fabricate a score for a component without evidence — any component may be `N/A`. If a critical component (valuation, earnings outlook, business quality, downside resilience) is `N/A`, report the partial fundamental score, do not produce an overall score, set `analysis_status` to `insufficient_evidence`, and name each missing component with the reason it could not be scored. See the analysis-status table in the scoring rubric.

## 8. Write the mode-specific output

Read [references/output-templates.md](references/output-templates.md) and follow the applicable template. The analytical chain in section 5 is the working order; the written output follows the template's Part A (price/valuation/scenarios) → Part B (fundamentals) → Part C (timing) → Part D (conclusion) order, with a one-line bridge at the end of each Part.

If the user explicitly asked for an update but no prior analysis or snapshot was found, state in one line that no prior analysis was located and that Initiation mode is being used — do not silently switch modes.

Always lead with a fixed status block, then the judgment:

```
분석 모드 | 기준 주가·기준일 | 재무 기준(FY/최근 분기) | 컨센서스 기준일
펀더멘털 X.X/10 | 진입 타이밍 X.X/10 (또는 미산출) | 종합 X.X/10 — 등급 (또는 미산출 + 사유·누락 항목)
신뢰도 A-D | 데이터 커버리지 XX% | 분석 상태 (확정/잠정/부분/핵심 근거 부족/제한)
```

Then:

- one-sentence thesis;
- one positive factor, one negative factor, and the decisive variable.

Include a brief **“쉽게 말하면”** explanation after the expert conclusion. It must clarify the main judgment without introducing new facts.

For Initiation and Update modes, end with a compact **reanalyzable snapshot** containing the analysis date, reference price, three scores, confidence, core thesis, invalidation conditions, and 2–4 watchpoints. Use the schema in [references/analysis-snapshot-schema.json](references/analysis-snapshot-schema.json) only when the user asks for JSON or a writable project explicitly requires machine-readable state.

## 9. Apply quality control before answering

Verify all of the following:

- security identity and price date are explicit;
- reported, trailing, and forward figures are not mixed silently;
- peer comparisons are economically comparable;
- industry forecasts include definition and source date;
- facts, consensus, assumptions, and inference are visually distinguishable;
- each material numerical claim is sourced when browsing or connected research is used;
- positive and negative evidence are both represented;
- no risk is counted twice solely to force a lower score;
- the score matches the written thesis and scenarios;
- missing data lower confidence rather than being fabricated;
- Focused and Event modes do not expand into an unnecessary full report;
- the response ends with: `본 분석은 정보 제공 목적이며 투자 판단과 책임은 투자자 본인에게 있습니다.`
