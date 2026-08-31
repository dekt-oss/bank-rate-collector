# 상대금리 기반 목표형 금리결정 시뮬레이터 — 작업지시서 v2

```yaml
document_type: implementation_work_order
status: draft_for_rereview
date: 2026-08-31
repository: dekt-oss/bank-rate-collector
branch: docs/relative-rate-goal-simulator-20260831
supersedes_for_review:
  - docs/plans/20260831-relative-rate-goal-simulator-work-order.md
implementation_authorized: false
merge_authorized: false
production_strategy_surface: true
risk_class: high_financial_decision_support
```

---

# 0. 작업 목표

최종적으로 Strategy 금리결정 기능을 다음 4계층으로 발전시킨다.

```text
R1 factual relative market simulator
R2 historical relative market analogue
R3 private calibrated forward model
R4 goal-based inverse simulator
```

단 구현 착수 전 R0에서 identity, pricing peer, representative rate, factual cost, point-in-time history 계약을 고정한다.

**R1~R4를 한 PR로 구현하지 않는다.**

---

# 1. 시작 전 필수 확인

현재 repository의 실제 존재 파일만 읽는다.

필수:

- `AGENTS.md`
- `pyproject.toml`
- `.gitignore`
- `.github/workflows/ci.yml`
- `.github/workflows/collect.yml`
- `.github/workflows/collect-savings-fast.yml`
- `.github/workflows/strategy-main-runtime-e2e.yml`
- `docs/specs/CURRENT.md`
- `docs/specs/20260822-public-structural-v2-decision-cockpit-final.md`
- `docs/specs/20260825-private-inflow-calibration-protocol-v1.md`
- `docs/specs/20260818-internal-deposit-data-request-v1.md`
- `docs/plans/20260831-relative-rate-goal-simulator-plan-v2.md`
- `docs/reviews/20260831-relative-rate-goal-simulator-claude-review-response.md`
- `docs/evidence/20260831-savings-bank-funding-identity-coverage.md`

관련 구현:

- `public_structural_v2_market_position_service.py`
- `public_structural_v2_cockpit_presentation.py`
- `public_structural_v2_inflow_service.py`
- `inflow_prediction_service.py`
- `inflow_calibration_protocol.py`
- `inflow_asof_feature_contract.py`
- `inflow_backtest_evaluation.py`
- `inflow_private_model_registry_contract.py`
- `institution_funding_direct_peer.py`
- `institution_funding_direct_peer_db.py`
- `institution_funding_read_model.py`
- `institution_funding_read_model_db.py`
- `institution_funding_strategy_payload.py`
- `institution_matching.py`
- `rate_funding_matrix_service.py`
- `strategy_contract_service.py`
- `strategy_decision_cockpit.py`
- `strategy_service_base.py`
- `site_service.py`

`CLAUDE.md`, root `README.md`는 현재 없으므로 읽었다고 가정하지 않는다.

---

# 2. 절대 불변 규칙

1. Strategy는 이미 production surface다.
2. merge = runtime 검증으로 취급하지 않는다.
3. source precedence 임의 변경 금지.
4. stable product identity 임의 변경 금지.
5. canonical institution identity를 name-only로 merge 금지.
6. missing funding/rate를 0으로 대체 금지.
7. current rate/funding을 historical month로 carry-back 금지.
8. nearest-month interpolation 금지.
9. Public Structural v2 product market-position 계약을 institution-level로 몰래 변경 금지.
10. funding peer와 pricing peer를 동일 집합으로 취급 금지.
11. R1 factual cost에서 `predicted_total`, `predicted_new_money`, `predicted_rollover` 사용 금지.
12. `peer_*` 값을 `market_*` field에 저장 금지.
13. R1/R2 public DOM에 목표수신/목표기간 input 렌더링 금지.
14. R1/R2에서 추천금리/필요금리/예상수신 출력 금지.
15. `한계조달원가` 표현 사용 금지.
16. internal raw/private model data를 public git/artifact/log에 저장 금지.
17. inverse solver가 자체 forward 예측식을 가지는 것 금지.
18. promoted champion 없이 inverse solver 호출 금지.
19. out-of-support 목표 외삽 금지.
20. historical peer에서 현재 지역값을 과거에 소급 적용 금지.

