# Public Structural Engine v2 + 금리결정 Cockpit — Final Implementation Plan

```yaml
document_type: implementation_plan
status: approved/implementation-authorized
date: 2026-08-22
repository: dekt-oss/bank-rate-collector
issue: 169
parent_issue: 167
stacked_on_pr: 168
review_pr: 170
main_reference: b5fca6b5add85ebb4a6ca2b04f9b21dd75baf2b1
review_result: CHANGE_REQUESTED -> accepted_and_resolved_in_plan
implementation_authorization: explicit_user_approval_2026-08-22
merge_policy: explicit_user_approval
production_strategy_release_gate: unchanged_off
internal_data: prohibited_in_public_repo
```

---

## 0. 지위와 목적

이 문서는 PR #170의 review plan과 2026-08-22 Claude/Fable 리뷰를 반영한 **최종 구현 기준**이다.
리뷰는 종료됐고 사용자가 구현 진행을 승인했다. 따라서 이 문서 이후 별도 Fable 재리뷰를 Gate로 두지 않는다.

다만 아래는 계속 금지한다.

- 사용자 명시 승인 없는 merge
- Production Strategy Release Gate 변경
- 실제 내부자료, 내부계수, training diagnostics의 public repo 반입
- low/base/high stress assumption을 검증된 예측계수로 표현
- stress range를 prediction/confidence interval로 표현
- 내부자료 없는 상태에서 `추천금리`, `최적금리`, `달성확률` 자동 출력
- collector / DB schema / migration / source precedence / stable product identity의 임의 변경

한 문장 목표:

> 내부자료 없이도 **실제 시장에서 당사 금리의 위치와 금리변경 시 시장 구조가 어떻게 달라지는지**를 사실로 계산하고, 별도의 **미보정 구조 시나리오**와 **표면비용**을 인과처럼 섞지 않은 채 한 화면에서 비교할 수 있는 Decision Cockpit을 만든다.

향후 confidential calibrated engine은 같은 public forecast contract를 통해 숫자만 교체하고 UX는 재사용한다.

---

# 1. 리뷰 반영 최종 결정

## 1.1 P0-1 — 공동순위의 primary 표현

`rank / N × 100` 단일 상위비율은 primary UI에서 폐기한다.

제안금리의 순위는 **공동순위 범위**로 표시한다.

```text
best_rank  = higher_count + 1
worst_rank = higher_count + tie_competitor_count + 1
```

`tie_competitor_count`는 counterfactual universe에서 제안금리와 같은 금리를 가진 **다른 비교상품 수**다.
제안상품 자체는 tie count에 포함하지 않는다.

표현 예:

```text
공동 8~25위 / 112개
동률 비교상품 17개
```

동률이 없으면:

```text
8위 / 112개
```

으로 축약한다.

`상위 10% 진입선`, `상위 25% 진입선`은 별도의 cutoff 계약으로 유지한다.
순위범위를 `% percentile`로 변환해 headline으로 사용하지 않는다.

## 1.2 P0-3 — 금리 동일성 / tolerance

두 개념을 분리한다.

### 경제적 동일금리

저장 계약 `Rate`의 `DECIMAL(7,4)` 의미와 동일하게 **소수점 4자리로 정규화한 금리값이 같을 때만 동률**로 본다.

```text
normalized_rate = quantize(rate, 0.0001%p)
```

근거:

- `src/rate_monitor/db/types.py`
- `RATE_EXPONENT = Decimal("0.0001")`

`3.5450%`와 `3.5500%`를 1bp tolerance로 임의 동률 처리하지 않는다.

### 부동소수 안전장치

Python/JS 계산 과정에서의 float epsilon은 경제적 동률 규칙이 아니다.
필요하면 내부 비교 안전장치로만 사용하고 UI/domain contract에는 노출하지 않는다.

## 1.3 P0-4 — 제안금리 counterfactual universe

시장위치를 계산할 때 당사 현재 anchor 상품을 그대로 경쟁상품으로 남기지 않는다.

계약:

1. 선택 시장 universe에서 `anchor_product_id`인 현재 당사 대표상품 1개를 제거한다.
2. 같은 자리에 가상의 `proposal` 상품을 제안금리로 삽입한다.
3. 전체 비교상품 수 `N`은 유지한다.
4. 다른 당사 상품이 실제 별도 stable product라면 유지한다.
5. anchor가 없으면 시장위치 counterfactual은 fail-closed `unavailable`이다.

따라서 자기 자신을 `통과`, `동률`, `crowding`으로 세지 않는다.

## 1.4 P0-2 — 시장위치와 구조적 수신금액의 인과 분리

Public Structural v2의 금액모형은 **자사 금리 변화폭에만 반응하고 시장순위·시장밀집도에는 반응하지 않는다.**
이 사실을 숨기지 않는다.

상시 공시 문구의 의미:

> 구조적 수신 시나리오는 현재 대비 당사 금리변화폭에 대한 미보정 민감도입니다. 시장 순위·밀집도 변화는 금액식에 직접 반영되지 않습니다.

UX에서는 `시장위치 개선 → 수신증가`로 읽히는 화살표/문장을 금지한다.
두 영역은 같은 후보금리 축을 공유하지만 **원인-결과 관계처럼 연결하지 않는다.**

## 1.5 structural amount target finder 제외

다음은 Public v2 초기 범위에서 제외한다.

- `목표 총수신 X억원을 충족하는 최소금리`
- `구조 시나리오상 목표수신 최소금리`
- 구조금액을 이용한 자동 rate finder

현재 금액모형이 시장위치를 반영하지 않으므로 시장기반 의사결정 답처럼 보일 위험이 크다.

허용되는 finder는 factual market target뿐이다.

- 상위 10% cutoff 도달 최소금리
- 상위 10% cutoff **초과** 최소금리
- 상위 25% cutoff 도달/초과 최소금리
- 시장 최고와 동률/초과 최소금리

UI에서 `도달`과 `초과`를 구분한다.

## 1.6 threshold crossing 계약

단순 반개구간 `r0 < ri <= r1` 카운트는 사용하지 않는다.
각 비교상품에 대해 before/after relation을 직접 분류한다.

관계:

```text
proposal > competitor : ahead
proposal = competitor : tied
proposal < competitor : behind
```

금리 인상 시:

- `newly_outpriced`: before가 `behind|tied`, after가 `ahead`
- `newly_tied`: before가 `behind`, after가 `tied`

금리 인하 시:

- `newly_lost_to`: before가 `ahead|tied`, after가 `behind`
- `newly_tied_down`: before가 `ahead`, after가 `tied`

따라서 `통과 n개` 한 숫자 대신 필요 시:

```text
엄격 우위 전환 +8개 · 새 동률 +18개
```

처럼 구분한다.

## 1.7 `rank efficiency` 삭제

`+5bp당 순위 개선 효율` 같은 비율형 지표는 초기 범위에서 삭제한다.

이유:

- 시장금리 분포는 계단형이라 임의 간격을 +5bp로 환산하면 외삽이 된다.
- 밀집구간일수록 숫자가 커져 `좋은 효율`처럼 오독될 수 있다.

대신 **실제 고정 5bp 이동 결과**만 factual delta로 보여준다.

```text
+5bp 시 공동순위 31~42위 → 17~28위
엄격 우위 전환 +13개
```

## 1.8 rollover 0/100% 경계 문제

현재 `inflow-structural-v1`은 exact 0/100%에서 zero-step만 원본 p0를 쓰고 non-zero step에서는 clamp anchor를 사용해 작은 금리 이동에서 불연속이 생길 수 있다.

v1을 과거 baseline으로 보존하고, Public Structural v2의 rollover transform은 다음으로 고정한다.

```text
if p0 == 0: p1 = 0
if p0 == 1: p1 = 1
otherwise:
  logit(p1) = logit(p0) + gamma * rate_steps
```

즉 exact boundary는 수학적 극한처럼 absorbing boundary로 유지하고, `(0,1)` 내부에서는 기존 logit shift를 그대로 쓴다.

