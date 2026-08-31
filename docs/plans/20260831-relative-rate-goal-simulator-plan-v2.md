# 상대금리 기반 목표형 금리결정 시뮬레이터 — 기획안 v2

```yaml
document_type: product_plan
status: draft_for_rereview
date: 2026-08-31
repository: dekt-oss/bank-rate-collector
branch: docs/relative-rate-goal-simulator-20260831
supersedes_for_review:
  - docs/plans/20260831-relative-rate-goal-simulator-plan.md
production_strategy_release_gate: on_canonical_site_writer
merge_policy: explicit_user_approval
public_mode: factual_only
private_goal_inverse: disabled_until_promoted_champion
internal_data: prohibited_from_public_repo_and_artifacts
```

---

# 0. 결론

최종 제품 목표는 다음 질문에 답하는 것이다.

> 다음 1~3개월 동안 필요한 수신을 확보하려면, 현재 경쟁시장과 당사 실적을 기준으로 어느 수준의 금리를 검토해야 하는가?

그러나 **현재 public 데이터만으로는 이 질문에 예측 숫자로 답하지 않는다.**

이번 설계는 두 제품 상태를 명확히 분리한다.

## 현재: Factual Relative Market Simulator

사용자가 검토금리를 움직이면 실제 수집 가능한 사실만 갱신한다.

- 전체 시장 product-level 위치
- institution-level pricing peer 위치
- pricing peer 금리
- funding이 확인된 경쟁사의 수신잔액/증감
- funding coverage와 미확인 기관 수
- 제안금리 변화에 따른 경쟁사 우위/열위 전환
- 고정 notional 기준 표면이자 차이

**목표수신 입력, 예상수신, 추천금리, 필요금리 범위는 렌더링하지 않는다.**

## 향후: Private Calibrated Goal Simulator

내부 신규취급/만기/재예치/순수신 데이터가 들어오고 temporal OOS 검증과 model promotion을 통과한 경우에만 다음을 추가한다.

- 목표 수신액/기간 입력
- forward forecast
- target support gate
- inverse solver
- feasible rate range
- 불확실성/예측범위
- historical analogue

핵심은 `상대금리`를 중요한 설명축으로 쓰되, **factual fact와 calibrated forecast를 같은 신뢰도처럼 보이게 섞지 않는 것**이다.

---

# 1. 리뷰 반영으로 바뀐 핵심

Claude 적대적 리뷰의 P0 4건을 모두 반영한다.

1. Strategy는 이미 production surface다.
2. R1의 표면이자비용은 uncalibrated predicted volume에서 완전히 분리한다.
3. funding peer와 pricing peer를 분리한다.
4. product-level market position과 institution-level pricing peer position을 분리한다.

또한 다음을 추가한다.

- `peer_*` feature와 `market_*` feature를 별도 의미로 관리
- public mode에서 목표입력 UI 자체를 제거
- historical region look-ahead bias 방지
- 내부자료의 git/artifact 유출을 기계적으로 막는 gate
- inverse solver 비단조 응답 fail-closed
- 저축은행 79/66 identity gap을 production artifact evidence로 고정

---

# 2. 현재 저장소 사실

## 2.1 Strategy는 production surface

`AGENTS.md`와 canonical site-writer workflow가 Strategy production 발행을 현재 계약으로 정의한다.

따라서 이 설계의 R1 public factual 변경은 **merge 후 production에 노출될 수 있는 변경**으로 취급한다.

`Release Gate OFF`라는 과거 표현은 사용하지 않는다.

## 2.2 현재 inflow engine은 calibrated forecast가 아니다

현재 `inflow_prediction_service.py`의 sensitivity scenario는 내부실적 보정 전 구조 stress band다.

따라서 R1에서 다음을 쓰지 않는다.

- predicted_new_money
- predicted_rollover
- predicted_total
- 그 predicted volume을 원금으로 사용하는 비용

## 2.3 기존 market position은 product-level이다

Public Structural v2의 factual market position은 `product_id` 모집단을 사용한다.

이 계약은 유지한다.

한 기관이 여러 상품을 가지면 product-level 모집단에 여러 행이 존재할 수 있다. 이를 이번 작업에서 몰래 institution-level로 바꾸지 않는다.

## 2.4 기존 Direct Peer는 funding peer다

현재 `institution_funding_direct_peer*`는 funding observation과 log-balance 근접성을 사용하는 funding peer이며 NH local만 production enabled다.

