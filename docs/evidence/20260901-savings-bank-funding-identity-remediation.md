# Savings-bank funding identity remediation — production-copy evidence

Date: 2026-09-01

## Plain-language purpose

Data.go savings-bank funding had 79 current institution rows for 2026-03. 66 were already attached to canonical institutions and 13 were left unmapped because Data.go used Korean/legal-style names while the existing FSB and Finlife savings-bank sources used brand/acronym names (for example `오케이저축은행` vs `OK저축은행`).

This change does **not** relax the repository-wide code+name identity rule. For the savings-bank funding collector only, a name-mismatched Data.go row may be attached when:

- the exact `savings_bank:<fncoCd>` key has one active `exact_code` link in FSB,
- the same key has one active `exact_code` link in Finlife savings bank,
- both links point to the same active savings-bank canonical institution,
- no CRNO conflict is present,
- the sector-total row `030350S` is excluded.

The consensus result is observation-level only. It does not create a permanent Data.go `SourceEntityLink`, so later FSB/Finlife divergence cannot bypass the two-source gate.

## Production-copy validation

Validation used the current production R2 snapshot restored into a GitHub Actions runner-local SQLite file. The source database was never uploaded or written back.

- workflow run: `33472480883`
- artifact: `savings-bank-identity-census-33472480883`
- artifact id: `9787038618`
- artifact ZIP SHA256: `b264f52786c9030ab1e3516a599ce8d5e6422b054d00aebd692744582604b090`
- restored snapshot: `state/snapshots/20260901T133651-a27fffb4.sqlite3.gz`
- source effective month: `2026-03`
- production DB SHA256 before/after read-only census: `c4a94590ea6ef453b1934346a82adeb7a01babbce07bc2acf60988b44ccea516`

### Acceptance result

| Check | Result |
|---|---:|
| Current source population | 79 |
| Before mapped | 66 |
| Before unmapped | 13 |
| First reconciliation newly mapped | 13 |
| After mapped | 79 |
| After unmapped | 0 |
| Existing 66 identity changes | 0 |
| Non-identity field changes | 0 |
| Persistent Data.go funding-link changes | 0 |
| Active aggregate `030350S` before/after | 0 / 0 |
| Second reconciliation newly mapped | 0 |
| Production write-back | false |

### Invariant fingerprints

- non-identity fingerprint before: `de4e023efce072c5c3accfd2389841e271be267b04939b159af495ad09e8e4c3`
- non-identity fingerprint after: `de4e023efce072c5c3accfd2389841e271be267b04939b159af495ad09e8e4c3`
- Data.go funding-link fingerprint before: `cc86c29a390d72ebc8ba4c595689afad26846fef74be744c4938b39e8ce55370`
- Data.go funding-link fingerprint after: `cc86c29a390d72ebc8ba4c595689afad26846fef74be744c4938b39e8ce55370`

The non-identity fingerprint covers all observation columns except `institution_id` and `identity_status`; therefore amounts, source month, revision, validity, hashes and raw provenance were unchanged in the copy validation.

## 13 remediated rows

| fncoCd | Data.go name | Canonical name |
|---|---|---|
| 0010346 | 오에스비저축은행 | OSB저축은행 |
| 0010370 | 에스비아이저축은행 | SBI저축은행 |
| 0010404 | 디에이치저축은행 | DH저축은행 |
| 0010438 | 유니온상호저축은행 | 유니온저축은행 |
| 0010439 | 엠에스상호저축은행 | MS저축은행 |
| 0010468 | 세람상호저축은행 | 세람저축은행 |
| 0010568 | 대원상호저축은행 | 대원저축은행 |
| 0011767 | 제이티저축은행 | JT저축은행 |
| 0012889 | 아이비케이저축은행 | IBK저축은행 |
| 0013002 | 비엔케이저축은행 | BNK저축은행 |
| 0013127 | 케이비저축은행 | KB저축은행 |
| 0013308 | 제이티친애저축은행 | JT친애저축은행 |
| 0013351 | 오케이저축은행 | OK저축은행 |

All 13 received observation status `mapped_dual_source` in the runner-local remediation copy.

## Safety properties

- No fuzzy matching.
- No name-only mapping.
- No CRNO-only mapping.
- FSB-only or Finlife-only evidence fails closed.
- Duplicate active reference links fail closed.
- FSB/Finlife disagreement fails closed.
- Inactive or non-savings-bank canonical targets fail closed.
- CRNO conflict fails closed.
- Existing mapped observations are not rewritten; disagreement raises a conflict.
- Only the latest active savings-bank funding month is reconciled.
