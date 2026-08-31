# 상대금리 기반 목표형 금리결정 시뮬레이터 — Claude 리뷰 수용 기록

```yaml
document_type: review_response
status: accepted_with_revision
date: 2026-08-31
review_verdict: CHANGES_REQUIRED
reviewed_branch_head: 67ecd5420c4ebf99b82b100ad0e10b49447befbc
repository: dekt-oss/bank-rate-collector
implementation_authorized: false
merge_authorized: false
```

## 0. 결론

Claude의 P0 4건은 **전부 수용**한다.

이번 리뷰는 제품 방향을 뒤집는 것이 아니라, 다음 네 경계를 구현 전에 고정해야 한다는 지적이다.

1. Strategy는 이미 production surface다.
2. factual 비용과 uncalibrated 물량 예측을 분리한다.
3. funding peer와 pricing peer를 분리한다.
4. product-level market position과 institution-level pricing peer position을 분리한다.

P1/P2도 대부분 수용한다. 단 P1-6의 `79/66 미검증`은 리뷰 이후 GitHub Actions artifact를 다시 확인해 별도 evidence 문서로 해소했다.

이 문서와 v2 plan/work-order가 승인되기 전 **코드 구현은 시작하지 않는다.**

---

# 1. P0 처리

## P0-1 Strategy Release Gate 상태 오기 — 수용

### 판단

리뷰 지적이 맞다.

현재 repository의 `AGENTS.md`는 Strategy를 established production surface로 규정하고, canonical site-writer가 `RATE_MONITOR_STRATEGY_DASHBOARD="1"`을 유지한다고 명시한다.

따라서 기존 문서의:

```text
production_strategy_release_gate: unchanged_off
Production Strategy Release Gate OFF
```

는 폐기한다.

### v2 계약

```text
production_strategy_release_gate: on_canonical_site_writer
```

그리고 모든 R1 public factual 변경은 **merge 후 production Strategy에 노출될 수 있는 변경**으로 위험도를 산정한다.

PR/merge 자체를 runtime 검증으로 간주하지 않는다.

---

## P0-2 표면이자비용 factual 오분류 — 수용

### 판단

기존 `inflow_prediction_service.py`의 `simple_surface_interest_total_delta`는 `predicted_total`에 의존하며, `predicted_total`은 uncalibrated sensitivity scenario의 함수다.

따라서 R1 factual mode가 해당 값을 재사용하면 `예측을 금지한 화면에 예측 성격 숫자가 비용이라는 이름으로 유입`된다.

### v2 계약

R1 비용은 신규 factual arithmetic contract로 분리한다.

```text
Δ표면이자
= notional × (proposal_rate - current_rate) / 100 × term_months / 12
```

R1에서는 다음 둘만 허용한다.

1. 표준화된 `100억원당 표면이자 차이`
2. 사용자가 별도 `비용 계산 기준금액`을 입력한 경우 그 금액 기준 산술

금액 입력이 없다고 내부 잔액이나 predicted volume을 추정해 채우지 않는다.

화면 라벨 예:

```text
100억원 기준 연환산 표면이자 차이
비용 계산 기준금액 300억원 기준 표면이자 차이
```

`predicted_total`, `predicted_new_money`, `predicted_rollover`를 R1 factual 비용 계산에 사용하는 것을 금지한다.

---

## P0-3 Direct Peer를 pricing peer로 재사용 — 수용

### 판단

현재 `institution_funding_direct_peer*`는 funding 관측이 있는 기관을 대상으로 수신규모 근접성을 계산하는 **funding peer**다.

- NH local만 production enabled
- `balance <= 0`은 peer 후보에서 제외
- rate는 selection feature가 아님

따라서 이것을 금리경쟁사 모집단으로 쓰면 funding 결측 기관이 `자료없음`으로 남지 않고 목록에서 사라지는 selection bias가 생긴다.

### v2 계약

두 집합을 분리한다.

```text
funding_peer_set
- 목적: 수신규모/성장 비교
- 자격: canonical funding observation
- 기존 institution_funding_direct_peer 유지

pricing_peer_set
- 목적: 금리 경쟁위치 비교
- 자격: 동일 pricing policy scope의 유효 rate
- funding은 optional enrichment
- funding이 없어도 peer 행을 유지
```

pricing peer payload의 최소 coverage 계약:

