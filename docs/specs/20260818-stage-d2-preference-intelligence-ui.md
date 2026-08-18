# Stage D2 — Product / Preference Intelligence UI

```yaml
date: 2026-08-18
repository: dekt-oss/bank-rate-collector
base: main
related_issue: 108
production_strategy_release_gate: OFF
stage: D2
```

## 목적

D1의 객관적 우대조건 시장구조를 Strategy 화면에서 상품설계 근거로 읽게 한다.

핵심 질문은 다음이다.

> 시장 전체와 상위금리 상품에서 어떤 우대조건이 얼마나 자주 사용되며, 당사 현재 구조와 무엇이 다른가?

## 중요한 경계

D2는 **인과효과 분석이 아니다.**

상위금리 상품에서 특정 우대조건이 더 자주 관찰되어도 그 조건 때문에 수신이 늘었다고 해석하지 않는다.

따라서 화면에 항상 다음을 명시한다.

> 구조 비교이며 수신효과 추정이 아닙니다. 실제 효과는 내부 실적 보정 후 D2/E에서만 판단합니다.

## 입력계약

Strategy canonical slice에서 이미 계산된 D1 `preference_intelligence`만 사용한다.

- stable product + term + geography 대표단위
- Strategy 최고금리 기준 상위 `ceil(10%)`
- `missing != none`
- category denominator = `present + none`
- `effect_calibration = not_available_without_internal_performance_data`

브라우저가 D1 계산을 재구현하지 않는다.

## 화면

Selector:
- 업권: 저축은행 / 신협 / 새마을금고 / 농·축협
- 기간: 6 / 12 / 24 / 36개월

Summary:
- 우대정보 제공률
- 상위금리 진입기준
- 상위군 우대정보 제공률

Category table:
- 조건명
- 시장 전체 share
- 상위금리상품 share
- 차이 `top_tier_lift_pp`

당사:
- 고려저축은행 대표상품 수
- 최고금리
- 표준 우대조건 태그
- 원문 근거 펼침

## Low Coverage

알려진 우대정보 비중이 50% 미만이면 경고한다.

`missing`은 절대 `none`으로 표현하지 않는다.

## 비범위

- 실제 우대조건 달성률
- 신규수신 증분효과
- 재예치 효과
- 우대 1bp당 수신효과
- FTP 반영 경제성
- 최적 우대조건 조합
- 내부 실적 적재
- Strategy Release Gate ON

위 항목은 내부 실적자료가 들어오는 Stage E/D3에서 다룬다.
