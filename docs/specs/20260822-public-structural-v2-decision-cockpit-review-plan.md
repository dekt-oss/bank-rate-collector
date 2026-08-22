# Public Structural Engine v2 + 금리결정 Cockpit — Review Plan

```yaml
document_type: review_plan
status: draft/review-required
date: 2026-08-22
repository: dekt-oss/bank-rate-collector
issue: 169
parent_issue: 167
stacked_on_pr: 168
main_reference: b5fca6b5add85ebb4a6ca2b04f9b21dd75baf2b1
stacked_parent_head: 87ed6094f622d9c9a92a0b1d74c3d86774991d18
implementation_gate: Fable review APPROVE + explicit user approval
merge_policy: explicit_user_approval
production_strategy_release_gate: unchanged_off
internal_data: prohibited_in_public_repo
```

---

## 0. 이 문서의 지위

이 문서는 **구현 명세가 아니라 대형 후속 작업의 리뷰용 실행계획**이다.

- Fable 리뷰와 사용자 승인 전에는 아래 Stage의 구현을 시작하지 않는다.
- 현재 `main`에 merge된 사실과 Draft PR #168의 목표 상태를 구분한다.
- 이 계획은 #168의 공개/비공개 forecast boundary를 전제로 한다.
- #168이 merge되기 전에 구현을 시작해야 하는 예외가 생기면 stacked PR로만 진행하고,
  `main`에 #168이 이미 반영된 것처럼 취급하지 않는다.
- 내부자료 기반 calibrated engine은 로컬 confidential repository에서만 개발한다.
- 이 public repository에서는 내부자료·내부계수·training diagnostics를 취급하지 않는다.
- Production Strategy Release Gate는 별도 명시적 승인 없이는 변경하지 않는다.
- 자동 merge하지 않는다.

### 이 계획이 해결하려는 한 문장

> 내부실적이 없어도 **실제 시장에서 당사 금리가 어디에 위치하는지와 금리를 움직였을 때
> 시장 위치·구조적 수신반응·표면조달비용의 trade-off가 어떻게 달라지는지**를 최대한
> 사실 기반으로 계산하고, 나중에 confidential calibrated engine이 붙어도 UI를 다시 만들지
> 않는 금리결정 Cockpit을 만든다.

---

# 1. Current State — 지금 실제로 존재하는 것

## 1.1 main 기준점

2026-08-22 작업 시작 시 확인한 최신 `main`:

`b5fca6b5add85ebb4a6ca2b04f9b21dd75baf2b1`

해당 commit은 PR #166 `Strategy 금리결정·시장근거 의사결정 UX 정리` merge다.

PR #166에서 이미 다음이 들어왔다.

- Strategy를 금리결정 준비도 → 인사이트 → 경쟁사 TOP5 → 수신반응 시나리오 순으로 재구성
- 현재/+5/+10/+15bp 및 현재 제안금리 비교 UI
- 저민감/기준/고민감 수신반응 표시
- 한국은행 신규취급 금리와 업권 수신잔액 등 외부 시장근거 표시
- Python ↔ browser prediction parity 계약
- desktop/mobile Chrome smoke 보강

따라서 이번 계획은 이 기능을 다시 구현하지 않는다.

## 1.2 현재 수신반응 구조모델

`src/rate_monitor/services/inflow_prediction_service.py`

현재 `inflow-structural-v1`은:

```text
rate_steps = (proposed_rate - current_own_rate) / 0.10%p

신규수신:
predicted_new_money
= baseline_new_money × exp(clamp(beta_new × rate_steps, -1.5, +1.5))

재예치:
logit(p1)
= logit(p0) + gamma_rollover × rate_steps
predicted_rollover
= maturity_amount × p1

총수신:
predicted_total
= predicted_new_money + predicted_rollover

표면이자비용:
surface_interest_delta
= predicted_total × proposed_rate × term_factor
  - baseline_total × current_rate × term_factor
```

현재 low/base/high 계수는 내부실적 추정치가 아니라 stress assumption이다.

```text
low   beta_new 0.02 / gamma_rollover 0.04
base  beta_new 0.05 / gamma_rollover 0.08
high  beta_new 0.10 / gamma_rollover 0.16
```

## 1.3 현재 가장 큰 구조적 한계

현재 코드에는 다음이 있다.

```text
current_gap  = current_own_rate - market_top10_rate
proposed_gap = proposed_rate - market_top10_rate
relative_change = proposed_gap - current_gap
```

대수적으로:

```text
relative_change = proposed_rate - current_own_rate
```

따라서 `market_top10_rate`는 감사용 gap에는 남지만 수신금액 민감도에는 독립적으로
작용하지 않는다.

이번 Public Structural v2에서 이 문제를 **근거 없는 새 coefficient로 보정하지 않는다.**
대신 실제 시장위치 계산을 별도 factual layer로 분리한다.

## 1.4 현재 브라우저의 시장위치 계산

`web/templates/strategy.html`의 현재 런타임은 선택 기간·업권 비교상품에서:

```text
mean
median
top10 cutoff
market min/max
```

을 계산하고, 제안금리보다 높은 비교상품 수를 세어:

```text
rank = higher_count + 1
```

로 공동순위형 시장 순위를 표시한다.

금리 입력은 현재 `step=0.01%p`, 즉 1bp 단위다.

현재 화면에는:

- 제안 최고금리
- 예상 시장 순위
- 고려저축은행 현재 최고
- 시장 상위 10% 진입선
- 평균/중앙값 기반 position rail

이 이미 존재한다.

