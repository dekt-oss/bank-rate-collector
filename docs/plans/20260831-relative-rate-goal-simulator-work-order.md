# 상대금리 기반 목표형 금리결정 시뮬레이터 — 작업지시서

```yaml
document_type: implementation_work_order
status: draft_for_review
date: 2026-08-31
repository: dekt-oss/bank-rate-collector
branch: docs/relative-rate-goal-simulator-20260831
code_change_in_this_branch: false
production_strategy_release_gate: unchanged_off
merge_policy: explicit_user_approval
internal_data: prohibited_in_public_repo
```

관련 기획: `docs/plans/20260831-relative-rate-goal-simulator-plan.md`

---

# 0. 작업 목표

Strategy의 금리결정 UX를 장기적으로 다음 흐름으로 전환한다.

```text
목표 수신액/순수신 + 목표기간
→ 검증된 내부모형이 필요금리 범위를 역산
→ 후보금리를 움직이며 경쟁사 위치·수신규모·비용·예상수신을 함께 확인
→ 과거의 유사한 상대금리 상황을 근거로 확인
→ 사람이 최종 금리를 결정
```

단, 현재 저장소에는 당사 실제 신규취급액·만기·재예치 등 내부 outcome 데이터가 없으므로 **지금 구현 가능한 범위와 미래 calibrated 범위를 분리**한다.

현재 구현의 1차 목표는:

> **후보금리를 움직였을 때 주요 경쟁사 대비 당사 위치와 경쟁사 수신규모가 어떻게 달라지는지 보여주는 factual Relative Market Simulator**

이다.

내부자료 보정 전에는 `목표 +300억 → 권장금리 3.55%` 같은 결과를 절대 출력하지 않는다.

---

# 1. 먼저 읽을 기준 문서

구현자는 작업 전 반드시 다음을 최신 main 기준으로 읽는다.

1. `AGENTS.md`
2. `CLAUDE.md`
3. `README.md`
4. `docs/specs/CURRENT.md`
5. `docs/specs/20260818-deposit-pricing-decision-cockpit-v3.md`
6. `docs/specs/20260822-public-structural-v2-decision-cockpit-final.md`
7. `docs/specs/20260825-private-inflow-calibration-protocol-v1.md`
8. `docs/specs/20260818-internal-deposit-data-request-v1.md`
9. 본 기획/작업지시서

문서와 최신 코드/runtime이 다르면 추측하지 말고 차이를 Evidence Gate로 기록한다.

---

# 2. 현재 구현 경로 — 재사용 우선

현재 저장소에는 이미 다음 기반이 있다. 새 엔진을 중복 구현하지 않는다.

## 시장 위치

- `src/rate_monitor/services/public_structural_v2_market_position_service.py`
  - anchor product replace 방식
  - 공동순위 `rank_best/rank_worst`
  - median/top25/top10/max와의 gap
  - ±5bp/±10bp crowding
  - 금리 변경에 따른 `newly_outpriced`, `newly_lost_to` 등 transition

## 현재 public 구조 시뮬레이션

- `src/rate_monitor/services/inflow_prediction_service.py`
- `src/rate_monitor/services/public_structural_v2_inflow_service.py`
- `src/rate_monitor/services/public_structural_v2_forecast_provider.py`
- `src/rate_monitor/services/public_structural_v2_decision_contract.py`
- `src/rate_monitor/services/public_structural_v2_cockpit_presentation.py`

중요: 현재 `inflow_prediction_service.py`의 계수는 **은행별 실적 보정치가 아니라 uncalibrated stress assumptions**이다. 목표역산 엔진의 champion으로 승격하지 않는다.

## 내부모형 보정 기반

- `src/rate_monitor/services/inflow_asof_feature_contract.py`
- `src/rate_monitor/services/inflow_calibration_protocol.py`
- `src/rate_monitor/services/inflow_backtest_evaluation.py`
- `src/rate_monitor/services/inflow_private_model_registry_contract.py`
- `src/rate_monitor/services/internal_calibration_intake_service.py`

