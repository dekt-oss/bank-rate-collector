# Relative Pricing R2 historical evidence gate — 2026-09-03

## 목적

R2 Historical Relative Market Analogue에 현재 가입가능지역이나 현재 identity를 과거로 소급하지 않고, 공식 FSB 과거 AREA census와 canonical `source_entity_links`의 point-in-time 근거가 함께 존재하는 날짜를 확인한다.

이 문서는 **evidence inventory**다. R2 계산 또는 UI를 활성화하지 않는다.

## 실행 근거

- repository: `dekt-oss/bank-rate-collector`
- evidence branch: `evidence/relative-pricing-r2-historical-20260903`
- workflow: `Relative Pricing R2 historical evidence`
- workflow run: `33651217860`
- exact head: `a6182b55988b7bb6f33a0bf44a3716402a496914`
- production snapshot restored runner-local only:
  - `state/snapshots/20260902T235430-db367adc.sqlite3.gz`
  - rate observations: 6,268,903
  - institutions: 7,126
  - products: 81,644
  - product variants: 445,229
  - collection runs: 327
- production DB write/publish: **없음**

## Evidence contract

1. 가입가능지역은 FSB `ratedepo` 공식 AREA census를 과거 조회일로 다시 질의한다.
2. canonical identity는 `source_entity_links` 중 `source_id='fsb'`, `entity_type='institution'`, `match_method='exact_code'`만 허용한다.
3. `as_of=t`에서 link `valid_from <= t < valid_to`인 identity만 인정한다.
4. `valid_from`이 없거나 미래이면 과거 identity 근거로 사용하지 않는다.
5. 현재 identity 및 현재 availability의 carry-back은 금지한다.

## 결과

### 2026-03-31

공식 FSB 과거 AREA census 자체는 정상 재현됐다.

- FSB 기관: **79**
- FSB 정기예금 상품: **391**
- `YN_Busan` 가입가능 기관: **14**
- point-in-time exact identity mapped: **0 / 79**
- identity unproven: **79 / 79**
- identity ambiguous: **0**
- 고려저축은행 historical source code: **증명 불가**
- historical anchor AREA: **증명 불가**
- gate: `insufficient_history`
- reason: `anchor_identity_not_proven_at_as_of`

### 판정

2026-03-31의 공식 AREA 원문을 현재 canonical identity에 연결할 수는 있지만, 그 연결이 2026-03-31 당시에도 유효했다는 temporal evidence가 없다.

따라서 현재 FSB exact identity를 2026-03-31로 소급하여 부산 peer를 만드는 것은 **금지**한다.

공식 원천에서 부산 14개라는 사실이 조회된 것과, 그 14개를 현재 canonical institution ID에 역사적으로 매핑할 수 있다는 것은 별개의 계약이다.

---

### 2026-08-31

공식 FSB 과거 AREA census와 point-in-time exact identity가 함께 성립했다.

- FSB 기관: **79**
- FSB 정기예금 상품: **395**
- `YN_Busan` 가입가능 기관: **14**
- point-in-time exact identity mapped: **79 / 79**
- identity unproven: **0**
- identity ambiguous: **0**
- 고려저축은행 FSB source code: **`0010390`**
- 고려저축은행 AREA: **`YN_Busan`**
- 부산 cohort source codes: **14**
- 부산 cohort mapped canonical institutions: **14**
- cohort identity unresolved: **0**
- gate: `availability_identity_evidence_ready`

### 판정

2026-08-31은 R2의 **availability + identity gate**를 통과하는 첫 확인 표본이다.

단, 이것만으로 R2 historical analogue 전체를 `ready`로 열 수는 없다. 다음 evidence가 추가로 필요하다.

1. 2026-08-31 historical representative rate
2. source precedence를 동일 시점으로 재현할 수 있는지
3. product/term/special-offer scope가 point-in-time으로 재현되는지
4. historical funding을 사용할 경우 미래 funding leak이 없는지
5. market regime가 같은 시점 정보만으로 구성되는지
6. merger/identity effective-date 경계에서 canonical duplicate가 0인지

## 현재 허용 범위

| as-of | official AREA | point-in-time identity | R2 availability/identity |
|---|---|---|---|
| 2026-03-31 | 있음 | 없음 | **차단** |
| 2026-08-31 | 있음 | 79/79 | **다음 gate 진행 가능** |

## 다음 작업

R1-D verification gate가 완료된 뒤 2026-08-31을 첫 R2 candidate date로 사용해 **historical rate/source precedence/product-scope evidence**를 조사한다.

R2 구현은 다음 항목이 증명되기 전까지 시작하지 않는다.

- future rate leak = 0
- current identity carry-back = 0
- current availability carry-back = 0
- unsupported historical product/special-offer scope 사용 = 0
- canonical institution duplicate = 0

Funding과 market regime는 evidence availability에 따라 nullable/insufficient로 유지하며, 현재값으로 보간하거나 소급하지 않는다.