## 1.5 Strategy 비교 universe

`strategy_contract_service.py`는 현재 Strategy 전용 파생금리를 만들어:

- savings_bank
- cu
- kfcc
- nh_local

의 6/12/24/36개월 정기예금을 대상으로 사용할 수 있다.

비교 기본 단위는 `sector + stable product representative`이며,
source precedence와 업권별 rate basis를 이미 별도 계약으로 관리한다.

이번 계획은 **기존 stable product identity / source precedence / strategy rate basis를 재정의하지 않는다.**

## 1.6 현재 공개 외부근거

이미 public repo에는 다음이 있다.

- 한국은행 기준금리
- 예금은행 신규취급 수신금리
- 예금은행 1년 정기예금 신규취급 금리
- 저축은행/신협/광의 상호금융/새마을금고 수신잔액과 MoM
- Strategy 7D/30D 시장이력
- 시장 median / upper-decile cutoff 변화
- stable-product 비교 변화
- 상위 10% 구성 교체

`deposit_pricing_external_feature_service.py`는 이를 read-only external feature bundle로 묶고 있다.

이번 계획의 Public Structural layer는 **이미 존재하는 데이터의 의미를 우선 사용**하고,
새 외부변수는 별도 Evidence Gate를 통과하기 전까지 공식/화면에 넣지 않는다.

## 1.7 #168 — 아직 main에 없는 선행 계약

Draft PR #168은:

- 현재 공식·계수·한계 문서화
- Evidence Registry
- confidential/public separation
- `inflow-public-forecast-v1` allowlist
- coefficient/provenance/training metadata 누출 fail-closed

를 추가한다.

이번 계획은 #168을 **dependency**로 취급한다.
#168을 main에 merge된 사실로 서술하지 않는다.

---

# 2. 목표 상태

최종 Strategy의 `01 금리 결정`은 아래 질문에 30초 안에 답해야 한다.

1. **현재 당사 금리는 선택 시장에서 어디에 있는가?**
2. **5bp / 10bp를 움직이면 실제 시장 위치가 얼마나 바뀌는가?**
3. **해당 금리에서 구조적 수신반응 범위는 어떻게 달라지는가?**
4. **추가 수신을 얻기 위해 표면이자비용을 얼마나 더 부담하는가?**
5. **어느 금리구간부터 추가 bp의 시장위치 개선효율 또는 구조적 비용효율이 둔화되는가?**
6. **어떤 값이 실제 시장 관측이고 어떤 값이 미보정 시나리오인지 즉시 구분 가능한가?**

이를 위해 엔진을 하나의 거대 formula로 만들지 않고 네 계층으로 분리한다.

```text
[Layer A] Factual Market Position
  실제 수집금리만 사용
        ↓
[Layer B] Structural Response Surface
  현재 v1 stress assumption을 여러 금리점에 일관 적용
        ↓
[Layer C] Decision Economics
  incremental / marginal trade-off 계산
        ↓
[Layer D] Decision Cockpit UX
  사실 / 시나리오 / 비용을 한 화면에서 결합
```

그리고 향후:

```text
[Confidential Calibrated Engine]
        ↓ same sanitized forecast contract
[Layer C/D 그대로 재사용]
```

을 목표로 한다.

---

# 3. 설계 원칙 — 반드시 지킬 것

## P1. Factual과 Assumption을 시각·계약 모두에서 분리

**Factual Market Position**

- 현재 비교상품 금리
- 순위
- 상위 비율
- median/top10/top25 cutoff
- gap
- crowding
- threshold crossing

은 실제 수집 데이터로 계산한다.

**Structural Scenario**

- 신규수신 변화
- 재예치 변화
- 예상 총수신
- stress range
- incremental amount
- 비용 trade-off

는 현재 미보정 sensitivity를 사용한다.

한 카드나 한 숫자에서 두 범주가 섞여 provenance를 알 수 없게 만들지 않는다.

## P2. 내부자료 없이 `forecast accuracy`를 주장하지 않는다

Public v2의 개선목표는:

- 시장구조 현실성
- 계산일관성
- 의사결정 설명력
- 불확실성 표시
- 실제 시장자료 활용도

이다.

**은행별 예측정확도 향상**은 confidential engine의 검증영역이다.

## P3. `추천금리`를 자동 생성하지 않는다

내부실적 calibration과 명시적 objective function이 없는 상태에서:

- `최적 금리`
- `추천 금리`
- `달성확률 xx%`

을 출력하지 않는다.

대신:

- `시장 상위 10% 진입 최소금리`
- `선택한 구조 시나리오에서 목표 총수신을 처음 넘는 금리`
- `비용상한 이내 후보`

처럼 **사용자가 지정한 조건을 충족하는 최소 후보금리**만 계산할 수 있다.

## P4. 현재 v1 coefficient는 임의 변경하지 않는다

Public Structural v2의 핵심은 arbitrary coefficient를 더 붙이는 것이 아니다.

- 시장위치 효과를 금액식에 새 임의계수로 추가하지 않는다.
- crowding/rank를 수신액 multiplier로 임의 적용하지 않는다.
- external prior evidence가 생기더라도 별도 review 없이 coefficient를 바꾸지 않는다.

## P5. 기존 canonical data contract를 건드리지 않는다

기본 범위에서는 변경 금지:

- collector
- DB/schema/migration
- source precedence
- canonical `base_rate` / `max_rate`
- stable product identity
- strategy rate basis

새 계산은 Strategy read-only derived layer로 만든다.

## P6. browser 계산이 필요한 경우 Python parity를 반드시 둔다

