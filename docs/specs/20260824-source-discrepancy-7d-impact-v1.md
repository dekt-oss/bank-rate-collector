# Source discrepancy strict 7D impact v1

기준일: 2026-08-24

## 1. 목적

현재 source-source automatic comparison key는 6D다.

`institution + normalized product + product_type + term + join_channel + interest_method`

B1에서 FINLIFE `payment_method` F/S가 동일 6D 안에서 서로 다른 rate pair를 만들 때 51건을 `ambiguous_variant_dimension`으로 fail-closed하고 있음을 확인했다. B1a에서는 그중 counterpart가 없던 10건에 `정기예금` 이름 + FINLIFE `savingProductsSearch` + F/S 적립유형이라는 upstream semantic anomaly가 fresh raw 자체에 존재함을 확인했다.

이번 B2는 `payment_method`를 7번째 strict key로 **실제로 도입하지 않는다.** production snapshot에서 strict exact-7D를 가상 적용했을 때 비교 가능 표본과 구조적 부작용을 계량하여 후속 identity decision의 근거만 만든다.

## 2. 핵심 질문

1. FSB와 FINLIFE의 payment_method coverage가 실제로 대칭적인가.
2. row 비율뿐 아니라 6D key 기준 known/unknown coverage는 어떤가.
3. strict 7D를 적용하면 기존 exact comparable universe가 얼마나 유지되는가.
4. 현재 51건 ambiguity가 실제 exact-payment 비교로 해결되는가, 아니면 source-only로 이동하는가.
5. 같은 7D 안에 여러 upstream row가 남는 structural duplicate가 얼마나 존재하는가.
6. structural duplicate 중 금리가 같은 경우와 충돌하는 경우는 각각 얼마인가.
7. B1a의 아산/진주 10건처럼 upstream taxonomy anomaly가 있는 cohort를 7D 해결 사례로 잘못 해석하고 있지 않은가.

## 3. Strict 7D simulation contract

가상 key:

`6D + payment_method`

payment_method는 normalize 후 exact equality로만 비교한다.

- `F`와 `S`는 다름
- source가 값을 제공하지 않으면 `unknown`
- `unknown`은 `F/S` wildcard가 아니다
- `unknown == unknown`인 경우에만 exact key가 같다

이 contract는 현행 production matching을 바꾸지 않는다.

## 4. Coverage 지표

source별/product_type별로 두 수준을 모두 보고한다.

### Row coverage

- known payment_method rows
- unknown payment_method rows
- known row ratio

### 6D key coverage

- known-only payment 6D keys
- unknown-only payment 6D keys
- known+unknown mixed 6D keys
- known key ratio

FINLIFE가 F/S 두 row를 제공하기 때문에 row ratio만 보면 coverage가 과대해질 수 있으므로 6D key coverage가 decision의 주 지표다.

## 5. Structural duplicate fail-closed

같은 strict 7D key에 candidate row가 2개 이상이면 금리가 같더라도 clean comparable로 세지 않는다.

이유:

- Daishin A1에서 동명이 upstream product code(`JJ`, `JJ09`)가 확인됐다.
- rate pair가 우연히 같다는 사실은 stable identity가 하나라는 증거가 아니다.
- 7D를 추가해도 product-code/identity ambiguity가 남을 수 있다.

따라서 같은 7D 중복은 두 종류로 별도 계량한다.

1. `same_rate_duplicate`
2. `conflicting_rate_duplicate`

둘 다 strict-7D clean comparable universe에서는 제외한다.

## 6. Ambiguity transition

현재 `dimension_ambiguities` 각 항목을 다음으로 분류한다.

- `strict7d_has_exact_payment_candidate`
- `strict7d_turns_into_payment_source_only`
- `already_no_counterpart`

이 분류는 7D adoption recommendation 자체가 아니다. 특히 B1a의 10건은 upstream taxonomy anomaly cohort이므로 `already_no_counterpart`로 분리 해석한다.

## 7. Decision boundary

B2 결과만으로 7D를 적용하지 않는다.

후속 decision에서 최소 다음을 함께 판단한다.

- installment_savings FSB key-level payment coverage
- strict 7D clean comparable retention ratio
- source-only 증가량
- same-7D structural duplicate 수
- 51건 ambiguity transition 분포
- B1a taxonomy anomaly 10건 분리
- existing source product-code identity 문제

FSB coverage가 낮아 ambiguity가 단순 source-only로 사라지는 경우, `P0~P3 mismatch가 줄었다`는 이유로 7D를 채택하면 안 된다.

## 8. Safety

- production R2는 restore/read-only only
- canonical rate write 없음
- FSB/FINLIFE precedence 변경 없음
- `product_variants.payment_method` identity 변경 없음
- DB/schema/migration 변경 없음
- collector/scheduler 변경 없음
- ambiguity candidate 대표값 선택 없음
- Strategy / Production Strategy Release Gate 변경 없음

Machine scope:

- `production_state_mutated=false`
- `canonical_mutated=false`
- `source_precedence_changed=false`
- `identity_changed=false`
- `strict_7d_implemented=false`
- `duplicate_7d_fail_closed=true`

## 9. Acceptance

- General CI lint/test/migration SUCCESS
- production R2 snapshot restore SUCCESS
- current 6D audit report 재생성 SUCCESS
- strict 7D impact artifact 생성 SUCCESS
- source별 row + 6D-key payment coverage 출력
- 6D vs strict-7D clean comparable 변화 출력
- source-only key 변화 출력
- same-rate/conflicting-rate structural duplicate 출력
- current ambiguity transition 출력
- canonical/authority/identity mutation 없음
- artifact digest 및 workflow head SHA 보존

## 10. Non-goals

- 7D migration
- stable identity schema 변경
- source parser 수정
- 아산/진주 record 자동 정정
- FINLIFE record 삭제
- canonical 금리 수정
- Issue #98 close
- Strategy 공개