---

# 3. PR / Stage 경계

권장 PR 분리:

```text
PR-A  R0 contract/docs/evidence only
PR-B  R0 identity remediation only
PR-C  R1 domain services + payload contract
PR-D  R1 Strategy presentation + runtime E2E
PR-E  R2 historical analogue
PR-F  R3 private data safety/calibration contract
PR-G  R4 inverse solver + private-only UI
```

한 PR이 실패해도 다음 계층으로 넘어가지 않는다.

---

# 4. R0-0 — 문서 기준선 정정

상태: **이 v2 문서에서 반영 완료, 코드 변경 없음**

확정할 것:

- production Strategy = ON canonical writer
- factual cost ≠ uncalibrated predicted-volume cost
- funding peer ≠ pricing peer
- product market position ≠ institution pricing peer position
- public target input UI 없음
- historical region look-ahead 금지

검증:

- main `AGENTS.md`
- canonical collect workflow env
- 관련 source 파일 직접 대조

---

# 5. R0-A — 구현 전 계약 신설

**코드보다 먼저 완료한다.**

## R0-A1 Institution Rate Reduction

신규 계약 후보:

`src/rate_monitor/services/institution_rate_reduction.py`

책임:

- product rows → institution representative rate 1행
- deterministic tie-break
- special-offer core/radar 분리
- selection reason/provenance 반환

기존 `public_structural_v2_market_position_service.py`는 수정하지 않는다.

최소 interface:

```python
reduce_institution_rates(
    rows,
    *,
    sector,
    product_type,
    term_months,
    availability_scope,
    include_special_offer=False,
) -> list[InstitutionRepresentativeRate]
```

반환 계약:

```yaml
institution_id: string
representative_product_id: string
rate_pct: decimal
rate_as_of: date|datetime
availability_scope: string
special_offer_flag: boolean
selection_reason: string
policy_id: string
policy_version: string
```

Acceptance:

- institution당 1행
- 동일 입력 → 동일 결과
- tie-break stable
- product count가 많아도 institution weight 1
- special offer 분리 계약 테스트

## R0-A2 Pricing Peer Policy

신규 모듈 후보:

`src/rate_monitor/services/pricing_peer_selection.py`

funding peer 모듈을 수정해 억지로 수용하지 않는다.

자격:

- exact canonical institution
- same sector
- same product/term
- compatible availability scope
- valid representative rate

funding observation은 optional enrichment다.

최소 반환:

```yaml
institution_id: string
representative_product_id: string
rate_pct: decimal
rate_as_of: date|datetime
peer_reason: string
funding_balance: decimal|null
funding_change_6m_pct: decimal|null
funding_status: known|unavailable
```

## R0-A3 Pricing Peer Position

신규 모듈 후보:

`src/rate_monitor/services/pricing_peer_position.py`

계산:

- peer median rate
- rank best/worst
- ties
- ±5bp / ±10bp count
- higher/lower count
- transition counts when proposal changes

기존 market position과 이름/필드 분리.

## R0-A4 Factual Surface Cost

신규 모듈 후보:

`src/rate_monitor/services/surface_cost_contract.py`

순수 함수:

```python
surface_interest_delta(
    *,
    notional_krw_100m,
    current_rate_pct,
    proposal_rate_pct,
    term_months,
)
```

공식:

```text
notional × Δrate/100 × term_months/12
```

`inflow_prediction_service.py`와 dependency를 두지 않는다.

## R0-A5 Policy versioning

최소 version:

- `institution_rate_reduction_policy_version`
- `pricing_peer_policy_version`
- `surface_cost_contract_version`

payload와 historical recomputation에 포함한다.

---

# 6. R0-B — 저축은행 identity evidence

상태: **population gap 실측 evidence는 완료**

근거:

`docs/evidence/20260831-savings-bank-funding-identity-coverage.md`

확인:

```text
2026-03 source institutions 79
mapped exact             66
unmapped                 13
source/ECOS total        aligned
```