```yaml
pricing_peer_count: integer
funding_join_count: integer
funding_join_ratio: number
funding_unjoined_count: integer
higher_rate_peer_count: integer
higher_rate_peer_funding_known_count: integer
higher_rate_peer_funding_total_krw: number|null
```

`funding_unjoined_count`를 숨기거나 0으로 대체하지 않는다.

---

## P0-4 product key / institution key 불일치 — 수용

### 판단

현재 factual market position은 product 모집단 계약이고 `institution_id`를 모른다.

따라서 여러 상품을 가진 기관이 market-wide product position에서 여러 행을 차지하는 것은 현재 계약의 실제 동작이다.

이 계약을 presentation cleanup처럼 바꾸면 안 된다.

### v2 계약

두 지표를 병존시킨다.

```text
market_position
- 기존 Public Structural v2
- product-level
- 기존 product_id anchor replacement 계약 유지

pricing_peer_position
- 신규
- institution-level
- institution → representative rate reduction 후 계산
```

신규 `institution_rate_reduction` 계약을 pricing peer 앞에 둔다.

설계 기본안:

```yaml
rule: max_rate_within_matched_scope
matched_on:
  - sector
  - product_type
  - term_months
  - availability_scope
special_offer: core_peer_excluded_and_radar_separate
tie_break: stable_product_id_ascending
output:
  - institution_id
  - representative_product_id
  - rate_pct
  - rate_as_of
  - selection_reason
```

이 기본안은 **사용자 최종 승인 전 implementation contract로 확정하지 않는다.**

---

# 2. P1 처리

## P1-1 peer feature whitelist — 수용

R3에서 기존 `market_*`의 의미를 바꾸지 않는다.

신규 feature는 별도 이름으로 추가한다.

```text
peer_gap_bp
peer_rank_best
peer_rank_worst
peer_tie_count
peer_within_5bp_count
peer_within_10bp_count
market_within_10bp_count
```

`peer_*` 값을 `market_*` 컬럼에 넣는 것은 contract violation이다.

---

## P1-2 public 목표입력 UI — 수용

R1/R2 public mode에서는 목표수신/목표기간 입력 UI를 **DOM에 렌더링하지 않는다.**

R4 private champion activation과 함께 처음 등장한다.

단 문서 설명/비활성 placeholder도 production UI에는 두지 않는다.

---

## P1-3 존재하지 않는 필독문서 — 수용

root에 `CLAUDE.md`, `README.md`가 현재 존재하지 않으므로 v2 work-order에서 필독 목록에서 제거한다.

`AGENTS.md`, `pyproject.toml`, `.github/workflows`, `docs/specs/CURRENT.md`와 실제 존재하는 관련 spec만 읽는다.

---

## P1-4 monotonicity gate — 수용

현재 이미 구현된 gate처럼 표현하지 않는다.

R4의 신규 산출물로 정의한다.

원칙:

- forward model grid가 비단조이면 최소금리 한 점을 억지로 선택하지 않는다.
- 불연속 feasible region은 복수 구간으로 계산한다.
- 안정성 조건을 충족하지 못하면 `status=non_monotonic_response`로 fail-closed하고 추천범위를 출력하지 않는다.

---

## P1-5 내부 데이터 기계적 방어 — 수용

R3 전에 다음을 별도 security/data-safety PR로 구현한다.

- `.gitignore` private/internal intake 경로
- CI forbidden path scan
- artifact upload 대상 scan
- forbidden sensitive column/name scan
- public payload에 private raw/sample/model diagnostic 노출 금지 검사

문서 규칙만으로 충분하다고 보지 않는다.

---

## P1-6 79/66 수치 — 지적 수용 + evidence 보강 완료

리뷰 시점에는 branch에 근거 문서가 없었던 지적이 맞다.

리뷰 이후 GitHub Actions production artifact를 다시 확인했고 다음을 별도 evidence로 기록했다.

`docs/evidence/20260831-savings-bank-funding-identity-coverage.md`

확인값:

```text
2026-03 savings_bank
institution_count 79
mapped_count      66
unmapped_count    13
institution sum   99,573,991 million KRW
ECOS total        99,574,000 million KRW
status            aligned
```

따라서 R0-B는 `79/66 실태 확인`이 아니라 **13개 exact mapping remediation 범위 확정**으로 좁힌다.

---

# 3. P2 처리

## P2-1 한계조달원가 — 수용

Public Structural v2의 기존 금지 계약을 유지한다.