따라서 pricing 경쟁사 선택에 그대로 쓰지 않는다.

## 2.5 저축은행 funding identity gap은 실측됨

`docs/evidence/20260831-savings-bank-funding-identity-coverage.md`에 production artifact evidence를 기록했다.

2026-03 기준:

```text
source institutions   79
exact mapped          66
unmapped              13
institution sum       99.573991조원
ECOS total            99.574000조원
reconciliation        aligned
```

즉 source coverage가 아니라 identity mapping gap이다.

---

# 3. 제품의 세 가지 비교층

이번 설계에서 `시장`, `pricing peer`, `funding peer`를 하나로 합치지 않는다.

## 3.1 Market Position — 전체 상품시장

기존 Public Structural v2를 그대로 사용한다.

```text
key             product_id
population      현재 Strategy 비교상품 모집단
purpose         제안상품의 전체 시장 위치
examples        공동순위, Top10/25 cutoff, ±5/10bp crowding
```

기존 `public_structural_v2_market_position_service.py`를 재사용한다.

## 3.2 Pricing Peer — 금리 의사결정 경쟁기관

신규 institution-level 비교층이다.

```text
key             institution_id
population      동일 pricing scope에서 유효한 rate가 있는 기관
purpose         주요 경쟁기관 대비 상대금리 위치
funding         optional enrichment
```

pricing peer 자격은 funding 보유 여부로 결정하지 않는다.

## 3.3 Funding Peer — 수신규모/성장 비교기관

기존 Direct Peer를 유지한다.

```text
key             institution_id
population      canonical funding observation이 있는 기관
purpose         수신규모·성장 상대비교
selection       region + log balance proximity
```

이 집합을 pricing peer로 재사용하지 않는다.

---

# 4. Institution Rate Reduction 계약

pricing peer를 만들기 전에 한 기관의 여러 상품을 institution-level 대표 rate 하나로 축약하는 정책이 필요하다.

## 4.1 설계 기본안

```yaml
institution_rate_reduction:
  rule: max_rate_within_matched_scope
  matched_on:
    - sector
    - product_type
    - term_months
    - availability_scope
  special_offer:
    core_pricing_peer: exclude
    separate_market_radar: include
  tie_break: stable_product_id_ascending
  output:
    - institution_id
    - representative_product_id
    - rate_pct
    - rate_as_of
    - selection_reason
```

### 이유

- 기존 Strategy가 최고금리를 핵심 비교축으로 사용한다.
- 한 기관 상품 수가 많다고 institution-level peer에서 여러 표를 차지하지 않게 한다.
- 특판은 일반 pricing peer와 시장 benchmark 목적이 다르므로 분리한다.
- tie-break를 stable product identity로 결정론화한다.

이 기본안은 사용자 승인 전 `proposed` 상태다.

## 4.2 금지

- 이름 유사도만으로 institution merge
- product-level market position 계약 변경
- special offer를 일반상품과 섞고 라벨을 숨김
- join/availability scope가 다른 상품을 동일 peer로 임의 비교

---

# 5. Pricing Peer 정책

## 5.1 자격

pricing peer의 최소 자격:

1. 같은 sector
2. 같은 product type
3. 같은 term
4. 현재 시점에 유효한 대표 rate
5. 동일 pricing availability scope
6. exact canonical institution identity

funding 관측은 자격요건이 아니다.

## 5.2 Availability scope

funding peer의 `sigungu → sido → nationwide` fallback을 복사하지 않는다.

권고 기본안:

- 전국 비대면 가입 가능 → nationwide
- 지역 제한 가입 → 해당 canonical availability scope
- 가입가능범위 증거가 없음 → 임의 지역추정 금지

즉 경쟁범위는 `기관 소재지`보다 `상품 가입가능범위`를 우선한다.

## 5.3 Funding enrichment

pricing peer 행은 funding이 없어도 남아야 한다.

payload 최소 계약:

```yaml
pricing_peer_count: integer
funding_join_count: integer
funding_join_ratio: number
funding_unjoined_count: integer
higher_rate_peer_count: integer
higher_rate_peer_funding_known_count: integer
higher_rate_peer_funding_total_krw: number|null
```

화면에서는 반드시 `funding 미확인 N개`를 병기한다.

known-only funding 합계를 전체 경쟁시장 합계처럼 표현하지 않는다.