## Direct Peer / 기관별 수신

- `src/rate_monitor/services/institution_funding_direct_peer.py`
- `src/rate_monitor/services/institution_funding_direct_peer_db.py`
- `src/rate_monitor/services/institution_funding_read_model.py`
- `src/rate_monitor/services/institution_funding_read_model_db.py`
- `src/rate_monitor/services/institution_funding_position_service.py`
- `src/rate_monitor/services/institution_funding_strategy_payload.py`

현재 Direct Peer는 exact sector/month population에서 지역 tier(`sigungu → sido → nationwide`)를 선택한 뒤 log-balance 거리로 peer를 고른다. identity를 합치거나 누락 history를 보간하지 않는다. 이 계약을 보존한다.

## Rate × Funding

- `src/rate_monitor/services/rate_funding_matrix_service.py`
- `src/rate_monitor/services/rate_funding_matrix_presentation.py`

## Strategy 조립/화면

- `src/rate_monitor/services/strategy_contract_service.py`
- `src/rate_monitor/services/strategy_decision_cockpit.py`
- `src/rate_monitor/services/strategy_external_context_service.py`
- `src/rate_monitor/services/strategy_service.py`
- `src/rate_monitor/services/strategy_service_base.py`
- `src/rate_monitor/services/strategy_workspace_presentation.py`
- `src/rate_monitor/services/strategy_mobile_responsive_presentation.py`
- `src/rate_monitor/services/site_service.py`

---

# 3. 절대 불변 규칙

이번 기능 때문에 아래를 우회하거나 다시 정의하지 않는다.

1. stable institution/product identity
2. source precedence
3. official evidence / provenance
4. missing value는 0이 아님
5. current rate를 historical month로 carry-back 금지
6. nearest-month interpolation 금지
7. 이름 유사성만으로 기관 자동 merge 금지
8. Rate × Funding을 인과효과로 설명 금지
9. 내부 raw 데이터 public repository 저장 금지
10. public structural stress를 calibrated forecast라고 표현 금지

---

# 4. Phase R0 — 데이터 readiness와 계약 고정

UI부터 만들지 않는다. 아래가 먼저다.

## R0-1. 저축은행 identity 79/79 exact coverage

현재 source funding에는 79개 개별 저축은행이 있지만 Strategy exact mapped population은 66개 수준이다.

해야 할 일:

- 13개 누락 source identity의 `fncoCd` / CRNO / 기존 canonical institution 관계 조사
- 공식 directory/evidence로 exact mapping
- 기존 institution/source link architecture를 따라 저장
- 이름만 보고 mapping 금지
- 79개 개별기관 합과 ECOS total reconciliation 재검증

Gate:

```text
source individual institutions = 79
canonical exact mapped = 79
aggregate sector row excluded
unresolved name-only mapping = 0
```

이 Gate 전에는 저축은행 peer/funding simulator를 production-ready로 선언하지 않는다.

## R0-2. NH historical rate evidence 조사

현재 NH는 current rate와 2025-12 funding은 있으나 aligned historical rate가 없다.

해야 할 일:

- R2 raw evidence / immutable artifact / 공식 source history에서 과거 시점 금리 존재 여부 조사
- historical source timestamp와 상품/기관 identity 검증
- 발견되면 point-in-time rate history로 정규화
- 없으면 `historical_rate_unavailable` 유지

금지:

- 현재 2026 금리를 2025-12에 붙이기
- 유사기관 금리로 대체
- 업권 평균으로 추정

## R0-3. 신협 funding readiness

공식 exact finance endpoint가 확정되기 전에는:

```text
credit_union competitor funding = unavailable
```

을 유지한다.

후보 데이터 848/828/20/633 등의 존재 자체를 canonical evidence로 승격하지 않는다.

## R0-4. Peer policy versioning