R1/R2 UI에서 `한계조달원가`라는 표현과 파생지표를 사용하지 않는다.

R4 이후라도 FTP/ALM economic cost와 구분되는 별도 승인/명세 없이는 부활시키지 않는다.

---

## P2-2 대형사 영향 — 수용

규모가중 평균금리를 새 scalar로 만들지 않는다.

대신 분해된 factual context를 보여준다.

- 당사보다 높은 pricing peer 수
- 그중 funding 확인 수
- 확인된 funding 합계
- funding 미확인 수
- 필요하면 known funding population 내 비율

partial coverage를 전체 업권 비중처럼 표시하지 않는다.

---

## P2-3 Historical Peer 저장 vs 재계산 — 수용

기본은 `versioned deterministic recomputation`이다.

snapshot 저장은 성능 캐시일 뿐 source of truth가 아니다.

단 현재 `institutions.region_sido/sigungu`가 시점 이력을 보존하지 않으므로 historical region을 현재값으로 소급하지 않는다.

```text
region_as_of available
→ 당시 availability/region policy 사용

region_as_of unavailable
→ nationwide_only 또는 insufficient_history
```

현재 지역으로 과거 peer를 좁히는 것은 look-ahead bias로 금지한다.

---

## P2-4 합병/명칭변경 — 수용

historical analogue에서 `source_entity_links.valid_from/valid_to`, alias/history 근거를 사용하고, 합병 전후 같은 경제주체가 중복계상되지 않는 테스트를 추가한다.

---

## P2-5 상품 identity 변화 — 수용

historical analogue candidate는 최소 다음 scope가 일치해야 한다.

- product_type
- term_months
- availability/join channel scope
- special offer core/radar classification

조건 불일치는 similarity penalty가 아니라 candidate exclusion을 기본으로 한다.

---

# 4. 리뷰가 요구한 사용자 정책 — v2의 제안 기본값

아래는 저장소 증거만으로 확정할 수 없는 영업/제품 정책이다.

이번 v2 문서에서는 구현자가 임의 결정하지 않도록 **제안 기본값**만 적는다.

## D1 institution → rate 축약

권고:

- 동일 업권 + 정기예금 + 동일 가입기간에서 institution max rate
- 특판은 core pricing peer에서 제외하고 별도 radar
- 채널/가입가능범위가 다르면 동일 peer scope로 보지 않음

상태: `proposed_not_user_approved`

## D2 R1 factual cost notional

권고:

- 기본 표시는 `100억원당 표면이자 차이`
- 선택적으로 사용자가 `비용 계산 기준금액` 입력
- 당사 잔액/예측수신을 자동 notional로 사용하지 않음

상태: `proposed_not_user_approved`

## D3 pricing peer의 지역범위

권고:

- funding peer의 `sigungu→sido→nationwide` fallback을 복사하지 않음
- 상품의 실제 가입가능범위/채널을 pricing availability scope로 사용
- 비대면 전국가입 상품은 nationwide
- 지역제한 상품은 해당 availability scope
- scope 증거가 없으면 임의 지역추정 금지

상태: `proposed_not_user_approved`

## D4 신협

권고:

- valid rate가 있으면 pricing peer에는 포함 가능
- institution funding이 없으면 행은 유지하고 funding=`자료없음`
- funding 기반 scalar/비중에는 known-only coverage를 명시

상태: `proposed_not_user_approved`

## D5 목표입력 UI 시점

권고:

- R1/R2/R3 public Strategy에는 렌더링하지 않음
- R4 private champion + inverse gate 통과 후 최초 노출

상태: `proposed_not_user_approved`

## D6 저축은행 pricing peer N

권고:

- 지금 확정하지 않음
- identity remediation + 실제 pricing population 분포 실측 후 후보 N을 calibration
- NH N=16을 복사하지 않음

상태: `deferred_by_evidence_gate`

---

# 5. 다음 문서

이 리뷰 반영의 실행 기준은 다음 v2 문서다.

- `docs/plans/20260831-relative-rate-goal-simulator-plan-v2.md`
- `docs/plans/20260831-relative-rate-goal-simulator-work-order-v2.md`
- `docs/evidence/20260831-savings-bank-funding-identity-coverage.md`

기존 v1 plan/work-order는 decision trail로 보존하며 수정하지 않는다.

v2가 재리뷰에서 승인되기 전 코드 구현/PR/merge로 넘어가지 않는다.