DoD:

- current rate에서 정확히 baseline 유지
- tiny +rate에서 수신이 경계 clamp 때문에 갑자기 감소하지 않음
- tiny -rate에서도 불연속 없음
- 0%, 0.1%, 99.9%, 100% fixture
- Python/JS 동일 결과

## 1.9 marginal economics 계약

`전단계 marginal`은 임의 candidate union 전체에서 계산하지 않는다.
**고정 5bp grid의 인접점 사이에서만** 계산한다.

```text
3.50 → 3.55
3.55 → 3.60
3.60 → 3.65
```

시장 top10/top25/max threshold는 같은 차트의 marker로만 표시하고 marginal 분모의 step으로 섞지 않는다.

표시 가능:

- 5bp 추가 시 구조적 총수신 변화
- 5bp 추가 시 표면이자비용 변화
- 구조적 추가수신 1억원당 표면비용: 안정성 Gate 통과 시만 보조 표시

초기 UI에서 비노출:

- annualized marginal funding rate
- FTP 조달원가처럼 읽히는 표현

`delta_volume`이 너무 작은 구간은 ratio를 숨긴다. 절대 epsilon 하나로 판단하지 않고 상대변화까지 함께 Gate한다.

## 1.10 Pareto/dominance 제외

현재 양(+)의 stress coefficient에서는 금리 상승 시 구조적 총수신과 표면비용이 같이 증가해 Pareto frontier가 거의 전체 후보가 될 수 있다.

Public v2 초기 범위에서 Pareto/dominance 기능은 제외한다.

## 1.11 low/base/high 해석

`저민감 / 기준 / 고민감`은 **반응 민감도 이름**으로만 유지한다.
금리 인하에서는 고민감 시나리오가 더 크게 감소하므로 금액의 높고 낮음 순서가 뒤집힐 수 있다.

따라서 UI는:

- `저민감 반응`
- `기준 반응`
- `고민감 반응`

으로 표기한다.

band는 항상 실제 결과의 `min/max`로 그리며 `low=아래, high=위`라고 가정하지 않는다.

---

# 2. Target Architecture

```text
strategy-table.json
      │
      ├── Factual Market Position Engine
      │      ├─ counterfactual replace
      │      ├─ rank range / ties
      │      ├─ cutoff / gap
      │      ├─ crowding
      │      └─ relation transitions
      │
      └── Candidate Rate Grid
             │
             ├── Public Structural v2
             │      ├─ low/base/high response
             │      ├─ boundary-continuous rollover
             │      └─ stress range
             │
             └── Decision Economics
                    └─ fixed-5bp marginal surface cost

Factual Market Position ─────┐
Structural public forecast ──┼─> sanitized Decision View Model ─> Cockpit UX
Decision Economics ──────────┘

future:
Confidential Calibrated Engine
      └─> inflow-public-forecast-v1-compatible adapter
           └─> same Decision View Model / same Cockpit
```

중요: Cockpit은 structural 내부의 `beta`, `gamma`, `log_effect`, raw feature를 직접 소비하지 않는다.

---

# 3. Stage 계획

각 Stage는 별도 branch / Draft PR을 기본으로 한다. parent가 미merge면 stacked PR로 진행한다.
사용자 승인 없이 merge하지 않는다.

## Stage A0 — 정의 계약 + golden vectors

목표: Market Position의 모호한 정의를 코드 전에 고정한다.

산출:

- `market_position_contract` 문서/fixture
- 4-decimal rate normalization
- rank range / tie 계약
- anchor replacement 계약
- threshold relation transition 계약
- top10/top25 cutoff `도달` vs `초과`
- synthetic dense-tie golden vectors

필수 fixture:

1. 동률 없음
2. 제안금리에 대규모 동률
3. current rate 동률에서 +5bp
4. target rate 동률 도달
5. target rate 1bp 초과
6. anchor 상품 제거 전/후 self-count 방지
7. 단일상품 universe
8. 4-decimal 경계 (`3.5450` vs `3.5451`)

DoD:

- headline `% 상위비율` 없음
- self product를 crossing/crowding에 세지 않음
- Python/JS가 동일 golden vectors를 통과할 수 있는 contract 확정

## Stage A1 — Public Structural v2 boundary engine

목표: v1을 보존하면서 v2 rollover 경계를 연속적으로 만든다.

원칙:

- v1 파일/동작은 baseline으로 보존 가능
- v2는 동일 low/base/high coefficient를 사용하되 boundary transform만 명시적으로 수정
- 신규 임의 시장 coefficient 추가 금지
- 모델명/버전은 v1과 구분

검증:

- 0 / 0.1 / 60 / 99.9 / 100%
- zero step
- tiny ±0.0001%p
- ±1bp / ±5bp / ±10bp
- `market_top10` 변경 시 금액 불변성을 regression test로 **의도적으로 고정**
- 그 불변성을 UI disclosure contract에도 연결

## Stage B — Factual Market Position Engine

새 read-only pure service를 만든다.

입력 최소 계약:

```text
rates[]
anchor_product_id
anchor_rate
proposal_rate
```

각 row에는 최소:

```text
product_id
rate
```

출력:

```text
status
universe_count
proposal_rate
rank_best
rank_worst
tie_competitor_count
mean_rate
median_rate
top25_cutoff
top10_cutoff
market_max_rate
gap_*_bp
exact_tie_count
within_5bp_count
within_10bp_count
newly_outpriced
newly_tied
newly_lost_to
newly_tied_down
```

crowding count는 중첩값임을 필드/문구에서 명시한다.

Python canonical pure function + JS mirror + golden vector parity를 둔다.

## Stage C — Candidate grid + sanitized decision contracts

후보금리는 두 집합을 분리한다.

### Factual marker set

- current
- proposal
- top25 cutoff
- top10 cutoff
- market max

### Fixed economics grid

- current 기준 5bp 간격 범위
- 실제 UI 범위 안에서만 생성

threshold marker를 economics marginal step에 섞지 않는다.

Stage C부터 structural forecast output은 #168의 public forecast contract와 호환 가능한 shape로 adapter한다.

Stage D 이후 UI는 **그 public shape만 소비**한다.

## Stage D — Response Surface

각 fixed grid 금리점에서:

- low/base/high predicted new money
- rollover
- total
- incremental total
- surface interest delta
- actual min/max stress band

을 계산한다.

상시 disclosure:

> 금액 시나리오는 당사 금리변화폭에 대한 미보정 민감도이며 시장순위·밀집도는 금액식에 직접 반영되지 않습니다.

시장 threshold는 curve 위 marker일 뿐 금액식을 바꾸지 않는다.

## Stage E — Marginal Economics

5bp 인접점 사이에서만:

```text
delta_total
delta_surface_interest
surface_cost_per_incremental_amount
```

을 계산한다.

ratio 표시 Gate:

- `delta_total > 0`
- 기준 total 대비 상대 delta가 너무 작은 구간은 ratio 숨김
- threshold는 config/근거와 함께 상수화하고 magic-number audit 수행

화면에서는 `표면비용`이라고 부른다.
FTP/ALM 경제원가라고 부르지 않는다.

## Stage F — Decision Cockpit UX

목표 읽기 순서:

1. 제안금리
2. 실제 시장 위치
3. 시장 threshold/crowding 변화
4. 별도 구획의 구조적 수신 stress scenario
5. 5bp 단위 표면비용 trade-off

### F1. Decision Strip

시장 factual과 structural amount 사이에 시각적 분리선/라벨을 둔다.

금지:

```text
순위 +20단계 → 수신 +9억
```

허용:

```text
시장 위치: 공동 17~29위 / 112개

미보정 구조 시나리오: 기준 229억 · stress range 224~238억
```

### F2. Market Position Ladder

- market max
- top10 cutoff
- top25 cutoff
- median
- current
- proposal

을 보여준다.

같은 금리는 marker를 겹쳐 놓고 `동률`을 표시한다.

### F3. Response Curve