현재 Strategy는 static build + browser interactive 구조다.

따라서 사용자 입력에 즉시 반응하는 계산을 JS에 둘 수 있지만:

- Python canonical pure function
- JS mirror
- frozen golden vectors
- deliberate one-sided drift probe

를 묶어 parity를 강제한다.

## P7. private provider가 붙어도 UI provenance가 새지 않게 한다

향후 confidential engine이 붙어도 브라우저 payload에는 #168 public allowlist 밖의:

- coefficient
- feature
- source file
- sample size detail
- training metric
- private model id/path

를 보내지 않는다.

UI는 provider 이름이나 내부자료 사용여부를 추론하게 만드는 metadata에 의존하지 않는다.

---

# 4. Target Architecture

```text
                   ┌─────────────────────────┐
                   │ strategy-table.json     │
                   │ current market snapshot │
                   └────────────┬────────────┘
                                │
                                v
                   ┌─────────────────────────┐
                   │ Market Position Engine  │
                   │ factual / deterministic │
                   └────────────┬────────────┘
                                │
               ┌────────────────┴────────────────┐
               │                                 │
               v                                 v
    ┌──────────────────────┐         ┌──────────────────────┐
    │ Market thresholds    │         │ Candidate rate grid  │
    │ rank/percentile/gaps │         │ current ± steps      │
    └──────────┬───────────┘         └──────────┬───────────┘
               │                                 │
               │                                 v
               │                    ┌─────────────────────────┐
               │                    │ Structural Response v2  │
               │                    │ v1 sensitivities        │
               │                    │ low/base/high surface   │
               │                    └──────────┬──────────────┘
               │                               │
               └───────────────┬───────────────┘
                               v
                   ┌─────────────────────────┐
                   │ Decision Economics      │
                   │ incremental/marginal    │
                   └────────────┬────────────┘
                                v
                   ┌─────────────────────────┐
                   │ Decision Cockpit UX     │
                   └────────────┬────────────┘
                                │
                                │ future provider swap
                                v
                   ┌─────────────────────────┐
                   │ inflow-public-forecast  │
                   │ sanitized contract      │
                   └────────────┬────────────┘
                                ^
                                │
                  ┌─────────────┴─────────────┐
                  │ Confidential Engine       │
                  │ local/private runtime     │
                  └───────────────────────────┘
```

---

# 5. Layer A — Factual Market Position Engine

## 5.1 입력 universe

입력은 현재 Strategy에서 이미 만들어지는 `aggregateProducts(term)`과 같은 의미를 사용한다.

필수 차원:

- active market mode
- active sectors
- term_months
- term_deposit
- strategy rate
- stable `product_id`

현재 compare-unit을 임의로 `institution`으로 바꾸지 않는다.

1차 구현의 primary label은 반드시:

> `선택 비교군의 대표 비교상품`

처럼 **상품 기준**임을 알 수 있게 한다.

향후 institution-level ranking을 추가하려면 업권별 outlet/institution/rate_scope 의미를 먼저
Evidence Gate에서 따로 검증한다.

## 5.2 기본 통계

선택 비교군의 금리 벡터 `R = {r1 ... rn}`에 대해:

```text
N                   비교상품 수
mean_rate           평균
median_rate         중앙값
max_rate            최고
min_rate            최저
top25_cutoff        상위 25% 진입선
top10_cutoff        상위 10% 진입선
```

상위 cutoff는 기존 `topCutoff()` 의미와 맞춘다.

```text
count = max(1, ceil(N × share))
cutoff = 내림차순 N개의 count번째 금리
```

## 5.3 공동순위 계약

제안금리 `r`의 순위는 현재와 동일하게:

```text
higher_count(r) = count(ri > r + tolerance)
rank(r) = higher_count(r) + 1
```

동일금리는 공동순위다.

추가로:

```text
tie_count(r) = count(abs(ri - r) <= tolerance)
```

을 표시해 `5위 / 120개`가 실제로 몇 개 상품과 동률인지 알 수 있게 한다.

## 5.4 상위 비율

사용자에게 직관적인 보조값으로:

```text
top_share_pct = rank / N × 100
```

을 사용한다.

표현 예:

```text
17위 / 112개 · 상위 약 15.2%
```

이는 통계 percentile 추정치가 아니라 **현재 공동순위를 전체 비교상품 수로 나눈 표시값**이다.
문구에서도 `상위 비율`로 부르고 `확률`이라고 하지 않는다.

## 5.5 Gap metrics

현재/제안 각각:

```text
gap_to_mean_pp
gap_to_median_pp
gap_to_top25_pp
gap_to_top10_pp
gap_to_market_max_pp
```

을 계산한다.

금리 차이는 내부 계산에서 `%p`, UI에서는 기본 `bp`로 함께 보여준다.

## 5.6 Crowding — 경쟁금리 밀집도

제안금리 `r` 주변의 실제 상품 밀집도를 계산한다.

```text
exact_tie_count        |ri-r| <= tolerance
within_5bp_count       |ri-r| <= 0.05%p
within_10bp_count      |ri-r| <= 0.10%p
```

또한 구간을 분리한다.

```text
(r-10bp, r-5bp]
(r-5bp, r]
(r, r+5bp]
(r+5bp, r+10bp]
```

목적은 금리를 5bp 움직였을 때 **실제로 몇 개 비교상품 가격대를 통과하는지** 보여주는 것이다.

## 5.7 Threshold crossings

현재금리 `r0`, 후보금리 `r1`에 대해 상승 시:

```text
crossed_products
= count(r0 < ri <= r1)
```

