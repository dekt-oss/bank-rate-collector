# 수신금액 예측엔진 v1 — 내부 실적 보정 전 구조모형

```yaml
document_type: implementation_spec
status: experimental
created_at: 2026-08-16
target_repository: dekt-oss/bank-rate-collector
stacked_on: feat/strategy-dashboard-korea-map
inherits: docs/specs/20260812-strategy-dashboard-v1.md
```

## 1. 목적

기존 전략 대시보드의 수신액 계산기는 사용자가 `기준 월 수신액`과
`+0.10%p당 변화율`을 직접 넣는 단순 선형 what-if였다. 이번 v1은 이를
**신규자금과 만기 재예치를 분리하는 수신금액 예측엔진**으로 교체한다.

다만 현재 canonical DB에는 고려저축은행 상품별 실제 신규취급액·만기도래액·
재예치액의 장기 이력이 없다. 따라서 v1을 `학습완료` 또는 `내부 실적 기반`으로
표현하지 않는다. 모델 상태는 `uncalibrated`이며, 현재 계수는 실제 은행 실적에서
추정한 업계계수가 아니라 **민감도 스트레스 밴드**다.

내부 실적을 확보하면 UI와 계산 인터페이스는 유지하고 계수만 재추정하여
`calibrated` 상태로 전환하는 것을 목표로 한다.

## 2. 근거와 제한

예금 수요는 절대금리만이 아니라 다른 금융기관 대비 상대금리와 기회비용에
반응한다. Federal Reserve의 예금수요 모형도 개별 은행 금리와 평균 예금금리의
상대관계를 수요함수에 포함한다. New York Fed는 은행이 예금금리를 올릴 때
예금 flow가 얼마나 반응하는지를 별도 민감도로 추정하며, 그 민감도가 시기별로
크게 달라짐을 보여준다. 한국은행도 수신경쟁을 예금금리 스프레드로 관찰하고,
비은행권의 금리인상과 수신유입을 함께 분석한다.

따라서 외부 연구의 단일 탄력성을 고려저축은행 계수로 복사하지 않는다.
본 엔진은 **계산구조와 데이터 계약을 먼저 고정**하고, 실제 내부 실적으로
계수를 보정하는 방향을 채택한다.

## 3. 입력 단위와 기준

금리는 화면과 동일하게 `%` 단위의 숫자를 사용한다. 예를 들어 `3.70`은
연 3.70%다.

- `10bp = 0.10%p`
- 금액 단위: 억원
- 기간 단위: 개월
- 현재 기준금리: 선택기간의 고려저축은행 현재 대표 최고금리
- 시장 상대기준: 선택기간의 상위 10% 진입선
- 기준 신규자금: 현재 당사금리에서의 최근 월 신규취급액 수준
- 만기도래액: 다음 분석기간에 만기 도래하는 금액
- 현재 재예치율: 현재 당사금리에서 관측한 재예치율

현재 당사 대표금리가 없으면 금액 예측을 하지 않는다.

## 4. 상대금리 변수

```text
current_gap = current_own_rate - market_top10_rate
proposed_gap = proposed_rate - market_top10_rate
relative_change = proposed_gap - current_gap
                = proposed_rate - current_own_rate
rate_steps = relative_change / 0.10%p
```

즉 현재 신규수신 실적을 anchor로 사용할 때, 예측에 필요한 것은 시장 자체를
고정한 상태에서 **당사 상대포지션이 몇 10bp 이동하는지**다. 같은 시점의
`top10_rate`를 두 번 더해 효과를 중복 계산하지 않는다.

시장 상위10%선과 예상 순위는 포지션 설명 및 향후 보정모형의 feature로 보존한다.

## 5. 신규자금 모형

신규자금은 음수가 될 수 없고 금리효과가 누적될 때 선형식이 비정상적인 음수를
만들지 않도록 log-link를 쓴다.

```text
log_effect = beta_new × rate_steps
log_effect = clamp(log_effect, -1.5, +1.5)

predicted_new_money = baseline_new_money × exp(log_effect)
```

`beta_new`는 +10bp 상대포지션 이동당 log 신규자금 변화량이다.

## 6. 재예치 모형

재예치율은 0~100% 범위 확률이므로 logistic link를 쓴다.

```text
p0 = current_rollover_rate / 100
logit(p1) = logit(p0) + gamma_rollover × rate_steps
p1 = logistic(logit(p1))

predicted_rollover = maturity_amount × p1
```

입력 재예치율의 계산 안정성을 위해 내부적으로 0.1%~99.9% 범위로 clamp한다.
화면 입력 자체는 0~100%를 허용한다.

## 7. 총수신 및 비용

```text
predicted_total = predicted_new_money + predicted_rollover
baseline_total = baseline_new_money + maturity_amount × p0
incremental_total = predicted_total - baseline_total
```

