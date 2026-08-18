# Stage D1 — Preference Intelligence 계약

```yaml
date: 2026-08-18
repository: dekt-oss/bank-rate-collector
base: main
related_issue: 108
production_strategy_release_gate: OFF
stage: D1
```

## 목적

내부 실적자료가 오기 전에도 현재 수집 데이터만으로 객관화할 수 있는 우대조건 시장구조를 만든다.

D1이 답하는 질문은 다음이다.

> 어떤 우대조건이 시장 전체와 상위금리 상품에서 얼마나 자주 사용되며, 당사 현재 상품은 어떤 조건 조합을 사용하고 있는가?

D1은 **우대조건이 실제 수신유입을 증가시킨다고 추정하지 않는다.** 실제 달성률, 증분유입, 재예치 효과, 1bp당 효율은 내부 실적자료가 필요한 D2/E 범위다.

## 입력 계약

Strategy 전용 canonical slice를 사용한다.

필수 열:

- `sector`
- `institution`
- `product_id`
- `term_months`
- `max_rate` — Strategy에서 이미 확정된 비교금리
- `preference`
- `preference_status`
- `preference_tags`

따라서 NH의 현재 e-joy base+add 등 기존 Strategy rate contract를 재구현하지 않는다.

## Scope

- sectors: `savings_bank`, `cu`, `kfcc`, `nh_local`
- terms: `6M`, `12M`, `24M`, `36M`
- product type은 Strategy slice가 이미 `term_deposit`으로 제한한다.
- 대표단위: stable `product_id + term + geography`

같은 대표단위에 여러 행이 있으면 Strategy `max_rate`가 가장 높은 행 하나를 사용한다.

## 우대조건 상태 계약

기존 taxonomy의 세 상태를 절대 합치지 않는다.

- `present`: 우대조건이 명시되어 있음
- `none`: 원천이 우대조건 없음이라고 명시
- `missing`: 원천이 해당 정보를 제공하지 않음

특히 `missing`을 `none`으로 세지 않는다.

## Coverage

각 scope에서 다음을 표시한다.

```text
total_offering_count
known_preference_count = present + none
present_count
none_count
missing_count
known_preference_share
```

`known_preference_share < 50%`면 `coverage_status = low`로 표시한다.

이 경고는 새마을금고처럼 원천 자체가 우대조건 정보를 충분히 주지 않는 경우 시장비교가 과도하게 해석되는 것을 막는다.

## 상위금리 상품 정의

현재 Strategy 비교금리 기준 상위 `ceil(10%)` 상품을 top tier로 정의한다.

```text
top_tier.definition = top_ceil_10pct_by_strategy_max_rate
```

기존 화면의 `상위 10% 진입선`과 같은 percentile 개념이며 실제 ordinal TOP10과 혼동하지 않는다.

## 조건별 지표

표준 taxonomy code별로 계산한다.

```text
market_count
market_share
top_tier_count
top_tier_share
top_tier_lift_pp = top_tier_share - market_share
```

분모는 `present + none`, 즉 우대조건 정보가 실제로 알려진 상품만 사용한다.

예:

```text
DIGITAL_CHANNEL
시장 20%
상위금리 상품 45%
상위군 lift +25%p
```

이는 **상위금리 상품에서 해당 조건이 더 많이 쓰인다는 기술통계**다. 해당 조건 때문에 금리가 높아졌거나 수신이 늘었다는 인과관계가 아니다.

## 당사 비교

저축은행 scope에 고려저축은행이 있으면 다음을 별도 제공한다.

- 당사 offering count
- 당사 최고 Strategy rate
- preference status counts
- 당사 표준 preference codes / labels
- 원문 sample 최대 5건

이를 시장/상위군 조건구성과 비교하는 UI는 후속 D2 presentation에서 구현한다.

## 명시적 비범위

D1에서는 다음 값을 만들지 않는다.

- 실제 우대조건 달성률
- 조건별 신규수신 증분효과
- 조건별 재예치 효과
- 조건별 중도해지 감소효과
- 우대 1bp당 증분수신
- 추가 이자비용 대비 효율
- FTP 반영 경제성
- 최적 우대조건 조합

이 값들은 내부 실적자료가 들어온 뒤 D2/E에서 보정한다.

D1 output에는 이를 명시하기 위해:

```text
effect_calibration = not_available_without_internal_performance_data
```

를 고정한다.

## Release / UI

D1은 데이터 엔진 계약만 구현한다. B/C2와 Strategy 레이아웃 충돌을 만들지 않기 위해 이번 PR에서 화면 배치를 변경하지 않는다.

Production Strategy Release Gate는 계속 OFF다.