하락 시는 반대방향으로 대칭 정의한다.

UI 표현 예:

```text
+5bp로 비교상품 14개 금리구간 통과
```

`경쟁사 14곳`이라고 표현하지 않는다. 현재 compare-unit이 stable product이기 때문이다.

## 5.8 Rank efficiency

금리변화가 0보다 클 때:

```text
rank_gain = rank(r0) - rank(r1)
rank_gain_per_5bp = rank_gain / ((r1-r0)/0.05)
```

단:

- 0bp 변화면 `undefined`
- 금리하락은 별도 signed movement로 표시
- 이것을 수익성 또는 고객반응으로 표현하지 않는다

표현 예:

```text
+5bp당 순위 8.0단계 개선
```

## 5.9 Next market thresholds

현재 UI 금리 입력 granularity가 1bp이므로 1차 후보로:

- next higher observed rate
- rate to tie that threshold
- rate to exceed by 1bp
- top25 cutoff
- top10 cutoff
- market max

를 계산한다.

단, `+1bp` exceed는 **UI 입력 granularity 계약**일 뿐 실제 은행 가격정책의 최소조정단위라고
주장하지 않는다.

## 5.10 Factual engine의 금지사항

이 layer에서 금지:

- 고객반응 coefficient
- 수신액 multiplier
- `효율이 좋으니 추천`
- 미래 순위 예측
- 경쟁사 미래 금리변경 가정

모든 값은 **현재 snapshot에서 제안금리를 가상으로 놓았을 때의 정적 시장위치**다.

---

# 6. Layer B — Structural Response Surface v2

## 6.1 기존 공식은 baseline으로 유지

Public v2에서 내부자료가 없는 동안 `inflow-structural-v1` 공식을 버리지 않는다.

다만 현재처럼 특정 제안금리 한 점만 강조하지 않고, 여러 후보금리에 low/base/high를
동시에 적용해 **response surface**를 만든다.

## 6.2 후보금리 grid

기본 후보는 현재 당사금리를 기준으로:

```text
-10bp
-5bp
current
+5bp
+10bp
+15bp
+20bp
```

중 유효 범위만 사용하고, 다음을 union한다.

- 사용자가 현재 입력한 제안금리
- top25 cutoff
- top10 cutoff
- 다음 주요 observed threshold

모든 금리는 1bp grid에 normalize한다.

후보가 너무 많아지면 정렬 후 dedupe하고 최대 개수를 제한한다.

### UX 기본

기본 화면에서는 지나치게 많은 후보를 노출하지 않고:

- current
- +5
- +10
- +15
- proposal
- 주요 market threshold

를 우선 보여준다.

전체 후보는 상세보기에서 제공한다.

## 6.3 각 후보의 low/base/high 결과

각 rate candidate `r`에 대해:

```text
low:
  predicted_new_money
  predicted_rollover_rate
  predicted_rollover
  predicted_total
  incremental_total
  surface_interest_delta

base:
  same

high:
  same
```

을 계산한다.

## 6.4 Stress band 계약

```text
stress_total_min = min(low/base/high predicted_total)
stress_total_max = max(low/base/high predicted_total)
```

현재 low/base/high가 민감도 순으로 단조라는 사실에 의존하지 않고 실제 결과의 min/max를 쓴다.

UI 명칭:

- `구조적 시나리오 범위`
- `민감도 범위`

금지 명칭:

- 신뢰구간
- 예측구간
- 90%/95% range
- 확률범위

## 6.5 Market position과 amount formula를 섞지 않는다

Factual Layer A의:

- rank
- top_share
- crowding
- top10 gap

을 v2 amount formula에 임의 coefficient로 곱하지 않는다.

Layer A와 Layer B를 **동일 rate candidate 기준으로 나란히 결합**할 뿐이다.

이는 현재 TOP10이 상쇄되는 문제를 숨기지 않으면서도 근거 없는 보정식을 만들지 않는 선택이다.

---

# 7. Layer C — Decision Economics

## 7.1 기본 원칙

현재 비용계약은 FTP가 아니라 단순 표면이자다.

따라서 이 layer 명칭도:

> `구조적 표면비용 trade-off`

로 제한한다.

`실제 조달원가`, `FTP`, `손익`, `NIM 영향`이라고 부르지 않는다.

## 7.2 Incremental metrics

각 rate/scenario에 대해:

```text
incremental_total
surface_interest_delta
```

는 기존 공식에서 직접 나온다.

추가로 adjacent candidate 간 차이를 계산한다.

예: 3.55 → 3.60%

```text
step_rate_delta_bp
step_rank_gain
step_crossed_products
step_incremental_total_change
step_surface_interest_delta_change
```

## 7.3 Marginal surface cost

후보 `A → B`에서:

```text
delta_volume = predicted_total_B - predicted_total_A
delta_cost   = predicted_surface_interest_B - predicted_surface_interest_A
```

`delta_volume > epsilon`인 경우에만:

```text
marginal_surface_cost_per_added_1eok
= delta_cost / delta_volume
```

을 계산한다.

금액 단위가 억원이므로 결과는:

```text
추가 총수신 1억원당 기간내 추가 표면이자비용(억원)
```

이다.

사용자용 표시는 원 단위로 환산할 수 있지만 내부 contract는 unit을 명시한다.

## 7.4 Annualized marginal surface cost rate — 선택기능

기간 비교를 위해 필요하면:

```text
annualized_marginal_surface_cost_rate
= (delta_cost / delta_volume) / (term_months / 12) × 100
```