업권별 peer 정책에 최소 다음 메타를 둔다.

```text
peer_policy_id
peer_policy_version
sector
requested_count
scope_fallback_rule
size_distance_metric
as_of_rule
```

NH N=16을 저축은행에 복사하지 않는다.

저축은행은 79/79 coverage 이후 N 후보를 다시 평가해 정책을 확정한다.

---

# 5. Phase R1 — Public Relative Market Simulator

내부자료 없이 production에 올릴 수 있는 목표 범위다.

## R1-1. 입력

- 상품종류
- 가입기간
- 지역/업권 조건
- 후보금리 `candidate_rate_pct`

현재 Strategy의 canonical anchor/product universe 선택 계약을 재사용한다.

## R1-2. Relative Market Contract

시장 전체 위치와 Direct Peer 위치를 구분한다.

### 전체 시장 factual position

기존 `public_structural_v2_market_position_service.py`를 최대한 재사용한다.

### Direct Peer position — 신규/확장 계약

최소 출력:

```yaml
status: ready | insufficient_peer_coverage | funding_unavailable | rate_unavailable
candidate_rate_pct: 3.55
peer_policy_id: string
peer_policy_version: string
peer_as_of: YYYY-MM-DD_or_month
peer_count: integer
peer_rate_coverage_count: integer
peer_funding_coverage_count: integer
peer_median_rate_pct: number|null
peer_gap_bp: number|null
rank_best: integer|null
rank_worst: integer|null
tie_count: integer
within_5bp_count: integer
within_10bp_count: integer
higher_rate_peer_count: integer
lower_rate_peer_count: integer
newly_outpriced_count: integer
newly_lost_to_count: integer
higher_rate_peer_funding_total_krw: number|null
lower_rate_peer_funding_total_krw: number|null
peer_funding_total_krw: number|null
```

규칙:

- funding coverage가 불충분하면 aggregate funding 값은 `null`, 0 금지
- rate와 funding의 as-of가 다르면 각각 명시
- 합산금액은 exact canonical institution identity로 join된 row만 포함
- coverage numerator/denominator를 함께 노출 가능해야 함

## R1-3. Competitor row contract

각 peer에 최소:

```yaml
institution_id: canonical stable id
institution_name: display name
sector: string
peer_scope: sigungu|sido|nationwide
peer_distance: number|null
rate_pct: number|null
rate_as_of: date|null
gap_vs_candidate_bp: number|null
relation: ahead|behind|tied|rate_unavailable
funding_balance_krw: number|null
funding_as_of: month|null
funding_growth_6m_pct: number|null
identity_mapping_status: exact|unavailable
```

필요 시 source/evidence drill-down용 reference를 별도 field로 연결한다.

## R1-4. Slider 동작

사용자가 후보금리를 바꾸면 새 수집을 하지 않고 현재 factual snapshot을 기준으로 즉시 재계산한다.

동적으로 갱신할 값:

- peer median 대비 gap
- 공동순위
- 당사보다 높은/낮은 peer 수
- ±5bp/±10bp crowding
- 새로 앞서는 peer / 뒤처지는 peer
- 경쟁사 목록의 당사 대비 gap/relation
- higher/lower peer funding aggregate — coverage Gate 충족 시
- 표면이자비용

### 표면이자비용 규칙

새 공식을 임의로 만들지 않는다.

기존 `simple_surface_interest_total_delta` 또는 Public Structural v2의 현재 canonical cost semantics를 재사용한다. 요구 UX가 기존 계약으로 표현되지 않으면 먼저 별도 cost contract 문서를 작성하고 승인받는다.

## R1-5. Public UI 표현

현재 단계의 제목 예:

> 검토금리별 경쟁시장 위치

허용:

- `3.55% 적용 시 Direct Peer 16곳 중 공동 4~6위`
- `Peer 중앙값 대비 +13bp`
- `당사보다 높은 peer 3곳`
- `그 3곳의 확인 가능한 수신잔액 합계 1.8조원`

