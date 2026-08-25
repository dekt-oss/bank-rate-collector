# Inflow Pre-Data E2E and Runtime Runbook Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the last internal-data-independent inflow-engine preparation by binding promotion evidence to one exact experiment, rehearsing the complete private research contract with deterministic synthetic data, and documenting the private runtime operating procedure.

**Architecture:** Keep production behavior unchanged. Strengthen the existing pure governance functions, then exercise the existing intake, as-of, evaluator, promotion, registry, and public-boundary services directly from one integration test; the runbook describes the private workspace but stores no private values in this public repository.

**Tech Stack:** Python 3.12, pytest, Ruff, Alembic, GitHub Actions.

**Spec:** `docs/specs/20260825-private-inflow-calibration-protocol-v1.md` and `docs/specs/20260825-private-inflow-model-registry-contract-v1.md`

## Global Constraints

- Production Strategy Dashboard remains ON; do not change its workflows, UI, or public calculation.
- Do not introduce actual internal data, coefficients, feature importance, diagnostics, model artifacts, registry rows, approval contents, DB/schema/migrations, collectors, schedulers, FTP modeling, automatic rates, automatic promotion, or Phase 5 work.
- All new test data must be deterministic and visibly synthetic; no random seed or mock-only integration path.
- Champion activation remains human-approved and fail-closed; no automatic activation or rollback is added.
- Work on a new branch, create a Draft PR linked to Issue #167, and do not merge without separate user approval.

---

### Task 1: Bind governance evidence and close merged-review gaps

**Files:**
- Modify: `src/rate_monitor/services/inflow_calibration_protocol.py`
- Modify: `src/rate_monitor/services/inflow_private_model_registry_contract.py`
- Modify: `tests/test_inflow_calibration_protocol.py`
- Modify: `tests/test_inflow_private_model_registry_contract.py`
- Modify: `docs/specs/20260825-private-inflow-calibration-protocol-v1.md`
- Modify: `docs/specs/20260825-private-inflow-model-registry-contract-v1.md`

**Interfaces:**
- Consumes: existing `assess_challenger_promotion`, `assess_champion_activation`, `validate_private_registry_entry`, and `validate_private_registry_snapshot` contracts.
- Produces: promotion reports containing `experiment_id`, `model_artifact_sha256`, `training_data_fingerprint_sha256`, and `feature_schema_sha256`; activation compares all four plus protocol/candidate identity with the registry entry.

- [ ] **Step 1: Write failing promotion-evidence tests**

```python
def test_activation_rejects_report_from_another_experiment() -> None:
    report = _promotion_report(experiment_id="experiment-other")
    entry = _champion_entry()
    entry["promotion_report_sha256"] = promotion_report_digest(report)
    activation = assess_champion_activation(entry=entry, promotion_report=report)
    assert activation["status"] == "blocked"
    assert "promotion_report:experiment_id_mismatch" in activation["reasons"]
```

Add equivalent literal mismatch cases for protocol version, model artifact digest, training-data fingerprint, and feature-schema digest.

- [ ] **Step 2: Run the focused tests and confirm RED**

Run: `uv run pytest -q tests/test_inflow_private_model_registry_contract.py`

Expected: the new cross-experiment/evidence cases fail because activation currently checks only candidate identity and report digest.

- [ ] **Step 3: Add exact evidence identity to the promotion report and activation gate**

Change the keyword-only promotion assessment interface to require:

```python
def assess_challenger_promotion(
    *,
    experiment_id: str,
    model_artifact_sha256: str,
    training_data_fingerprint_sha256: str,
    feature_schema_sha256: str,
    candidate_key: str,
    observation_date_count: int,
    pricing_event_oos_count: int,
    feature_columns: list[str] | tuple[str, ...] | set[str],
    challenger_metrics: dict[str, float],
    incumbent_metrics: dict[str, float],
    fold_metrics: list[dict[str, float | str]],
) -> dict[str, Any]:
```

Validate identifiers and lowercase SHA-256 values fail-closed, emit them in the canonical report, and require exact equality during activation.

- [ ] **Step 4: Write and run RED tests for registry parsing and chronology**

Cover these concrete breaks:

```python
validate_private_registry_entry({**_candidate_entry(), "model_id": " model-001 "})
validate_private_registry_entry({**_candidate_entry(), 7: "unexpected"})
validate_private_registry_entry({**_champion_entry(), "effective_from_date": "2026-01-03"})
validate_private_registry_snapshot([_retired_entry(retired_at="2026-02-05T09:00:00+09:00"), replacement])
validate_private_registry_snapshot([retired_replacement_with_missing_superseded_model])
```

Expected: current code accepts whitespace/same-day/backdated or retired-link cases, and a non-string key raises instead of returning `invalid`.

- [ ] **Step 5: Implement the minimal fail-closed corrections**

Reject surrounding whitespace instead of normalizing stored identifiers, reject non-string field keys before sorting, require `effective_from_date > human_approval_at.date()`, validate supersession links for champion and retired former champions, and require predecessor retirement to occur before replacement approval/effectiveness.

- [ ] **Step 6: Run registry and calibration suites GREEN**