을 계산할 수 있다.

단 다음 조건 모두 충족 시에만 노출한다.

- delta_volume > epsilon
- term_months > 0
- 단위 검증 테스트 존재
- UI에 `표면비용 기준` 명시

FTP나 실제 transfer pricing과 혼동될 가능성이 높으면 v1 UI에서는 숨긴다.

## 7.5 Undefined / pathological case

다음은 `—`로 표시하고 숫자를 억지로 만들지 않는다.

- 구조적 추가수신 <= 0
- 분모가 거의 0
- 금리하락과 volume/cost 방향이 복합적인 경우
- 입력 누락

## 7.6 Pareto / dominance 분석

내부자료 없는 단계에서 `최적화`라고 부르지 않는다.

후보 간 다음 세 축을 비교할 수 있다.

```text
시장위치 개선
구조적 총수신 변화
표면비용 증가
```

명백히 열등한 후보를 `dominance`로 표시하는 것은 가능하나,
**자동 recommended candidate는 만들지 않는다.**

Fable 리뷰에서 이 기능이 과도한 의사결정 암시라고 판단하면 Stage C 범위에서 제외한다.

---

# 8. Decision Objective Layer — 조건충족 탐색

## 8.1 목표

금리담당자가 원하는 조건을 지정했을 때 후보 중 **최소 조건충족 금리**를 찾는다.

초기 목표유형:

### A. Factual target

- 상위 X% 진입
- 상위 10% 진입
- 시장 중앙값 이상
- 특정 market rank 이내

이 유형은 실제 시장 snapshot만 사용하므로 기본 제공 가능하다.

### B. Structural target

- base 시나리오 총수신 >= X
- low 시나리오 총수신 >= X
- 구조적 incremental_total >= X

이 유형은 반드시:

> `미보정 구조 시나리오 기준`

으로 표시한다.

### C. Cost constraint

- 표면이자비용 증가 <= X
- 금리 상한 <= X

## 8.2 결과 문구

허용:

> `현재 비교군 기준 상위 10%에 처음 진입하는 후보금리 3.61%`

> `저민감 시나리오에서 총수신 300억원 조건을 처음 충족하는 후보금리 3.67%`

금지:

> `추천금리 3.61%`

> `3.61%면 300억원 달성 가능`

> `목표 달성확률 85%`

---

# 9. Layer D — 최종 UX / UI 정보구조

## 9.1 UX 목표

현재 화면은 계산기와 시장근거가 이미 있으므로 **더 많은 카드**가 목표가 아니다.

목표는:

> `현재 → 제안 → 시장위치 변화 → 구조적 수신반응 → 비용`의 한 방향 읽기 흐름

이다.

## 9.2 상단 Decision Strip

`01 금리 결정`의 첫 핵심 결과를 한 줄로 압축한다.

예시 구조:

```text
현재금리        제안금리       시장위치 변화       구조적 총수신       표면비용
3.50%     →     3.60%         38% → 15%          224~238억         +1.7억
                               +26 rank            base 229억
```

표시원칙:

- 시장위치 값은 `시장관측` badge
- 수신범위는 `구조시나리오` badge
- 비용은 `표면비용` badge
- 색만으로 provenance를 구분하지 않는다

## 9.3 Market Position Ladder

수직 또는 수평 ladder에:

- market max
- top10 cutoff
- top25 cutoff
- median
- current
- proposal

을 표시한다.

현재 rail의 단순 min/max marker보다 **의미있는 threshold 중심**으로 바꾼다.

각 threshold에는 gap을 bp로 표시한다.

예:

```text
3.70  시장 최고
3.65  상위 10%
3.60  ● 제안
3.55  상위 25%
3.50  ○ 현재
3.45  중앙값
```

## 9.4 Market Step Impact

현재 → proposal의 변화에 대해:

```text
+10bp
순위 43 → 17
상위 비율 38.4% → 15.2%
비교상품 14개 금리구간 통과
제안금리 ±5bp 안에 21개 상품 밀집
```

처럼 factual impact를 먼저 보여준다.

## 9.5 Response Curve

x축:

```text
금리
```

y축:

```text
예상 총수신(억원)
```

표현:

- base line
- low~high stress band
- current vertical marker
- proposal vertical marker
- median/top25/top10 market threshold vertical marker

중요:

**stress band는 투명한 영역으로 그리되 `통계적 신뢰구간 아님`을 차트 caption에 고정한다.**

## 9.6 Candidate Rate Table

기본 테이블:

| 후보금리 | 시장순위/상위비율 | 통과 비교상품 | 구조적 총수신 범위 | base 증분수신 | 표면비용 | 전단계 marginal |
|---|---|---:|---:|---:|---:|---:|

기본 후보 수는 모바일에서 읽을 수 있게 제한한다.

상세보기에서 모든 후보를 제공한다.

## 9.7 Progressive Disclosure

처음부터 노출:

- current / proposal
- factual market shift
- structural range
- cost
- Response Curve

접힌 상세:

- low/base/high 세부 신규/재예치
- 공식
- coefficient assumption
- threshold/crowding 상세
- 데이터 근거
- Evidence Registry 링크

## 9.8 모바일

390px 기준:

- Decision Strip은 2열 또는 세로 stack
- ladder는 화면폭 내 고정
- Response Curve 가로 스크롤 금지
- candidate table은 핵심열 카드형 fallback 검토
- 세부 formula/table만 horizontal scroll 허용 가능

## 9.9 접근성