- x: candidate rate
- y: structural total
- 저/기준/고민감 line
- min/max stress band
- current / proposal marker
- market top10/top25/max는 vertical reference marker

`confidence band`, `prediction interval` 표현 금지.

### F4. Candidate table

행은 고정 5bp grid + proposal을 우선한다.

열:

- 금리
- 공동순위 범위
- 동률 수
- top10/top25 상태
- base structural total
- stress range
- current 대비 structural delta
- 5bp marginal surface cost

proposal이 5bp grid 밖이면 별도 강조행으로 추가하되 marginal 열은 비교 불가 시 `—` 처리한다.

### F5. mobile

390px에서 읽기 순서를 반드시:

`금리 → 시장위치 → 구조 시나리오 → 비용`

으로 유지한다.
5열 Decision Strip을 무리하게 한 행에 압축하지 않는다.

## Stage G — factual-only constraint finder

허용:

- `상위 10% 진입선 도달 최소금리`
- `상위 10% 진입선 초과 최소금리`
- `상위 25% 진입선 도달/초과`
- `시장 최고 동률/초과`

결과는 결정이 아니라 **조건충족 값**으로 표시한다.

금지:

- 추천
- 최적
- 목표수신 달성 최소금리
- 달성확률

## Stage H — provider adapter

Public Structural provider와 future confidential provider를 같은 Decision View Model로 연결한다.

UI는 다음에 의존하지 않는다.

- coefficient
- private model id
- training metric
- source file
- feature importance
- sample size detail

#168 public allowlist를 벗어나는 private metadata는 fail-closed한다.

## Stage I — External Prior Evidence Gate

별도 연구 Stage다.

질문:

> 공개 업권/거시 시계열만으로 현재 임의 stress range의 크기에 근거를 줄 수 있는가?

가능한 자료:

- BOK policy rate
- 예금은행 신규취급 수신금리
- 1년 정기예금 신규취급 금리
- 업권 수신잔액
- repo가 보유한 시장금리 history

필수 조건:

- causality 주장 금지
- 은행 개별 elasticity로 해석 금지
- time-order / lag / regime / sample-size 검토
- out-of-sample 검증 불가하면 coefficient 변경 NO-GO

`NO-GO`는 정상 결과다.

## Stage J — 실제데이터/runtime/visual QA

코드 단위테스트만으로 완료하지 않는다.

필수:

- production-derived/actual Strategy dataset read-only spot check
- 실제 dense tie 사례 확인
- current/proposal self replacement 확인
- factual market output 손계산 대조
- structural 5bp grid sanity check
- marginal cost 분모 안정성 확인
- desktop Chrome
- 390px mobile Chrome
- overflow / tooltip / label collision
- release gate OFF 회귀

사용성 목표는 stopwatch 단정 대신 task-based smoke로 확인한다.

예:

1. 사용자가 현재/제안 시장위치를 찾을 수 있는가
2. factual vs scenario를 구분할 수 있는가
3. 5bp 추가비용을 찾을 수 있는가
4. stress band를 확률구간이라고 오해할 문구가 없는가

---

# 4. Python ↔ JS parity 강제

v2에서 browser 계산이 필요한 함수는 이름을 계약에 고정한다.

예정 canonical functions:

```text
normalize_rate
build_counterfactual_universe
market_position
relation_transition_counts
shift_rollover_probability
predict_structural_v2_scenario
predict_structural_v2_surface
```

JS mirror가 필요한 함수는 별도 JS module에 두고 parity test가 직접 import/execute한다.

DoD:

- frozen vectors를 Python과 JS 모두 실행
- 한쪽 formula를 일부러 바꾸면 deliberate drift probe가 실패
- built HTML에 별도의 임의 계산 formula가 새로 생기면 contract test가 실패하거나 명시적 allowlist 검토가 필요
- UI presentation은 raw structural formula를 직접 재구현하지 않음

---

# 5. Public / Confidential Boundary

## Public repo 가능

- structural v2 formula
- market-position formula
- synthetic fixture
- public source context
- sanitized forecast/view contract
- UI
- parity/backtest infrastructure for public model