Run: `uv run pytest -q tests/test_inflow_calibration_protocol.py tests/test_inflow_private_model_registry_contract.py`

Expected: all focused tests pass with no warnings.

### Task 2: Add deterministic synthetic end-to-end rehearsal

**Files:**
- Create: `tests/test_inflow_private_research_rehearsal.py`
- Modify: `.github/workflows/inflow-engine-contract.yml`

**Interfaces:**
- Consumes: `assess_internal_calibration_bundle`, `validate_as_of_feature_row`, `build_expanding_window_splits`, `score_backtest_records`, `assess_challenger_promotion`, `promotion_report_digest`, `assess_champion_activation`, `validate_private_registry_snapshot`, and `validate_public_forecast_payload`.
- Produces: one real-service positive rehearsal and HANDOFF adversarial paths without a production orchestrator or private data.

- [ ] **Step 1: Write the positive-path integration test first**

Build one literal/generated synthetic 37-month canonical bundle with no PII, validate a representative as-of row, score incumbent/challenger predictions through the common evaluator, construct four fold results including one final holdout, produce an eligible report, bind it to a synthetic registry entry, simulate explicit timezone-bearing approval, and assert activation is allowed while `auto_activate` and every `database_written` flag remain false.

- [ ] **Step 2: Run the new file and confirm RED**

Run: `uv run pytest -q tests/test_inflow_private_research_rehearsal.py`

Expected: fail until the complete fixture and evidence-bound promotion interface are connected.

- [ ] **Step 3: Add the ten adversarial paths using the same deterministic fixture**

Add direct real-service assertions for future leakage, tampered report, blocked-promotion registry forgery, absent approval, approval before evaluation, timezone-less approval, duplicate same-scope champions, replacement without retirement, private coefficient leakage through the public forecast validator, and final-holdout/component regression promotion failure.

- [ ] **Step 4: Add the test to targeted CI and run GREEN**

Run: `uv run pytest -q tests/test_inflow_private_research_rehearsal.py`

Expected: the positive path and all ten adversarial paths pass without mocks or random data.

### Task 3: Write the private runtime operating runbook

**Files:**
- Create: `docs/runbooks/private-inflow-calibration-runtime.md`
- Modify: `docs/specs/20260825-private-inflow-model-registry-contract-v1.md`

**Interfaces:**
- Consumes: the current E0 intake, as-of feature, evaluator, promotion, registry, and public forecast contracts plus `docs/specs/20260822-private-inflow-engine-local-bootstrap-claude.md`.
- Produces: a command/checklist-level operator procedure that never contains actual private values.

- [ ] **Step 1: Document the public/private boundary and workspace layout**

Use sibling local-only code/data roots and the logical private layout `source/`, `canonical/`, `features/`, `experiments/`, `models/`, `promotion-reports/`, `registry/`, and `backups/`; state that actual values and files remain outside this public repository.

- [ ] **Step 2: Document every execution gate**

For source receipt through Strategy publication, list input, output, failure/no-go condition, and evidence retained. Include the required first-run checks for history, row counts, missingness, duplicates, PII, product/term/channel coverage, pricing events, maturity/rollover/early-withdrawal/FTP, as-of availability, and market join coverage.

- [ ] **Step 3: Document evidence, backup, and rollback**

Record every #208 identity/hash/cutoff/approval field, require digest verification before use, preserve immutable registry snapshots, retire the old champion before activating a replacement, and define manual fallback to the current public structural forecast when private inference is unavailable. Do not implement automatic rollback.

- [ ] **Step 4: Cross-check the runbook against live function names and lifecycle rules**

Read each named service and verify the runbook does not claim a CLI, storage backend, activation action, or public fallback behavior that the current repository does not provide; label private-runtime commands not yet implemented as operator steps rather than executable repository commands.

### Task 4: Adversarial review, verification, and Draft PR

**Files:**
- Review all files changed since `5bf702a63377ab05031c7bd23c4b3600fc151df9`.

**Interfaces:**
- Consumes: completed Tasks 1-3.
- Produces: reviewed exact-head commit and unmerged Draft PR linked to Issue #167.

- [ ] **Step 1: Run Fable Review against the HANDOFF failure checklist**

Attempt cross-experiment report reuse, lag-named future values, string-only status forgery, same-scope ambiguity, public metadata leakage, impossible rollback chronology, and fixture shortcuts. Record severity and close every Critical/High/Medium finding before final verification.

- [ ] **Step 2: Run required fresh verification**

Run targeted Inflow Engine Contract equivalent, the synthetic E2E file, Ruff, full pytest, empty DB Alembic upgrade, model/schema parity, `git diff --check`, and one direct Python execution of the rehearsal path where available.

- [ ] **Step 3: Commit and push the exact head**

Use a scoped commit message such as `feat: complete inflow pre-data rehearsal and runbook`; push only `codex/feat-inflow-predata-e2e-runbook-20260825`.

- [ ] **Step 4: Create an unmerged Draft PR**

Link Issue #167 and include Current, Target, Scope, Safety Boundary, Verification, Remaining Work, and the exact head SHA. Do not enable auto-merge and do not merge.