- 10.5px 미만 핵심 microcopy 금지라는 최신 Strategy 가독성 계약을 보존
- 색만으로 factual/scenario/cost를 구분하지 않음
- 차트 marker에 text/aria label 제공
- slider/number input keyboard 조작 유지
- 모션은 의미 전달에 필수로 사용하지 않음

---

# 10. Provider-Agnostic Forecast UX

## 10.1 목적

지금은 public structural model이 계산하고,
향후에는 confidential calibrated engine이 계산할 수 있다.

화면 전체를 다시 만들지 않는다.

## 10.2 Forecast contract

#168의 `inflow-public-forecast-v1`을 forecast result의 public boundary로 사용한다.

허용 핵심:

```text
version
generated_at
status
amount_unit
rate_unit
scenarios[]
  rate_pct
  predicted_new_money
  predicted_rollover
  predicted_total
  incremental_total
  surface_interest_delta
  optional lower/upper
```

## 10.3 Market position은 forecast payload와 분리

시장 rank/crowding/threshold는 public Strategy 데이터에서 직접 계산 가능하다.

따라서 confidential engine이 나중에 붙어도:

```text
Market Position = public factual layer
Forecast Amount = provider result
Decision UX     = combine
```

구조를 유지한다.

## 10.4 UI가 private provenance를 노출하지 않게 한다

향후 provider 변경 시 브라우저에:

- `private_model`
- `internal_calibrated`
- training date/sample
- coefficient source

같은 값을 보내지 않는다.

현재 public structural mode의 정확한 limitation은 문서/상세 설명으로 관리하되,
provider 전환 자체가 UI 문구 변화로 내부자료 존재를 암시하지 않도록 presentation contract를
Fable 리뷰에서 별도 확인한다.

---

# 11. External Prior Research — 별도 Evidence Gate

이 Stage는 **반드시 연구/판정 후 구현 여부를 결정**한다.

## 11.1 질문

Public 데이터만으로 현재 arbitrary stress band보다 더 근거 있는 prior를 만들 수 있는가?

## 11.2 현재 available 후보

이미 저장소에 존재:

- BOK policy rate
- bank deposit realized rates
- bank 12M deposit anchor
- sector deposit balances
- project-collected market rate history

추가 조사 후보는 별도 public source evidence가 확보되는 경우에만 검토한다.

## 11.3 최소 데이터 Gate

external prior를 수치화하려면 최소:

- 충분한 시계열 길이
- 연속성
- 같은 의미의 rate series
- 같은 의미의 balance/flow series
- 공표 lag 기록
- 구조변화/regime 식별 가능성

이 필요하다.

프로젝트 수집기간이 너무 짧으면 `우리 시장금리 history`를 장기회귀에 억지로 사용하지 않는다.

## 11.4 허용 가능한 결과

A. **NO-GO**

```text
공개자료로 은행별 수신민감도를 추정할 수 없음
→ 현 low/base/high는 stress assumption 유지
```

이는 정상적인 결과다.

B. **Context Prior GO**

공개자료에서 업권/시장 수준의 반응범위가 재현 가능할 경우:

```text
external_context_prior
```

로 별도 관리할 수 있다.

그러나:

- 고려저축은행 coefficient라고 부르지 않음
- private calibrated model과 동일한 지위를 주지 않음
- 바로 production center estimate로 승격하지 않음

## 11.5 기존 Evidence Registry와 연결

외부 연구/공공데이터 근거는 #168의 Evidence Registry 방식처럼:

```text
Supports
Does NOT support
```

를 반드시 함께 기록한다.

---

# 12. 구현 단계 — PR 분리 계획

Fable 승인 후 아래 순서를 기본으로 한다.

## Stage 0 — #168 merge / dependency normalization

목적:

- public/private boundary를 main에 확정
- stacked branch를 최신 main으로 정리
- CURRENT.md 문서 상태 정리

DoD:

- #168 merged or user-approved equivalent contract on main
- public forecast contract tests green
- no internal data in repo

## Stage A — Market Position Engine

새 pure domain/service 계약을 만든다.

예상 파일:

```text
src/rate_monitor/services/strategy_market_position_service.py

tests/test_strategy_market_position_service.py
tests/data/strategy_market_position_vectors.json
```

필수 구현:

- mean/median/top25/top10
- joint rank
- top share
- tie count
- gap metrics
- crowding
- crossings
- rank gain
- market thresholds

이번 Stage에서는 UI를 크게 바꾸지 않는다.

DoD:

- exact synthetic vectors
- ties
- one-row market
- all same rate
- empty market
- up/down move
- 1bp boundary
- selected multi-sector universe
- current compare-unit 보존

## Stage B — Browser parity + candidate grid

목적:

interactive simulator에서 같은 market-position 계약을 사용한다.

- Python canonical vectors
- JS mirror
- Node parity
- one-sided drift failure probe
- current/+5/+10/+15/proposal + thresholds candidate generation

DoD:

- Python/JS market metrics numerical parity
- existing inflow parity 계속 green
- no second uncontrolled formula copy

## Stage C — Structural Response Surface + Marginal Economics

목적:

여러 후보금리에 low/base/high surface와 incremental/marginal metrics를 계산한다.

기존 v1 coefficient 변경 없음.

DoD:

- same rate = baseline invariant
- higher/lower direction tests
- marginal denominator guard
- cost unit tests
- term 6/12/24/36 tests
- stress band != prediction interval contract

## Stage D — Decision Cockpit UX

목적:

- Decision Strip
- Market Position Ladder
- Market Step Impact
- Response Curve
- Candidate table
- progressive disclosure

예상 주요 파일:

```text
strategy_decision_cockpit.py
strategy_decision_*_presentation.py
web/templates/strategy.html
scripts/strategy_*_smoke.js
```

구현 전 실제 최종 HTML composition path를 다시 확인한다.

DoD:

- desktop 1280 / 1440
- mobile 390
- overflow 없음
- chart/table 숫자 실제 engine contract와 일치
- existing map/preferences/market evidence 회귀 없음
- user input interaction smoke

## Stage E — Objective / Constraint Finder

목적:

명시적 사용조건으로 `minimum satisfying rate` 탐색.

초기 default는 factual market target만 활성화하는 안을 우선 검토한다.
Structural amount target은 caveat와 함께 optional로 제공한다.

DoD:

- no automatic recommendation wording
- no probability language
- exact boundary tests
- impossible condition returns unavailable/none

## Stage F — Provider Adapter

목적:

현재 structural provider와 향후 private provider가 같은 sanitized result shape를 consumer에 제공하도록 한다.

이번 Stage에서도 private endpoint는 만들지 않는다.

DoD:

- structural fallback works
- unavailable provider fails closed
- no private metadata fields
- #168 allowlist contract stays authoritative

## Stage G — External Prior Evidence Gate

research-only PR부터 시작한다.

```text
public data audit
→ method proposal
→ Fable/user review
→ GO/NO-GO
```

NO-GO면 coefficient는 그대로 유지한다.

## Stage H — Integrated verification / release-readiness

기능구현이 모두 끝난 뒤 별도 통합 검증.

- full CI
- targeted engine CI
- Python/JS parity
- production-like R2 restore if available
- isolated Strategy build
- Chrome desktop/mobile
- actual current market sample numeric spot-check
- no internal metadata leak
- release gate remains OFF

Release Gate ON은 별도 사용자 승인사항이다.

---

# 13. PR 의존성 원칙

```text
#168 E1A boundary
   ↓
Stage A Market Position
   ↓
Stage B Browser parity
   ↓
Stage C Response/Economics
   ↓
Stage D UX
   ↓
Stage E Objective finder
   ↓
Stage F Provider adapter
```

Stage G public prior research는 A~C와 병렬 **조사**는 가능하지만,
coefficient/model behavior 변경은 별도 승인 전 금지한다.

각 구현 Stage는 기본적으로 독립 PR이다.

이전 Stage가 merge되지 않았는데 다음 Stage가 필요하면 stacked PR임을 명시한다.

---

# 14. 테스트 전략

## 14.1 Domain unit tests

### Market position

- empty
- one product
- all ties
- duplicate rates
- proposal below min
- above max
- exactly top10 cutoff
- exactly top25 cutoff
- +1bp crossing
- down-rate crossing
- floating tolerance

### Structural response

기존 golden vectors 보존 + candidate grid vectors 추가.

### Economics

- positive incremental
- zero incremental
- negative incremental
- 6/12/24/36M annualization
- currency/rate units

## 14.2 Contract tests

- documentation formulas vs code
- public payload allowlist
- Strategy market metric labels
- `비교상품` vs `경쟁사` 용어 오용 방지
- stress range vs prediction interval wording

## 14.3 Browser parity

Node에서 built HTML의 실행 함수를 추출해 Python 결과와 비교한다.

마커가 없으면 skip하지 않고 fail.

## 14.4 Runtime E2E

실제 build에서:

- selected sector change
- term change
- base/bonus input
- prediction inputs
- market rank
- ladder
- curve
- candidate table

이 모두 동기화되는지 확인한다.

## 14.5 Visual QA

최소 viewport:

- 1440×900
- 1280×800
- 390×844

검사:

- 우선순위
- 숫자 잘림
- chart labels
- tooltip
- scroll
- sticky/topbar 충돌
- text contrast

---

# 15. 실제 데이터 Evidence Gate

구현 전/후 production-like 데이터가 가능한 경우 반드시 숫자 spot-check를 한다.

예:

```text
선택: savings_bank / 12M
N = 실제 비교상품 수
current 고려 최고금리 = 실제 UI값
proposal = current + 10bp

수작업:
higher_count
rank
top10 cutoff
±5bp crowding
crossed product count

engine 결과와 대조
```

테스트 fixture만 통과했다고 actual market metric이 맞다고 선언하지 않는다.

---

# 16. 용어 계약

## 허용

- 시장 관측
- 현재 snapshot
- 비교상품
- 공동순위
- 상위 비율
- 금리구간 통과
- 구조적 시나리오
- 민감도 범위
- 표면이자비용
- 조건충족 최소금리

## 금지 또는 강한 제한

- 예측 정확도 향상 — 내부실적 검증 전 금지
- 최적금리 — objective + calibration 전 금지
- 추천금리 — 자동 추천 금지
- 신뢰구간 — 실제 statistical interval 없으면 금지
- 달성확률 — calibrated probabilistic model 없으면 금지
- 실제 조달원가 — FTP 미반영이면 금지
- 경쟁사 n곳 추월 — compare-unit이 product이면 금지
- deposit beta — 현재 `beta_new`와 혼용 금지

---

# 17. 데이터/보안 경계

Public repo에 절대 들어오면 안 되는 것:

- 고려저축은행 내부 신규수신 원본
- 만기도래/재예치 원본
- 내부 상품별 실적
- 내부 coefficient
- private feature importance
- training/test metrics
- private model registry
- file/sheet/column provenance
- local private repo 경로를 runtime metadata로 노출한 값

문서에는 구조와 contract만 기록한다.