따라서 R0-B에서 추가로 할 일은 `79/66을 다시 추측`하는 것이 아니라 다음이다.

1. production DB read-only restore
2. 13 source identity의 `fncoCd / crno / normalized name` 추출
3. existing canonical institution/source_entity_links 대조
4. exact evidence가 있는 것만 remediation candidate로 기록
5. 불확실한 것은 unresolved queue 유지

Deliverable:

`docs/evidence/YYYYMMDD-savings-bank-identity-remediation-census.md`

각 행:

```text
source_fncoCd
source_crno
source_name
candidate_institution_id
canonical_name
evidence_type
mapping_decision
reason
```

---

# 7. R0-C — 저축은행 exact identity remediation

High-risk persistent identity 작업.

## 조건

R0-B census에서 exact evidence가 확보된 기관만 처리한다.

허용 evidence 예:

- exact FSS fncoCd
- exact legal registration/corporate number
- official directory linkage
- existing canonical history와 일치하는 exact source identifier

금지:

- 단순 이름 유사도
- 수신규모 유사도
- 주소 유사도 하나만으로 merge
- current display name만 보고 merge

## 검증

remediation 후:

- canonical mapped count
- unmapped count
- source total unchanged
- ECOS reconciliation unchanged
- duplicate canonical link 0
- FK/integrity
- historical link range 충돌 0

79/79이 목표일 수 있으나, evidence가 부족하면 억지로 79/79을 만들지 않는다.

Gate는 `evidence-backed mapping only`다.

---

# 8. R0-D — Historical evidence inventory

두 축을 별도로 조사한다.

## R0-D1 NH 2025-12 historical rate

현재 Strategy matrix는:

```text
status = historical_rate_unavailable
historical_rate_institutions = 0
```

다음 순서:

1. immutable raw evidence / R2 raw evidence manifest 검색
2. source가 historical date query를 공식 지원하는지 검증
3. existing imported raw/history가 있는지 검증
4. provenance가 없으면 replay/추정 금지

결과:

- evidence available → R2 candidate
- unavailable → 현 상태 유지

## R0-D2 Historical region / availability history

현재 `institutions.region_sido/sigungu`가 point-in-time history가 아님을 전제로 조사한다.

확인할 것:

- historical availability scope source 존재 여부
- legal institution location history 여부
- historical product channel/region scope 여부

없으면 R2에서:

```text
historical_peer_scope = nationwide_only
```

또는:

```text
status = insufficient_history
```

현재 지역값 carry-back 금지.

---

# 9. R1-A — Pricing Peer Domain 구현

R0-A 계약 승인 후 착수.

## 신규 모듈

권장:

- `institution_rate_reduction.py`
- `pricing_peer_selection.py`
- `pricing_peer_position.py`
- `surface_cost_contract.py`

## 재사용

- canonical rate read path
- stable product id
- existing market position
- institution funding read model for optional enrichment

## 금지 결합

`institution_funding_direct_peer.py`에 pricing logic를 넣지 않는다.

## 테스트

### reduction
- same institution multiple products → 1 representative row
- deterministic tie
- special offer separated
- invalid/missing rate excluded with explicit reason

### pricing peer
- funding missing institution remains peer
- funding known/missing counts correct
- no duplicate institution
- same sector/product/term/scope only

### position
- rank/tie/crowding
- proposal transition
- product market metrics와 peer metrics independent

---

# 10. R1-B — Factual Cost 구현

`surface_cost_contract.py`를 먼저 구현하고 테스트한 뒤 UI에 연결한다.

Acceptance:

1. 같은 notional/Δrate/term이면 sensitivity scenario가 무엇이든 결과 동일
2. inflow prediction 모듈 import 없음
3. zero Δrate → zero cost delta
4. 음/양 Δrate 부호 정확
5. 단위 테스트에 rate percent vs bp 혼동 방지

기본 standardized output:

```text
notional = 100억원
```

optional user notional은 별도 input이고 목표수신 input이 아니다.

---

# 11. R1-C — Strategy Payload

기존 Strategy payload를 깨지 않는 additive contract로 추가한다.

예:

```yaml
relative_pricing:
  status: ready|insufficient_data|policy_disabled
  as_of: ...
  market_position:
    # existing product-level contract reference
  pricing_peer_position:
    policy_id: ...
    policy_version: ...
    pricing_peer_count: ...
    peer_median_rate_pct: ...
    peer_gap_bp: ...
    peer_rank_best: ...
    peer_rank_worst: ...
    peer_tie_count: ...
    peer_within_5bp_count: ...
    peer_within_10bp_count: ...
    higher_rate_peer_count: ...
    funding_join_count: ...
    funding_unjoined_count: ...
    funding_join_ratio: ...
    higher_rate_peer_funding_known_count: ...
    higher_rate_peer_funding_total_krw: ...
  peers:
    - institution_id: ...
      institution: ...
      representative_product_id: ...
      rate_pct: ...
      gap_bp: ...
      funding_balance: null|...
      funding_change_6m_pct: null|...
      funding_status: known|unavailable
  factual_cost:
    contract_version: ...
    standardized_notional_krw_100m: 100
    standardized_surface_interest_delta: ...
```

## Payload guard

- partial funding coverage 명시
- missing funding null
- no predicted inflow fields in R1 block
- no target input state
- policy versions mandatory

---

# 12. R1-D — Strategy Presentation

## UI

상단:

```text
현재금리 / 검토금리 slider
```

카드:

1. 전체 상품시장 위치
2. 주요 pricing peer 위치
3. 경쟁사 표
4. funding known/unknown coverage
5. 100억원당 표면이자 차이
6. optional 비용 계산 기준금액

## 목표 UI 금지

다음 selector/input이 DOM에 없어야 한다.

- target balance
- target net inflow
- target horizon
- recommended rate

## 경쟁사 표

최소:

| 기관 | 대표금리 | 당사 대비 | 수신잔액 | 6M 증감 | funding 상태 |

funding 없으면 기관 행을 유지하고 `자료없음`.

## 라벨

시장 product-level과 pricing institution-level을 구분한다.

예:

```text
전체 상품시장 위치
주요 경쟁기관 위치
```

두 개를 `시장순위` 하나로 뭉개지 않는다.

---

# 13. R1 Verification Gate

코드 PR과 UI PR 각각 검증한다.

## Unit/contract

- targeted pytest
- full pytest
- Ruff
- migration test if schema touched
- `git diff --check`
- magic-number audit

## 핵심 acceptance

- pricing peer institution 중복 0
- funding missing peer 행 보존
- funding known/unknown 합 = pricing_peer_count
- cost calculation predicted-volume 독립
- market_* / peer_* 의미 혼용 없음
- public target input DOM 부재
- no prediction/recommendation field in R1 payload

## Runtime

production-data build로 desktop/mobile browser E2E.

검증할 것:

- 실제 production-format payload
- auth flow 포함
- Strategy 1440 desktop
- mobile 390
- slider 변화
- competitor rows
- 자료없음 렌더링
- standardized cost arithmetic
- no target input

가능하면 preview/production smoke를 분리한다.

---

# 14. R2 — Historical Relative Market Analogue

R0-D evidence가 있는 업권만 활성화한다.

## 입력

- historical representative rate
- historical pricing peer policy
- historical funding if available
- market regime
- product/term/scope

## Point-in-time contract

`as_of=t`에서 t 이후 정보 사용 금지.

필수 테스트:

- future rate leak 실패
- future funding leak 실패
- current region carry-back 실패
- identity effective date 경계
- merger period duplicate 0
- special-offer/product-scope mismatch candidate exclusion

## historical peer recomputation

기본:

```text
versioned deterministic recomputation
```

cache snapshot은 가능하지만 canonical source는 아니다.

## Output

historical analogue 결과는 사실/유사도 설명용이며 causal effect를 주장하지 않는다.

---

# 15. R3 — Private Calibration

public repo에 내부 raw를 넣지 않는다.

## R3-0 Data Safety PR 선행

별도 PR:

- `.gitignore`: `data/internal/`, `private/` 등 확정 intake path
- CI forbidden-path scan
- artifact path scan
- sensitive-column scan
- public payload private-field scan

