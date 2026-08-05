# Source and Data Policy

## Purpose

Apply this policy whenever the stock-analysis skill needs current or externally verifiable facts. Prefer evidence quality over volume.

## Source hierarchy

Use the highest available level for each claim:

1. **Primary company and regulatory sources**: exchange filings, regulator filings, audited statements, earnings releases, investor presentations, official guidance, capital-return announcements.
2. **Official public data**: central banks, statistics agencies, ministries, exchanges, industry regulators, customs, energy or commodity agencies.
3. **Consensus and institutional research**: reputable consensus providers, broker research, rating-agency or industry-research publications. State whether figures are mean, median, or a single analyst estimate.
4. **Established financial journalism**: use for event chronology, quotations, and context; verify decisive financial figures against primary sources when possible.
5. **Aggregators and community sources**: use only as discovery aids, sentiment evidence, or a last resort. Do not use them as the sole support for earnings, valuation, market size, or capital structure.

## Freshness targets

Use these as targets, not excuses to invent unavailable data:

| Data | Preferred freshness |
|---|---|
| Price and technicals | live or latest market close |
| Korean investor flows | latest available session; aggregate 1/5/20/60 sessions as useful |
| Short interest and institutional holdings | latest published date; state reporting lag |
| Consensus | latest available snapshot; identify 30/90-day revision direction |
| Company financials | latest filed or officially released period |
| Industry size forecast | preferably published within 24 months; always state publication date |
| Macro variables | latest official release and applicable reference period |

## Data normalization

Before comparing figures, align:

- trading currency and reporting currency;
- fiscal years and calendar years;
- GAAP, IFRS, and adjusted/non-GAAP definitions;
- basic versus diluted shares;
- enterprise-value treatment of leases, pensions, associates, and minority interest when material;
- ADR or GDR conversion ratios;
- stock splits, rights issues, special dividends, and spin-offs;
- TTM, current fiscal year, next fiscal year, and NTM labels;
- reported results versus consensus estimates.

Never combine a current price with an old estimate without showing both dates.

## Security and price identity

State:

- company, ticker, exchange, share class;
- primary or secondary listing;
- price type: live, delayed, latest close, adjusted close;
- date, time, and timezone when available;
- market capitalization basis and diluted share count when relevant.

## Consensus rules

- Prefer a provider that reports analyst count and estimate date.
- Cross-check decisive forward figures with a second source when feasible.
- Report direction and magnitude of revisions, not only the latest point estimate.
- State dispersion when wide disagreement is itself material.
- Treat price targets as sentiment and valuation evidence, not ground truth.
- Do not average estimates that use incompatible fiscal periods or accounting definitions.

## Peer-selection rules

Select 2–5 peers based on the economics of the earnings engine:

- product and customer overlap;
- geography and regulatory regime;
- growth and margin profile;
- capital intensity and balance-sheet structure;
- cycle position;
- accounting comparability.

Explain why each peer belongs. Exclude a superficially similar peer when its economics are materially different. Use the broad market multiple only as background context.

## Industry forecast rules

For every market-size or CAGR claim, state:

- market definition and geographic scope;
- base-year value;
- endpoint-year value;
- CAGR and forecast window;
- nominal or real currency if known;
- publication date and source type.

When reputable forecasts diverge, show a range and explain the definitional difference. Never convert TAM directly into company revenue without adoption, share, capacity, pricing, and timing assumptions.

## Technical and positioning data

- Adjust price history for splits and distributions when appropriate.
- Avoid false precision in support and resistance; use zones.
- State whether flows are daily, weekly, monthly, gross, or net.
- State reporting lags for 13F, short interest, options, insider transactions, and fund holdings.
- Do not call a single day of buying a durable flow trend.

## Conflicts and missing data

When sources conflict:

1. compare dates, definitions, and revision timestamps;
2. prefer the latest primary source for reported facts;
3. preserve the disagreement when it cannot be reconciled;
4. explain which figure is used and why.

Use `N/A` for unavailable facts. Do not transform missing evidence into a negative investment score. Reflect missingness in the coverage and confidence assessment.

## Citation discipline

When tools support citations, cite each load-bearing factual paragraph near the claim. Separate:

- **Fact**: directly supported by a source;
- **Consensus**: aggregated external estimate;
- **Assumption**: analyst-created input;
- **Inference**: conclusion derived from multiple facts.
