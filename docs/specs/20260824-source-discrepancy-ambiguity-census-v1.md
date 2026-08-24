# Source discrepancy payment-method ambiguity census v1

기준일: 2026-08-24

## 1. 목적

Post-Merge 개선 통합 명세 v3 Track B1을 구현한다.

현행 source-to-source automatic match key는 6D다.

`institution + normalized product + product_type + term + join_channel + interest_method`

한 source가 동일 6D 안에 여러 `payment_method`와 서로 다른 rate pair를 제공하면 최고금리 하나를 대표로 고르지 않고 `ambiguous_variant_dimension`으로 차단한다.

이 census는 그 차단 항목이 일반 mismatch queue 밖에서 얼마나 큰 위험 표면을 만드는지 계량한다. **7D identity 전환 결정은 이 작업의 범위가 아니다.**

## 2. 필수 census

각 ambiguity item에 다음을 기록한다.

- institution / product / product_type / term
- join_channel / interest_method
- blocked side / counterpart side
- candidate count
- candidate payment methods
- candidate rate pairs
- counterpart 존재 여부
- counterpart가 있으면 각 candidate max-rate와 counterpart의 절대 차이
- item별 최대/최소 blocked delta
- triage max-rate gap과 같은 threshold를 사용한 `blocked_risk_band`
- counterpart가 없으면 latest source rows를 이용한 structural absence category

## 3. Risk band

Triage의 금리차 component와 같은 구간만 재사용한다.

- `ge_1.00pp`
- `ge_0.50pp`
- `ge_0.20pp`
- `ge_0.10pp`
- `lt_0.10pp`
- `zero`
- `unknown`

이 band는 investigation visibility 용도이며 authority score가 아니다.

## 4. Counterpart 없음 분석

`counterpart=None`을 단순 source 부재라고 단정하지 않는다.

latest source rows를 조회해 다음 structural category로만 분류한다.

- `counterpart_6d_rows_exist_but_were_not_selected`
- `same_product_term_variant_mismatch`
- `same_product_other_terms_only`
- `same_institution_type_other_product_only`
- `counterpart_product_absent_from_latest_source_rows`
- `counterpart_runtime_rows_unavailable`

각 category는 원천의 최종 business truth가 아니라 다음 forensic 경로를 결정하기 위한 구조 설명이다.

## 5. Queue masking indicator

항상 다음을 함께 노출한다.

- comparable mismatch count
- ambiguity blocked count
- ambiguity blocked with counterpart count
- blocked gap `>=0.20pp` count
- triage P0 count

`P0=0`만 단독으로 데이터 위험이 0이라고 해석하면 안 된다.
Ambiguity item은 fail-closed 때문에 comparable mismatch triage에서 제외되기 때문이다.

## 6. Safety

이 census는 다음을 하지 않는다.

- canonical rate write
- source precedence / authority 선택
- production R2 write
- payment_method를 canonical/stable identity의 strict 7번째 key로 승격
- collector/parser/schema/migration 변경
- ambiguity candidate 중 최고금리를 대표값으로 선택

보고서 scope에는 다음을 machine-readable로 고정한다.

- `ambiguity_census_mutates_canonical=false`
- `ambiguity_census_selects_authority=false`
- `ambiguity_census_promotes_7d_identity=false`

## 7. Acceptance

- unit test: candidate count / F+S combination / blocked delta / risk band / queue masking
- unit test: counterpart 없음 structural category
- General CI lint / full test / empty DB migration SUCCESS
- production R2 read-only snapshot에서 census workflow SUCCESS
- census blocked count == source report `ambiguous_payment_method`
- 모든 distribution 합계 == blocked count
- counterpart 없는 모든 item에 structural category 존재
- production artifact로 최신 product_type/candidate-count/payment-method/counterpart/risk-band 분포를 재확인

## 8. B2 handoff

이 결과를 이용해 다음 별도 decision에서만 7D 전환을 평가한다.

- FSB payment_method coverage
- FINLIFE coverage
- 실제 의미 분리 비율
- 7D 전환 시 source-only 증가량
- exact comparable universe 변화량

B1 완료 자체는 7D 전환 승인으로 간주하지 않는다.
