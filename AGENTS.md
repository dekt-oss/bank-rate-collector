# bank-rate-collector agent instructions

## Strategy production release policy

- Strategy dashboard is an established production surface. Canonical site-writer workflows keep `RATE_MONITOR_STRATEGY_DASHBOARD: "1"` and production tests enforce that contract.
- Do not describe Strategy production release as OFF based on historical handoff text or old conversation state. Repository workflow/test state is the source of truth.
- When the user explicitly authorizes a normal Strategy change to be merged, no second, separate "Release Gate ON" approval is required for the existing production writer to publish that merged Strategy code.
- Turning Strategy production publication OFF, removing `strategy.html`, or removing the Strategy navigation entry is a separate behavior change and requires explicit user approval.
- PR creation or merge is not runtime verification. For Strategy UI changes, use the existing production-data/preview browser E2E where applicable and report anything not verified.

## Financial/data safety

- Do not change prediction coefficients, source precedence, stable product identity, ranking populations, dedupe/identity rules, or persistent data contracts as a presentation cleanup unless the task explicitly requires it and the relevant evidence gate has been applied.