## Public repo 금지

- 실제 내부 Excel/CSV
- source-specific internal column mapping
- 실제 내부계수
- private feature table
- training rows
- model diagnostics
- internal sample sizes/provenance
- private runtime path/id

Confidential engine은 local/private repository에서 관리한다.

---

# 6. 용어 계약

사용 가능:

- 실제 시장위치
- 공동순위 범위
- 동률 비교상품
- 상위 10% 진입선
- 엄격 우위 전환
- 미보정 구조 시나리오
- stress range / 민감도 범위
- 표면이자비용
- 조건충족 최소금리

사용 금지/제한:

- 예측 정확도 향상: private OOS evidence 전 금지
- confidence interval / prediction interval: 실제 통계구간 전 금지
- 추천금리 / 최적금리: objective + calibrated evidence 전 금지
- 달성확률: probability model 전 금지
- 한계조달원가: FTP/ALM 경제원가로 오해될 수 있어 초기 UI 금지
- `deposit beta`: 현재 신규수신 민감도 계수 이름으로 사용 금지

---

# 7. Verification Gate

각 Stage 공통:

1. Ruff targeted
2. targeted pytest
3. Python/JS parity 해당 시 필수
4. magic-number audit
5. `git diff --check`
6. GitHub Actions 결과 확인
7. actual-data read-only evidence 가능한 Stage에서 확인
8. UI Stage는 desktop/mobile browser smoke
9. adversarial self-review
10. 미검증 항목 명시

General CI가 main 선행 lint debt로 중단되면 이번 diff와 분리해서 보고하되 targeted gate를 대체한 것으로 과장하지 않는다.

---

# 8. Review disposition matrix

| Review | 최종 처리 |
|---|---|
| P0-1 rank/N 낙관편향 | 단일 % headline 폐기, 공동순위 범위 |
| P0-2 market-independent amount | 상시 불변성 공시 + causal layout 금지 + structural target finder 제거 |
| P0-3 tolerance 미정의 | 4-decimal exact normalization / float epsilon 분리 |
| P0-4 self product universe | anchor replace counterfactual |
| P1-1 crossing 비대칭 | relation transition 방식으로 재정의 |
| P1-2 rank efficiency | 삭제, 실제 5bp 이동만 표시 |
| P1-3 rollover discontinuity | v2 boundary-continuous transform |
| P1-4 marginal instability | fixed 5bp only + ratio stability gate |
| P1-5 Pareto 퇴화 | 제외 |
| P1-6 low/high reversal | 민감도 라벨 유지, min/max band 실제 계산 |
| P2-1 crowding 중첩 | 중첩임을 명시, 가산 해석 금지 |
| P2-2 provider shape | Stage C부터 public shape, Stage D 이후 UI는 그 shape만 소비 |
| P2-3 parity scope | 함수명 고정 + deliberate drift |
| P2-4 actual-data sanity | Stage J에 Layer A/B/C 모두 추가 |
| P2-5 UX 측정 | task-based smoke |
| P2-6 cutoff 동률 | `도달`/`초과` 별도 계약 |

---

# 9. 완료 기준

Public Structural v2 전체 작업은 아래가 모두 충족돼야 완료다.

- [ ] 공동순위 범위가 dense tie에서 손계산과 일치
- [ ] anchor self-count가 없음
- [ ] cutoff 도달/초과가 분리
- [ ] rollover 0/100 경계에서 tiny rate move discontinuity 없음
- [ ] structural amount가 market top10에 불변이라는 사실이 테스트와 UI에 명시
- [ ] low/base/high stress range가 통계구간으로 표현되지 않음
- [ ] marginal은 고정 5bp에서만 비교
- [ ] 추천/최적/달성확률 없음
- [ ] Cockpit이 sanitized view model만 소비
- [ ] private metadata leak test 통과
- [ ] desktop/mobile runtime smoke 통과
- [ ] actual Strategy data spot check 통과
- [ ] Release Gate unchanged
- [ ] 자동 merge 없음

이 문서가 이후 구현 Stage의 Source of Truth다.