---

# 6. 상대금리 지표

## 6.1 Pricing Peer Gap

```text
peer_gap_bp
= proposal_rate - pricing_peer_median_rate
```

단 median만 보여주지 않는다.

함께 제공:

- peer rank best/worst
- tie count
- higher/lower peer count
- within ±5bp / ±10bp count
- newly outpriced / newly lost-to institution count
- funding-known higher-rate peer count
- funding-known higher-rate peer balance total
- funding-unjoined peer count

## 6.2 Market vs Peer 의미 분리

기존 `market_*`는 product 모집단 의미를 유지한다.

신규 `peer_*`는 institution pricing peer 모집단 의미다.

두 계열을 같은 feature 이름으로 저장하지 않는다.

예:

```text
market_gap_bp         product market 기준
peer_gap_bp           pricing peer institution 기준
```

---

# 7. R1 Factual Cost 계약

## 7.1 기존 predicted volume 비용 금지

R1에서는 `inflow_prediction_service.py`의 predicted_total 기반 비용을 사용하지 않는다.

## 7.2 허용 산식

```text
surface_interest_delta
= notional
  × (proposal_rate - current_rate) / 100
  × term_months / 12
```

이 값은 **고정 가정원금에 대한 순수 산술**이다.

## 7.3 UX 기본안

기본 표시:

```text
100억원당 표면이자 차이
```

선택 기능:

```text
비용 계산 기준금액 [      ] 억원
```

입력 시:

```text
300억원 기준 표면이자 차이
```

당사 현재잔액, 예상수신, predicted_total을 자동 notional로 사용하지 않는다.

## 7.4 한계조달원가

Public Structural v2가 초기 UI에서 금지한 `한계조달원가`는 이번 R1/R2에서 사용하지 않는다.

FTP/ALM economic cost와 구분되는 별도 명세와 사용자 승인이 있기 전 부활시키지 않는다.

---

# 8. R1 Public UX

R1은 **목표형 화면이 아니다.**

## 8.1 상단

```text
현재금리 3.45%
검토금리 3.55%  [slider]
```

동시에:

### 전체 시장
- product-level 공동순위
- top10/top25 cutoff
- ±5/10bp crowding

### Pricing Peer
- peer median gap
- institution-level 공동순위
- 높은/낮은 peer 수
- 경쟁사별 대표금리
- funding known/unknown

### 비용
- 100억원당 표면이자 차이
- optional notional 입력

## 8.2 절대 금지

R1/R2 public Strategy DOM에 다음을 렌더링하지 않는다.

- 목표수신 입력
- 목표기간 입력
- 예상수신
- 예상순수신
- 추천금리
- 필요금리
- 목표 달성확률
- calibrated confidence/prediction interval처럼 보이는 값

---

# 9. Historical Relative Market Analogue

## 9.1 목적

잘못된 질문:

> 과거 당사가 3.50%였을 때 수신은 어땠나?

목표 질문:

> 과거에 당사의 경쟁사 대비 상대위치가 현재 검토안과 비슷했던 시점에서 수신이 어떻게 움직였나?

## 9.2 Point-in-time 원칙

과거 analogue는 당시 정보만 사용한다.

- 당시 rate
- 당시 funding balance
- 당시 canonical identity link
- 당시 product scope
- 당시 availability/region scope

오늘의 current rate나 current funding을 carry-back하지 않는다.

## 9.3 Region look-ahead 방지

현재 `institutions.region_sido/sigungu`는 point-in-time history가 아니다.

따라서 historical region_as_of가 없으면:

```text
historical_peer_scope = nationwide_only
```

또는:

```text
status = insufficient_history
```

현재 지역값을 과거에 소급해 peer를 좁히는 것은 금지한다.

## 9.4 Snapshot 정책

기본은 versioned deterministic recomputation이다.

저장할 경우 snapshot은 cache일 뿐 source of truth가 아니다.

각 결과는 최소 다음을 기록한다.

- peer_policy_id/version
- rate_reduction_policy_id/version
- as_of
- input identity revision
- funding revision/as_of
- rate as_of
- historical scope mode

---

# 10. Private Calibration

내부자료는 public repository/artifact에 저장하지 않는다.

## 10.1 Feature naming

R3에서 기존 market feature 의미는 유지한다.

추가 후보:

```text
peer_gap_bp
peer_rank_best
peer_rank_worst
peer_tie_count
peer_within_5bp_count
peer_within_10bp_count
market_within_10bp_count
```