경로명은 실제 private ingestion architecture 확정 후 최소 범위로 정한다.

## Feature whitelist 확장

`inflow_calibration_protocol.FEATURE_GROUPS["pricing"]`에 기존 의미를 보존한 채 신규 peer feature를 별도 추가한다.

후보:

```text
peer_gap_bp
peer_rank_best
peer_rank_worst
peer_tie_count
peer_within_5bp_count
peer_within_10bp_count
market_within_10bp_count
```

contract test:

- peer value를 market field에 넣으면 실패
- unknown feature fail-closed 유지

## OOS

기존 temporal OOS contract를 재사용한다.

모델 promotion 없이 R4로 가지 않는다.

---

# 16. R4 — Goal-based Inverse

## 전제

다음이 모두 참일 때만 UI/solver 활성화:

- private champion exists
- lifecycle/promotion status active
- temporal OOS gate passed
- required feature support present
- target support gate passed
- response sanity passed

## 목표 UI

R4에서 처음 렌더링:

```text
목표 순수신
목표 기말잔액
목표 기간
```

## Solver

신규 모듈로 분리.

예:

`goal_rate_inverse_solver.py`

forward model을 호출할 뿐 자체 예측식을 갖지 않는다.

## Out-of-support

training/validation support의 명시적 범위를 벗어나면:

```text
status = target_out_of_support
rate_range = null
```

## Non-monotonic

rate grid에서 목표 충족 집합이 불연속이면:

- 복수 feasible interval을 계산
- 안정성 기준이 부족하면 `non_monotonic_response`
- 최저금리 한 점으로 압축하지 않음

## Output

허용:

- feasible rate range
- uncertainty range
- target gap
- model version/as-of
- support status

금지:

- 달성 보장
- 정답/최적금리 표현
- support 밖 외삽

---

# 17. 업권별 Gate

## Savings Bank

R1 pricing peer 전에:

- 79/66 evidence 확인됨
- R0-C exact remediation 수행
- remediation 후 pricing population census
- N 후보 calibration

`N=16` 복사 금지.

## NH Local

- existing funding peer N=16 유지
- pricing peer N 별도 설계
- 2025-12 historical rate evidence 없으면 R2 historical analogue 비활성

## CU

v2 권고:

- valid rate → pricing peer 가능
- institution funding unavailable → 행 유지, funding null

funding 기반 합계는 known-only.

## KFCC

existing provenance/coverage gate를 우선한다.

---

# 18. 사용자 승인 필요 정책

구현 시작 전 다음 정책을 사용자가 명시적으로 승인하거나 수정해야 한다.

```yaml
D1_institution_rate_reduction:
  proposal: matched scope max rate; special offer separate radar

D2_cost_notional:
  proposal: 100억원 standardized + optional user input

D3_pricing_availability_scope:
  proposal: product availability/join scope, not funding-peer geography

D4_cu_missing_funding:
  proposal: keep pricing peer row, funding unavailable

D5_goal_ui_activation:
  proposal: R4 promoted champion only

D6_savings_peer_n:
  proposal: defer until post-remediation population calibration
```

D6는 승인으로 숫자를 정하는 것이 아니라 evidence gate를 승인하는 항목이다.

---

# 19. 완료 판정

각 Stage 완료보고는 반드시 다음으로 나눈다.

## 완료

실제로 코드/테스트/runtime evidence로 확인된 항목.

## 미검증

환경/secret/data access 부족으로 확인하지 못한 항목.

## 남은 작업

다음 stage gate.

PR 생성/CI success 자체를 기능동작 완료로 쓰지 않는다.

자동 merge 금지.

---

# 20. 이번 문서 브랜치의 현재 범위

현재 브랜치에서는 **문서/evidence만 수정**한다.

코드, DB, migration, workflow, UI는 변경하지 않는다.

Claude 재리뷰에서 `APPROVE FOR IMPLEMENTATION PLANNING` 또는 동등한 승인 판정을 받은 뒤에도, 사용자 정책 D1~D5를 확정하고 구현 branch를 새로 만든다.
