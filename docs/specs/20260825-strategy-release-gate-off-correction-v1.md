# Phase 4 — Strategy Release Gate OFF correction v1

## Status

- Scope: Phase 4 release-readiness corrective change only
- Ledger: GitHub Issue #205
- Base main at start: `23e0f6869ca924ea3d9b2c1023b7a6c70d18bc9d`
- `user_approved_release=false`
- Production Strategy Release Gate target: **OFF**

## Context

Phase 4 release-readiness recovery found a repository/runtime contract drift.

The current master plan and handoff require the Production Strategy Release Gate to remain OFF until a new explicit user approval. However, an earlier approved release in PR #150 intentionally pinned `RATE_MONITOR_STRATEGY_DASHBOARD: "1"` in every canonical `rate-data` writer. That historical release state remained in `main`, and the current `rate-data/site-public` manifest still contained `strategy.html` and the Strategy-only data slice.

This correction does not change Strategy functionality. It restores the current Phase 4 release boundary: Strategy code may remain implemented and testable, while canonical production publication stays OFF.

## Current state vs target state

### Current state before this correction

- `.github/workflows/collect.yml`: Strategy publish env = `"1"`
- `.github/workflows/collect-savings-fast.yml`: Strategy publish env = `"1"`
- `.github/workflows/nh-attempt.yml`: Strategy publish env = `"1"`
- canonical `rate-data/site-public` contains `strategy.html`
- production smoke expects Strategy to exist

### Target state

All canonical writers explicitly pin:

```yaml
RATE_MONITOR_STRATEGY_DASHBOARD: "0"
```

An OFF publication must have all of the following properties:

- no Strategy navigation in the search root
- no `strategy.html` in the canonical site manifest
- no `data/strategy-table.json`
- no `data/strategy-table.json.gz`
- public `/strategy.html` returns 404 or 410

A newer production generation is not allowed to bypass the Strategy-absence checks.

## Implementation scope

### 1. Canonical writer gate

The following three writers are pinned to explicit OFF:

- `.github/workflows/collect.yml`
- `.github/workflows/collect-savings-fast.yml`
- `.github/workflows/nh-attempt.yml`

Explicit `"0"` is used instead of relying on an omitted environment variable so the operational release state is visible and testable in repository source.

### 2. Production smoke becomes fail-closed for OFF

`scripts/production_smoke.py` validates:

- root operational markers still exist
- root does not expose `href="strategy.html"`
- expected canonical manifest contains no Strategy public files
- live production manifest contains no Strategy public files
- `/strategy.html` is absent with HTTP 404/410
- manifest freshness/size contracts remain intact
- `/api/health` read-only contract remains intact

If Strategy remains retrievable or appears in either manifest, the smoke fails as `content-mismatch`.

### 3. Strategy functionality remains independently testable

`.github/workflows/strategy-main-runtime-e2e.yml` continues to build an **isolated runner-local Strategy site** with:

```yaml
RATE_MONITOR_STRATEGY_DASHBOARD: "1"
```

That is intentional. The E2E proves the hidden feature remains buildable and runtime-valid against a runner-local restore of production data. It does not write production R2, publish `rate-data`, deploy Vercel, or constitute release approval.

The corrective branch family `fix/strategy-release-gate-*` and this specification are watched so the exact corrective head receives the production-data Strategy runtime test.

## Safety boundaries

This correction does **not** change:

- source precedence
- stable product identity
- 6D source-discrepancy comparison key
- payment-method ambiguity fail-closed policy
- canonical rate values
- official-evidence authority policy
- collector parsing or scheduling semantics
- DB schema or migrations
- Strategy calculations or prediction coefficients
- Search filter behavior
- Phase 5 backlog

No canonical source is overwritten and no authority is automatically selected.

## Pre-merge acceptance

The corrective PR may be considered implementation-valid only when:

- [ ] exact-head General CI succeeds
- [ ] Ruff succeeds
- [ ] full pytest succeeds
- [ ] empty-DB Alembic/model parity succeeds
- [ ] `tests/test_strategy_production_release.py` proves all three writers are OFF and no writer contains the ON env
- [ ] `tests/test_production_smoke.py` proves Strategy leakage is rejected
- [ ] exact-head production-data Strategy runtime E2E succeeds on desktop/mobile in isolated ON mode
- [ ] final PR diff contains no temporary patch helper/workflow
- [ ] no unrelated source/data/schema/product changes are present

### Expected pre-merge production-smoke behavior

The current official production publication was generated while the gate was ON. Therefore a PR-triggered production smoke using the new OFF checker may fail before merge because it is correctly detecting the still-public Strategy surface.

That failure is expected evidence of the current-state/target-state gap. It must **not** be weakened or reclassified as success merely to green the PR.

## Post-merge acceptance

Merging the corrective PR alone is not proof that production is OFF.

After an explicitly authorized merge, the following are required before `implementation_ready=true`:

1. main push/canonical publish writer completes successfully
2. resulting `rate-data/site-public/site-manifest.json` contains no Strategy file/slice
3. production root contains no Strategy navigation
4. production `/strategy.html` is absent (404/410)
5. production smoke using the OFF contract succeeds against the newly published manifest
6. rollback/disable path is thereby verified through the real canonical publication path

Until all six are verified, Issue #205 remains open and `implementation_ready=false`.

## Release approval boundary

Even after:

- `implementation_ready=true`
- `runtime_verified=true`
- `data_risk_reviewed=true`

`user_approved_release` remains **false** unless the user separately gives an explicit instruction equivalent to:

> Production Strategy Release Gate ON을 승인한다. Strategy production release를 진행해라.

A future ON release must be a separate intentional change. CI, runtime verification, a merged PR, or this correction must never imply that approval.
