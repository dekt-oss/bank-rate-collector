# Private Inflow Calibration Runtime Runbook

- Date: 2026-08-25
- Parent Issue: #167
- Applies after: actual internal source files are formally received in an approved local/private workspace
- Public contracts: `inflow-calibration-protocol-v1`, `inflow-private-model-registry-v1`, `inflow-public-forecast-v1`
- Current public fallback: Public Structural v2
- Target state after this change is merged: **PRE-DATA COMPLETE / INTERNAL DATA BLOCKED**

This runbook is an operator procedure, not an instruction to place internal data in this public
repository. The public repository provides validation contracts only. Source-specific adapters,
training commands, model storage, and private inference do not exist here yet and must be implemented
in the separately approved local-only private repository after real data arrives.

---

## 1. Stop conditions before any work

Stop immediately if any item below is true.

- The proposed data or artifact path is inside the public `bank-rate-collector` checkout.
- The private code repository has a Git remote or a push destination that was not separately approved.
- A source file contains customer, account, resident-registration, phone, email, or address identifiers.
- The source owner, retention period, access authority, or approved storage location is unknown.
- The observation date/as-of meaning of any feature is unknown.
- A current target-period outcome could be present in a model feature.
- The canonical bundle has less than 24 observation dates or less than two years of history.
- Promotion evidence has less than 36 observation dates, four OOS folds, six OOS pricing events, or one
  untouched final holdout.
- A model/report/data/schema digest cannot be reproduced exactly.
- Human approval is absent, predates evaluation, lacks a timezone, or cannot be linked to an approval
  reference.

Do not replace unknown values with estimates to pass a gate. Record the failure and return the bundle to
the data owner or model owner.

---

## 2. Public/private boundary

### Public Git/GitHub may contain

- generic schema and field names;
- deterministic synthetic fixtures that cannot be linked to internal observations;
- validation and governance contract code;
- generic operating instructions;
- pre-data governance threshold definitions.

### Public Git/GitHub must never contain

- internal source files or aggregate raw rows;
- customer/account/direct identifiers;
- source-specific private sheet names, column names, or product mappings;
- fitted coefficients, feature importance, or training diagnostics;
- model binaries or serialized model artifacts;
- actual training-data fingerprints or actual promotion reports;
- actual private registry rows or approval-document contents;
- private storage paths, credentials, tokens, or encryption material.

The existing local bootstrap guide is
`docs/specs/20260822-private-inflow-engine-local-bootstrap-claude.md`. Its strong `.gitignore`, staged-file
scanner, local hook, no-remote rule, and sibling code/data directories remain prerequisites. `.gitignore`
is defense in depth; it does not authorize copying private files into a Git working tree.

---

## 3. Logical private workspace

Use the approved local root selected by the bootstrap guide. The private Git repository and private data
root are siblings, never parent/child.

```text
<approved-private-root>/
├─ inflow-engine-private/         local-only Git; code and generic tests only
└─ data/                          outside every Git working tree
   ├─ source/                     immutable files exactly as received
   ├─ canonical/                  source-specific adapter output
   ├─ features/                   as-of feature tables
   ├─ experiments/                run manifests and aggregate evaluation outputs
   ├─ models/                     model artifacts
   ├─ promotion-reports/          exact reports used by governance review
   ├─ registry/                   append-only registry snapshots
   └─ backups/                    immutable pre-change recovery bundles
```

Set the data root only in the private runtime environment:

```powershell
$env:INFLOW_PRIVATE_DATA_ROOT = '<approved-private-root>\data'
```

Do not put the real value in public code, a public workflow, command history shared with others, or this
runbook.

### Preflight commands

Run these from the local-only private code repository. They print metadata, not data contents.

```powershell
git remote -v
git status --short --branch
git ls-files
Test-Path -LiteralPath $env:INFLOW_PRIVATE_DATA_ROOT
```

Required result:

- `git remote -v` is empty unless a separate private remote was explicitly approved.
- `git ls-files` contains no spreadsheet, delimited data, database, model, report, registry, or secret.
- `INFLOW_PRIVATE_DATA_ROOT` exists and is outside both the private and public Git working trees.

---

## 4. First-receipt checklist

Complete and retain a private intake checklist before fitting.

- [ ] Record source owner, delivery time, permitted use, retention rule, and file SHA-256.
- [ ] Confirm the source directory is read-only to the research process.
- [ ] Count files, sheets/tables, rows, observation dates, and the min/max date without copying values to
      public logs.
