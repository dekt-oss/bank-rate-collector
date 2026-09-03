# Relative Pricing R2 — 저축은행 historical funding evidence

```yaml
date: 2026-09-03
rate_snapshot_as_of: 2026-08-31
funding_as_of: 2026-03
knowledge_as_of: 2026-08-31
sector: savings_bank
metric: deposit_liabilities_total
production_write: false
status: funding_foundation_ready
```

## 결론

2026-08-31 historical Relative Pricing 분석에서 저축은행 funding은 **2026-03
source-effective month**를 당시 알려진 최신 완전관측 월로 사용할 수 있다.

이 의미는 `2026-03` 값이 3월 당시 우리 시스템에 존재했다는 뜻이 아니다. 해당
공식 과거자료는 2026-08-28 수집되어 2026-08-31 분석 cutoff에는 이미 알려져
있었다. 따라서 R2는 아래 세 시점을 구분한다.

```text
rate_as_of      = 2026-08-31
funding_as_of   = 2026-03
knowledge_as_of = 2026-08-31
```

`funding_as_of`를 `rate_as_of`로 바꾸거나 nearest-month로 보간하지 않는다.

---

## 1. Knowledge-time census

Evidence workflow run: `33702029707`
Artifact: `relative-pricing-r2-funding-knowledge-33702029707`
Artifact id: `9873902957`
Artifact ZIP SHA256:
`243e82b2e9cb9d2a01223352229d996f3a6a226cca95222662f1737f2347b3b4`

Cutoff: `2026-08-31 23:59:59`

| source month | rows | observed by cutoff | after cutoff | exact historical identity | canonical duplicates |
|---|---:|---:|---:|---:|---:|
| 2026-03 | 79 | 79 | 0 | 79 | 0 |
| 2025-09 | 79 | 79 | 0 | 79 | 0 |
| 2025-03 | 79 | 79 | 0 | 79 | 0 |

Observed timestamps:

- 2026-03 rows: `2026-08-28 15:17:50.942993`
- 2025-09 rows: `2026-08-28 15:18:06.398864`
- 2025-03 rows: `2026-08-28 15:18:22.181033`

Production snapshot의 전체 savings-bank funding month census에서
`2026-08-31` cutoff까지 79행이 완전히 관측된 가장 최신 source month는
**2026-03**이었다.

### 고려저축은행

Source key: `0010390`
Canonical institution id:
`a78d347f-9a4f-4ec4-9c4e-0bbcce0102c2`

| month | balance | unit | observed_at |
|---|---:|---|---|
| 2026-03 | 1,836,484 | million_krw | 2026-08-28 15:17:50.942993 |
| 2025-09 | 1,721,962 | million_krw | 2026-08-28 15:18:06.398864 |
| 2025-03 | 1,378,903 | million_krw | 2026-08-28 15:18:22.181033 |

Historical identity resolution method:
`fsb_finlife_exact_code_temporal_consensus`.

---

## 2. Historical identity gate

Separate identity evidence run: `33700347261`
Artifact: `relative-pricing-r2-funding-identity-33700347261`
Artifact id: `9873317840`
Artifact ZIP SHA256:
`21e56cd16e49e9d60856fb94d1f35baf61657764e56d5c440da527023ac5e2d5`

2026-03 funding 79행에 대해:

- temporal-link identity resolved: **79 / 79**
- supporting links recorded by cutoff: **79 / 79**
- unresolved: **0**
- historical resolution agrees with current canonical id: **79 / 79**

현재 observation의 mutable `institution_id` 또는 `identity_status` 자체는 historical
proof로 사용하지 않는다.

Resolver는 cutoff 당시 기록된 source link를 다시 해석한다.

1. Data.go direct exact-code/name link가 cutoff 이전에 존재하면 사용
2. 없으면 FSB exact-code + Finlife savings-bank exact-code가 같은 canonical
   institution으로 합의해야 함
3. supporting link의 `created_at`도 cutoff 이하여야 함
4. ambiguous/conflicting identity는 fail-closed

---

## 3. Production-format runtime verification

Feature branch runtime workflow run: `33702445782`
Artifact: `relative-pricing-r2-funding-runtime-33702445782`
Artifact id: `9874037311`
Artifact ZIP SHA256:
`8d79a6936ab6b33cb6165ab5d6279cab4d34c24161abe23e455eedb527e36d25`

Restored runner-local production snapshot:
`state/snapshots/20260903T094307-e2abe4d7.sqlite3.gz`

Historical adapter result:

```text
status                         ready
rate_as_of                     2026-08-31
knowledge_as_of                2026-08-31
funding_as_of                  2026-03
required exact funding points  237
2026-03 institutions           79
funding join                   79 / 79
funding missing                0
nearest-month interpolation    false
missing-as-zero                false
mutable observation identity   not trusted
production write               false
```

고려저축은행 runtime result:

```text
2026-03 balance       1,836,484 million KRW
2025-09 balance       1,721,962 million KRW
2025-03 balance       1,378,903 million KRW
6M change             +6.6506694108%
12M change            +33.1844226896%
```

---

## 4. Implementation contract

`relative_pricing_historical_funding.py`

- immutable SQLite read
- explicit `knowledge_as_of`
- exact analysis month + exact -6M/-12M only
- `observed_at <= knowledge_as_of`
- revision `valid_from/valid_to` evaluated at historical cutoff
- multiple simultaneously-valid revisions hard error
- source-specific mutable identity fields are not mapping proof
- reconstructed exact historical identity only
- missing prior month remains null; no imputation
- funding missing does not remove a pricing peer
- `rate_as_of`, `funding_as_of`, `knowledge_as_of` remain separate

`relative_pricing_historical_funding_identity.py`

- savings-bank funding identity only for this R2 stage
- direct exact Data.go evidence or FSB + Finlife exact-code consensus
- source link must have been recorded by historical cutoff
- current `Institution.active` is not used as historical activity evidence
- CRNO conflict and link cardinality conflicts fail closed

The existing `institution_funding_read_model.py` remains the authoritative exact-month
6M/12M calculation after safe historical points are reconstructed.

---

## 5. Remaining R2 blocker

Funding foundation is now evidence-backed for the 2026-08-31 savings-bank snapshot,
but **R2 historical analogue is still not activated**.

The remaining upstream rate-population blocker is historical special-offer provenance:

```text
historical_special_offer_gate = blocked
reason = no_versioned_explicit_fsb_special_offer_field
```

Therefore this funding work does not bypass PR #286's fail-closed historical rate gate,
and does not enable historical peer ranking, analogue UI, or causal interpretation.