금지:

- `추천금리 3.55%`
- `+300억 달성 가능`
- `예상 순수신 +280억`
- `달성확률 84%`

---

# 6. Phase R2 — Historical Relative Context

공식 point-in-time rate evidence가 확보된 업권부터 진행한다.

## R2-1. Historical Peer Snapshot

현재 peer를 과거에 그대로 적용하지 않는다.

과거 시점의 정보로 peer set을 재구성하고 최소 다음을 versioned snapshot 또는 deterministic recomputable contract로 남긴다.

```yaml
as_of: historical date/month
sector: string
anchor_institution_id: string
peer_policy_id: string
peer_policy_version: string
peer_institution_ids: []
peer_scope_by_institution: {}
rate_coverage_count: integer
funding_coverage_count: integer
snapshot_status: ready|insufficient_history
```

필수:

- 과거 당시 funding balance를 size-distance에 사용
- 당시 없던 미래정보 사용 금지
- 기관 합병/명칭변경도 canonical identity history 기준
- 현재 기관규모를 과거 peer 선정에 사용 금지

## R2-2. Historical Analogue Finder

검색 기준 후보:

- `peer_gap_bp`
- peer rank range
- crowding ±5bp/±10bp
- 시장금리 regime
- 상품 가입기간
- seasonality
- 내부자료가 들어온 이후 maturity/own-flow context

결과에는 왜 유사사례로 선택됐는지 component distance를 설명 가능하게 한다.

내부 outcome이 없는 현재에는 `시장환경 유사사례`라고만 표현하고 당사 수신결과를 추정하지 않는다.

---

# 7. Phase R3 — Private Internal Calibration

내부 데이터는 public repo에 넣지 않는다.

기존 `20260825-private-inflow-calibration-protocol-v1.md`와 다음 코드를 확장/재사용한다.

- `inflow_asof_feature_contract.py`
- `inflow_calibration_protocol.py`
- `inflow_backtest_evaluation.py`
- `inflow_private_model_registry_contract.py`
- `internal_calibration_intake_service.py`

핵심 feature 후보:

- own rate
- rate change bp
- Direct Peer median gap
- peer rank best/worst
- tie count
- within 5bp/10bp count
- peer rate distribution
- own maturity amount
- own baseline new money
- own rollover
- market regime

기존 public stress model은 challenger/reference로 유지한다.

Private model이 champion이 되려면 최소:

- train/validation/test temporal split
- OOS backtest
- leakage test
- feature as-of contract
- calibration quality
- stability by rate regime
- human promotion review

을 통과해야 한다.

---

# 8. Phase R4 — Goal-based Pricing / Inverse Solver

R3의 private calibrated champion이 승인된 뒤에만 구현한다.

## R4-1. Forward model 먼저

```text
candidate rate + relative market context + internal current state
→ predicted new money / rollover / net inflow / ending balance + uncertainty
```

이 forward model의 검증이 선행 조건이다.

## R4-2. Inverse solver

목표를 입력받아 후보금리 grid에서 forward model을 반복 호출한다.

```text
target net inflow / ending balance + horizon
→ candidate rate grid
→ calibrated forecasts
→ feasible region 탐색
→ 필요한 금리 범위 제시
```

inverse solver가 자체 예측식을 가지면 안 된다.

## R4-3. 출력

단일 `정답금리`보다:

- feasible rate range
- center scenario
- predicted range
- competitor position
- funding cost
- target shortfall/excess
- historical analogues

을 함께 보여준다.

## R4-4. Fail-closed

다음이면 금리범위를 출력하지 않는다.

- champion 없음
- feature freshness 실패
- peer coverage 미달
- target out-of-support
- response curve sanity/monotonicity Gate 실패
- uncertainty 과다
- model registry status가 promoted가 아님

---

# 9. Strategy 화면 최종 계층