`peer_*` 값을 `market_*` 컬럼에 넣지 않는다.

## 10.2 Required private safety gates

R3 전에:

- `.gitignore` private/internal intake path
- CI forbidden path scan
- artifact upload scan
- forbidden sensitive field scan
- public payload private-field scan

을 구현한다.

## 10.3 Promotion

inverse solver는 다음이 모두 통과한 promoted champion만 호출한다.

- temporal OOS
- target support
- calibration lifecycle/promotion
- data sufficiency
- response sanity

---

# 11. Goal Inverse — R4 전용

## 11.1 목표입력 UI 시점

목표수신/기간 입력은 **R4에서 처음 등장**한다.

## 11.2 Forward first

inverse solver가 자체 예측식을 갖지 않는다.

```text
target
  ↓
promoted forward model
  ↓
rate grid evaluation
  ↓
feasible region
  ↓
rate range
```

## 11.3 Out-of-support

학습/검증 support 밖 목표는 외삽 추천하지 않는다.

```text
status = target_out_of_support
```

필요금리 범위를 출력하지 않는다.

## 11.4 Non-monotonic response

forward response가 비단조이면 최소금리 하나를 억지로 고르지 않는다.

- feasible region이 복수면 구간을 분리
- 안정적 구간 판정이 안 되면 `non_monotonic_response`
- fail-closed 시 추천범위 미출력

---

# 12. 업권별 현재 처리

## 저축은행

- funding source 79 확인
- exact mapping 66 확인
- 13 identity remediation 선행
- pricing peer N은 remediation + distribution calibration 후 결정

## 농·축협

- funding peer N=16은 기존 calibration 유지
- pricing peer N에 자동 복사하지 않음
- historical 2025-12 rate evidence 별도 조사

## 신협

설계 기본안:

- valid rate가 있으면 pricing peer 포함 가능
- institution funding은 optional → 없으면 `자료없음`
- funding-based aggregate에는 known-only coverage 노출

## 새마을금고

기존 source/provenance/coverage contract를 먼저 존중하며, pricing peer 활성화는 해당 업권 rate identity/availability evidence가 충분한 경우만 한다.

---

# 13. 사용자 정책 결정이 필요한 항목

다음은 기술 증거만으로 최종 확정하지 않는다.

| ID | 정책 | v2 권고 기본안 | 상태 |
|---|---|---|---|
| D1 | institution 대표 rate | matched scope 내 max rate, 특판 별도 radar | 사용자 승인 필요 |
| D2 | factual cost notional | 100억원당 + optional user input | 사용자 승인 필요 |
| D3 | pricing peer 지역범위 | 상품 가입가능범위 기준 | 사용자 승인 필요 |
| D4 | 신협 funding 결측 | pricing peer 유지 + funding 자료없음 | 사용자 승인 필요 |
| D5 | 목표입력 UI | R4 champion 이후 최초 노출 | 사용자 승인 필요 |
| D6 | 저축은행 N | 실측/calibration 전 미정 | evidence gate |

구현자가 이 항목을 임의로 확정하지 않는다.

---

# 14. Success Criteria

이 설계가 성공했다고 볼 수 있는 최소 조건:

1. R1 public 화면에 예측수신/추천금리/목표입력 없음
2. market/product 모집단과 pricing peer/institution 모집단이 분리됨
3. pricing peer는 funding 결측 기관을 제거하지 않음
4. funding coverage known/unknown가 명시됨
5. 한 institution이 pricing peer에 1행만 존재
6. R1 비용은 predicted volume과 독립
7. current rate/funding carry-back 없음
8. historical region look-ahead 없음
9. internal raw/private model data가 public git/artifact에 없음
10. inverse solver는 promoted champion 없으면 호출되지 않음
11. out-of-support/non-monotonic response는 fail-closed
12. production-data browser E2E에서 desktop/mobile 모두 실제 payload와 UI가 검증됨

---

# 15. Non-goals

이번 문서 승인만으로 다음을 구현하지 않는다.

- source precedence 변경
- stable product identity 재설계
- name-only institution merge
- prediction coefficient 수정
- Public Structural v2 product market contract 변경
- Strategy production publication OFF
- 자동 merge

실제 구현 순서는 `20260831-relative-rate-goal-simulator-work-order-v2.md`를 따른다.