실제 private local repo 상태는 public Issue/PR에 세부 데이터를 복제하지 않는다.

---

# 18. 성능 계획

현재 Strategy 전용 slice와 aggregate cache를 보존한다.

Market position 계산은 후보금리 수 × 비교상품 수 수준이므로 초기에는 충분히 작지만,
구현 시 실제 runtime을 측정한다.

필요하면:

- sorted rate vector 1회 생성
- binary search rank
- prefix/count based crowding
- candidate dedupe

로 최적화한다.

성능 최적화를 이유로 의미계약을 바꾸지 않는다.

---

# 19. UX 성공기준

금리담당자가 별도 설명 없이 다음을 구분할 수 있어야 한다.

### 10초

- 현재금리
- 제안금리
- 현재/제안 시장순위
- 상위 10% 진입 여부

### 20초

- +5/+10bp의 시장위치 변화
- 주변 금리 밀집도
- 구조적 총수신 범위

### 30초

- incremental total
- 표면비용
- 다음 5bp의 marginal trade-off
- 어떤 값이 factual이고 어떤 값이 scenario인지

이 목표를 user test 없이 달성했다고 단정하지 않는다.
최소한 visual hierarchy/smoke contract로 기계검증하고, 사용자가 preview에서 최종 판단한다.

---

# 20. Rollback 전략

각 Stage는 독립적으로 되돌릴 수 있게 한다.

- Market Position: 신규 derived service 제거
- Response Surface: v1 single-point fallback 유지
- UX: 기존 #166 cockpit fallback 유지
- Objective finder: optional panel 제거 가능
- Provider adapter: structural fallback 유지

기존 `inflow-structural-v1`을 삭제하지 않는다.

---

# 21. Fable 리뷰 요청사항

Fable은 이 계획을 **구현 승인 관점에서 비판적으로 리뷰**한다.

다음 항목을 반드시 확인한다.

## A. 금융/수학 계약

1. rank / top share / cutoff 정의가 실제 UI 의미와 맞는가?
2. tie/crowding/crossing의 경계조건이 모호하지 않은가?
3. marginal cost 식의 단위와 해석이 맞는가?
4. structural scenario를 forecast처럼 오인시킬 표현이 남아 있는가?
5. market position과 amount response를 분리한 것이 적절한가?

## B. 데이터 계약

1. stable product representative를 primary compare-unit으로 유지하는 것이 맞는가?
2. combined savings-bank + mutual-finance에서 비교단위 왜곡 가능성이 있는가?
3. sector별 rate basis 차이가 rank/crowding 해석을 훼손하는가?
4. current strategy slice로 필요한 metric을 모두 재현할 수 있는가?

## C. Architecture

1. Python/JS parity 전략이 충분한가?
2. Stage 분리가 과도하거나 부족하지 않은가?
3. #168 public forecast contract와 충돌하는 부분이 있는가?
4. private provider 연결 시 provenance leakage가 생길 경로가 있는가?
5. 기존 presentation injection chain에서 유지보수성이 악화될 위험이 있는가?

## D. UX

1. 정보가 너무 많아 의사결정 속도를 오히려 떨어뜨리는가?
2. Market Ladder / Response Curve / Candidate Table의 중복이 과도한가?
3. factual vs structural provenance가 충분히 명확한가?
4. 모바일에서 실제 사용 가능한가?
5. 자동 추천을 하지 않으면서도 실무가치를 충분히 만드는가?

## E. Verification

1. 실제 시장숫자 spot-check가 충분한가?
2. golden vector / browser parity / drift probe가 충분한가?
3. visual QA와 runtime E2E 범위가 충분한가?
4. 어떤 미검증 항목이 남는가?

### Fable 최종 형식

```text
VERDICT: APPROVE | CHANGE REQUESTED

P0 Blocking:
- ...

P1 Major:
- ...

P2 Improvement:
- ...

P3 Optional:
- ...

Recommended Stage / boundary changes:
- ...

Questions requiring user decision:
- ...
```

**P0/P1이 하나라도 남아 있으면 구현을 시작하지 않는다.**

---

# 22. 사용자 결정이 필요한 항목 — Fable 리뷰 후 확정

아래는 지금 임의 확정하지 않는다.

1. 기본 금리 candidate 범위를 `-10~+20bp`로 둘지 더 넓힐지
2. primary UI에서 low/base/high 중 base line을 얼마나 강조할지
3. `annualized marginal surface cost rate`를 기본 화면에 노출할지
4. Objective Finder에서 structural amount target을 첫 버전에 넣을지
5. Response Curve와 Candidate Table을 동시에 기본 노출할지
6. External Prior Research를 Stage D와 병렬로 바로 시작할지

Fable 리뷰 의견을 받은 뒤 사용자에게 선택지를 좁혀 확인한다.

---

# 23. 계획 완료 기준

이 review plan 단계의 완료는 **코드 구현 완료가 아니다.**

완료 조건:

- [x] latest main 확인
- [x] #166 current UX 확인
- [x] #167/#168 dependency 확인
- [x] current `inflow-structural-v1` 공식 확인
- [x] current browser rank/top10 계산 확인
- [x] current Strategy universe/rate-basis 확인
- [x] existing external feature/history contract 확인
- [x] Public Structural v2 boundary 정의
- [x] staged PR 계획 정의
- [x] test/runtime/visual verification 계획 정의
- [x] confidential/public boundary 유지
- [ ] Fable review
- [ ] P0/P1 해소
- [ ] 사용자 구현 승인

따라서 **현재 상태에서는 구현 금지**다.

Refs #169 #167 #168