- [ ] Measure required-field missingness and duplicate canonical keys.
- [ ] Scan field names and representative values for direct PII; any hit is No-Go.
- [ ] Measure product-key mapping coverage and list unmapped counts privately.
- [ ] Measure term and channel coverage; do not merge unknown segments into a known segment.
- [ ] Count pricing events and identify their effective/as-of timestamps.
- [ ] Verify maturity amount/account coverage.
- [ ] Verify rollover amount/account coverage and `rollover_amount <= maturity_amount`.
- [ ] Verify early-withdrawal amount/account coverage.
- [ ] Verify FTP availability separately; FTP is not a forecast feature in v1.
- [ ] Verify every proposed feature has a reproducible as-of date at forecast origin.
- [ ] Measure market-rate join coverage by date/product/term/channel and retain unmatched counts.
- [ ] Confirm at least 24 dates for research and 36 dates for promotion review; nonlinear work requires 60.

Do not report private counts, hashes, or coverage values in a public Issue, PR, Action, or Strategy payload.

---

## 5. Execution ledger

Each stage records its input, output, failure condition, and retained evidence inside the private data root.

| Stage | Input | Private output | Fail/No-Go | Evidence retained |
| --- | --- | --- | --- | --- |
| 1. Receive | approved source files | immutable `source/` copy | authority, retention, location, or digest unknown | receipt manifest + file digest |
| 2. Adapt | immutable source | `canonical/` datasets | source mapping ambiguous or lossy | adapter version + mapping review ref |
| 3. E0 intake | canonical bundle | intake report | missing dataset, PII, invalid values, history below minimum | exact intake report |
| 4. Feature table | accepted canonical bundle + external context | `features/` table | join coverage below approved threshold or missing as-of evidence | feature schema + join/missingness report |
| 5. Leakage audit | feature values + as-of dates | validated row/table manifest | future/target/outcome feature or orphan/missing as-of key | as-of audit report |
| 6. Incumbent | identical OOS periods | structural reference predictions | periods or target definitions differ from challenger | incumbent run manifest |
| 7. Fit challenger | train windows only | model artifact in `models/` | OOS/holdout used for tuning, insufficient candidate history | training manifest + artifact digest |
| 8. OOS backtest | frozen artifact + expanding splits | OOS predictions | random split, missing fold, holdout touched during tuning | split manifest + row-count summary |
| 9. Evaluate | incumbent/challenger OOS predictions | common metric bundles | invalid component totals, zero denominator, missing event baseline | evaluator version + metrics |
| 10. Promotion | metrics + fold roles + evidence identities | promotion report | any primary/fold/component/bias/event gate fails | exact canonical report + SHA-256 |
| 11. Human review | exact report and linked artifacts | approval or rejection record | identity/digest mismatch or incomplete risk review | approver/timezone/ref |
| 12. Registry | approval + exact report digest | new registry snapshot | entry invalid, duplicate scope champion, old champion active | before/after snapshots |
| 13. Private inference | active champion artifact | private forecast | artifact digest differs from registry or inference health fails | inference run manifest |
| 14. Public boundary | private forecast result | sanitized public payload | unknown/private field or numeric invariant failure | allowlist validation result only |
| 15. Strategy | accepted public payload or current structural fallback | production Strategy view | public payload unavailable/invalid | public publication/runtime evidence |

Public repository function contracts used by these stages:

- `assess_internal_calibration_bundle` — canonical intake gate;
- `validate_as_of_feature_row` — per-row availability/leakage gate;
- `build_expanding_window_splits` — deterministic time-based fold contract;
- `score_backtest_records` — common component-aware evaluator;
- `assess_challenger_promotion` — human-review eligibility only;
- `promotion_report_digest` — canonical JSON SHA-256;
- `assess_champion_activation` — exact evidence plus approval gate;
- `validate_private_registry_snapshot` — one champion per scope and replacement audit;
- `validate_public_forecast_payload` — final public allowlist boundary.

These are library functions, not a finished private-runtime CLI. The private repository must call them or
maintain an explicitly versioned mirror; this public repository does not read internal paths or train a
model.

---

## 6. Evidence and versioning contract

Create one immutable private experiment manifest and keep these values consistent across artifact,
promotion report, approval, and registry metadata.