표면이자비용은 현재금리 baseline과 제안금리 예상수신 각각의 단순 이자를 먼저
계산한 뒤 차이를 낸다. 제안금리의 `예상총수신 × 금리차`만 계산하면 새로 늘어난
수신액 자체에 지급할 전체 이자를 누락하므로 사용하지 않는다.

```text
term_factor = term_months / 12

baseline_surface_interest
 = baseline_total × current_own_rate / 100 × term_factor

predicted_surface_interest
 = predicted_total × proposed_rate / 100 × term_factor

surface_interest_delta
 = predicted_surface_interest - baseline_surface_interest
```

단위는 억원이다. 금리·수신량 변화 조합에 따라 음수(비용 절감)일 수도 있다.

이 값은 FTP, 유동성 프리미엄, 중도해지, 세금, 복리효과, 실제 평균잔존기간을
반영한 조달원가가 아니다. UI에 `추가 표면이자비용`이라고 명시한다.

## 8. 미보정 스트레스 밴드

내부 실적이 없는 상태에서 하나의 숫자를 정답처럼 제시하지 않는다. 아래 계수는
**업계 추정치가 아니라 엔진 동작과 민감도 점검을 위한 사전 스트레스 가정**이다.

| 시나리오 | beta_new / +10bp | gamma_rollover / +10bp |
| --- | ---: | ---: |
| 저민감 | 0.02 | 0.04 |
| 기준 | 0.05 | 0.08 |
| 고민감 | 0.10 | 0.16 |

신규자금 log-effect는 ±1.5에서 제한한다. 예측 범위는 세 시나리오 결과의
최솟값~최댓값으로 표시하며, 기준 시나리오를 중앙 결과로 표시한다.

## 9. 화면 입력과 출력

기존 `기준 월 수신액 + 사용자가 입력하는 단일 민감도`는 제거한다.

사용자 입력:

- 최근 월 신규수신 기준액(억원)
- 다음 만기도래액(억원)
- 현재 재예치율(%)

자동 입력:

- 제안 최고금리
- 선택기간 고려저축은행 현재 최고금리
- 시장 상위10% 진입선
- 시장 예상순위

출력:

- 기준 예상 신규자금
- 기준 예상 재예치액 및 재예치율
- 기준 예상 총수신액
- 저/기준/고민감 시나리오 총수신 범위
- 현재 대비 예상 총수신 증감
- 추가 표면이자비용 증감
- 현재→제안 상대금리 이동 bp
- 모델 상태 `내부 실적 미보정`

## 10. 향후 내부 실적 보정 계약

고려저축은행에서 최소 다음 집계를 확보하면 계수 추정을 시작한다.

```text
기준일(일/주)
상품코드 / 가입기간
실제 적용금리 또는 대표 최고금리
신규취급액
신규계좌수(가능하면)
만기도래액
재예치액 또는 재예치율
중도해지액(가능하면)
가입채널
특판·캠페인 여부
```

보정 단계에서는 시장금리 history와 날짜를 맞춰 다음 후보 feature를 비교한다.

- 상위10%선 대비 gap
- 시장 평균/중앙값 대비 gap
- TOP5 평균 대비 gap
- 시장 순위 percentile
- 당사 금리 변경폭
- 만기도래액
- 채널 / 캠페인 / 계절성

out-of-sample 검증에서 가장 안정적인 feature set을 선택하고, 모델 상태를
`calibrated`로 바꾼다. 실적 데이터가 없는데 calibrated로 표시하는 것은 금지한다.

## 11. 안전 계약

- 현재 최고금리 `NULL`을 기본금리로 대체하지 않는다.
- 비교상품 source precedence와 stable product identity 계약을 바꾸지 않는다.
- DB/schema/migration/collector를 변경하지 않는다.
- 수신액 입력이 없으면 금액을 생성하지 않는다.
- 현재 당사 대표금리가 없으면 금액을 생성하지 않는다.
- NaN/Infinity/음수 금액 입력을 계산에 사용하지 않는다.
- 재예치율은 0~100%만 허용한다.
- 결과는 `예측`이지만 `내부 실적 미보정 구조모형`임을 항상 표시한다.
- 실제 유입을 보장한다고 표현하지 않는다.
- production Release Gate는 이 작업에서 켜지 않는다.

## 12. 검증 기준

- Python 엔진과 UI가 동일한 rate-step / exponential / logistic 계약을 사용한다.
- 0bp 변화에서는 신규자금·재예치율·총수신액이 baseline과 동일하다.
- +10bp에서 각 시나리오가 정의된 방향으로 반응한다.
- 금리 인하시 신규자금과 재예치율이 반대 방향으로 움직인다.
- 재예치율은 항상 0~100%다.
- 극단 rate-step에서도 신규자금 log-effect guardrail이 적용된다.
- 기간에 따른 표면이자비용 단위가 맞다.
- 표면이자비용 증감은 baseline 총이자와 제안 총이자의 차이여야 한다.
- 기존 시장순위·TOP10·지도·부산 drill-down 계약을 유지한다.
- 전체 CI와 Strategy Preview build가 통과한다.