최종 calibrated 모드 기준:

```text
A. 목표 수신 / 목표기간
B. 필요한 금리 범위 + 불확실성
C. 후보금리 What-if slider
D. 주요 경쟁사: 금리 + 수신잔액 + 6M 증감
E. 과거 유사 상대시장 사례
F. Rate × Funding Matrix
G. 지역/시장 상세 + 원본근거
```

현재 public-only 단계에서는 A/B를 예측기처럼 활성화하지 않는다.

현재의 실제 1차 화면은 C/D 중심으로 구현한다.

---

# 10. 테스트 요구사항

## Pure logic

- exact tie 공동순위
- top10/top25 cutoff 경계
- ±5bp/±10bp crowding
- 5bp/10bp slider transition
- peer median even/odd
- peer shortfall
- funding null propagation
- missing funding != 0
- duplicate stable institution id fail
- sector/month mismatch fail

## Identity / data

- 저축은행 aggregate row가 peer universe에 들어오지 않음
- source 79 ↔ canonical 79 exact mapping Gate
- name-only merge 없음
- NH historical current-rate carryback 없음
- CU funding unavailable 유지

## Historical

- point-in-time peer snapshot only
- future funding/rate leakage fail
- historical rate unavailable state 보존
- policy version 차이를 snapshot에 기록

## Strategy contract/UI

- candidate slider가 factual values만 갱신
- public mode에 target-based recommended rate가 렌더링되지 않음
- null funding은 `자료 없음`
- competitor row stable id 유지
- desktop/mobile layout smoke
- production-data Strategy build
- authenticated production Chrome smoke

## Private future

- temporal OOS backtest
- champion/challenger comparison
- inverse result reproduces forward forecast
- out-of-support fail-closed
- uncertainty Gate

---

# 11. 구현 PR 분리 원칙

한 PR에 전부 넣지 않는다.

권장 순서:

1. **R0-A Savings identity remediation**
2. **R0-B Historical-rate evidence/readiness**
3. **R0-C Peer policy/version contract**
4. **R1-A Direct Peer relative market domain/service**
5. **R1-B Strategy payload + competitor table**
6. **R1-C Slider UX + desktop/mobile runtime validation**
7. **R2 Historical peer/analogue**
8. **R3 Private calibration** — 내부자료 확보 후
9. **R4 Goal-based inverse simulator** — champion 승인 후

각 PR은 current state와 target state를 명확히 쓰고, CI 성공만으로 runtime 성공을 주장하지 않는다.

---

# 12. Definition of Done

## Public Relative Market Simulator 완료

다음이 모두 충족돼야 한다.

- 후보금리 변경 시 Direct Peer 상대위치가 deterministic하게 계산됨
- 경쟁사별 rate/funding이 exact identity로 결합됨
- coverage/missing이 명시됨
- 잘못된 수신 0 대체 없음
- 저축은행 identity Gate 충족 또는 해당 업권 fail-closed
- NH historical 정보가 없으면 historical 기능 비활성
- public 화면에 목표기반 추천/예측 표현 없음
- Strategy production-data build 통과
- desktop/mobile Chrome smoke 통과
- production smoke 통과

## Goal-based Simulator 완료

위 조건 + 다음이 필요하다.

- private calibrated champion promoted
- 목표/기간 입력 → feasible rate range
- forward/inverse parity 검증
- uncertainty 표시
- historical analogues point-in-time 검증
- public/private 데이터 경계 검증
- human decision remains final

---

# 13. 이번 문서 브랜치의 완료조건

이 브랜치에서는 **코드를 구현하지 않는다.**

완료조건:

- 기획안 작성
- 본 작업지시서 작성
- Claude 적대적 리뷰 프롬프트 작성
- `CURRENT.md`에 `draft_for_review`로 연결
- main 대비 diff가 docs-only인지 확인
- Claude 리뷰 전에는 구현 브랜치로 사용하지 않음