| Field | Rule |
| --- | --- |
| `experiment_id` | opaque, non-empty identifier; no surrounding whitespace |
| `candidate_key` | exact known challenger key |
| `protocol_version` | exact `inflow-calibration-protocol-v1` |
| `feature_schema_sha256` | lowercase SHA-256 of the frozen schema definition |
| `training_data_fingerprint_sha256` | lowercase SHA-256 of the approved private training snapshot/manifest |
| `model_artifact_sha256` | lowercase SHA-256 of the exact artifact used for OOS evaluation/inference |
| `promotion_report_sha256` | canonical JSON digest from `promotion_report_digest` |
| `training_cutoff_date` | last observation available to the final training window |
| `evaluation_cutoff_date` | last untouched OOS/final-holdout observation |
| `human_approver` | accountable reviewer identifier |
| `human_approval_at` | timezone-bearing timestamp after evaluation cutoff |
| `human_approval_ref` | opaque internal approval-record reference, not its contents |
| `effective_from_date` | calendar date strictly after the approval date |

Before activation, recompute every digest from the exact private object. A matching report status string is
not evidence. `assess_champion_activation` must return `activation_allowed`; it still returns
`auto_activate=false`, so the operator performs a separate explicit activation action in the private
runtime.

---

## 7. Backup and champion replacement

### Pre-change backup

Before changing a registry snapshot, copy these exact private objects to a new immutable backup directory:

- current registry snapshot;
- current champion artifact;
- current champion promotion report;
- proposed artifact and promotion report;
- experiment/run manifests;
- approval reference metadata.

Example metadata-only verification inside the private workspace:

```powershell
Get-FileHash -Algorithm SHA256 -LiteralPath '<private-model-artifact>'
Get-FileHash -Algorithm SHA256 -LiteralPath '<private-promotion-report>'
Get-FileHash -Algorithm SHA256 -LiteralPath '<private-registry-snapshot>'
```

Compare the resulting lowercase digests with the private manifest. Do not paste results into public logs.

### Replacement order

Use this manual, audited order for the same `scope_key`:

1. Validate the proposed champion and exact promotion report.
2. Create the backup bundle and verify its digests.
3. Record the old champion as `retired` with timezone-bearing `retired_at`, `retired_by`,
   `retirement_ref`, and `retirement_reason`.
4. Ensure old `retired_at` is earlier than the new approval timestamp and effective date.
5. Set the new champion's `supersedes_model_id` to the retired predecessor.
6. Validate the complete snapshot; it must have only one active champion for the scope.
7. Activate in the private runtime only after the effective date and explicit operator action.
8. Pass only an allowlisted forecast result to Strategy.

Never rewrite or delete the old approval, promotion, or retirement evidence.

### Failure and rollback

If the new private model is unhealthy:

1. Stop private inference for the affected scope and record the incident privately.
2. Mark the new champion `retired` with explicit retirement evidence; do not silently delete its row.
3. Use the current Public Structural v2 output as the immediate safe product fallback. The public
   structural simulator remains production functionality and does not depend on private coefficients.
4. Verify all backup digests before considering a previous artifact.
5. Do **not** mutate a retired row back to `champion`. Registry v1 has no direct `unretire` transition.
6. Restoring a previous artifact as a private champion requires a new model/registry identity, current
   evidence binding, human review, and a valid single-champion snapshot.

Automatic rollback, automatic unretire, and automatic model activation are not implemented by this
contract.

---

## 8. Public-boundary release check

Before publishing any private forecast result:

- [ ] Recompute model/report/data/schema digests and match them to the active registry entry.
- [ ] Confirm the registry snapshot has one active champion for the scope.
- [ ] Confirm the approval timestamp and effective date are valid.
- [ ] Build a new payload containing only `inflow-public-forecast-v1` fields.
- [ ] Run `validate_public_forecast_payload`; do not catch an error and publish a stripped payload.
- [ ] Confirm no coefficient, model/experiment ID, fingerprint, diagnostics, source path, sample detail, or
      approval metadata is present.
- [ ] If validation or private inference fails, publish no private payload and retain Public Structural v2
      as the product fallback.

The runbook does not change Strategy UI, the public forecast schema, the current β/γ stress assumptions,
canonical rates, source precedence, storage schema, collectors, or schedules.

---

## 9. First actual-data run output

The first private run is complete only when the operator can produce, inside the private workspace:

- approved intake and leakage audit reports;
- a frozen feature schema and all required digests;
- identical-period incumbent and challenger OOS outputs;
- four or more expanding-window folds with one untouched final holdout;
- a canonical promotion report;
- an explicit human approval or rejection;
- a valid registry snapshot with at most one active champion per scope;
- a public-boundary validation result;
- a backup/rollback evidence bundle.

Actual model quality, calibrated coefficients, forecast accuracy, champion selection, private inference,
and drift monitoring remain **unverified and blocked until internal data and an approved private runtime
are available**.
