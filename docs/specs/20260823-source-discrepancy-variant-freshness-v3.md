# 저축은행 원천 교차검증 v3 — variant identity + freshness metadata

기준일: 2026-08-23

관련 Issue: #98

## 1. 목적

FSB ↔ FINLIFE ↔ 개별 저축은행 공식 공시를 비교할 때 같은 상품명·기간이라도
**가입채널(`join_channel`)과 이자방식(`interest_method`)이 다른 실제 상품 surface를
하나로 합치지 않는다.**

이번 단계는 데이터 품질 감사 계약만 강화한다. canonical 금리, source precedence,
stable product identity, 수집 schedule은 변경하지 않는다.

## 2. 확인된 문제

기존 source-source automatic key는 다음 4개 필드였다.

- normalized institution
- normalized product
- product type
- term

하지만 `product_variants`에는 이미 `join_channel`과 `interest_method`가 저장되어 있다.
같은 상품/12개월이라도 인터넷·스마트뱅킹, 단리·복리 surface가 실제로 나뉘고
공시 금리도 달라질 수 있으므로, 대표 최고금리 한 행을 먼저 뽑은 뒤 비교하면
다른 variant를 같은 값처럼 취급할 위험이 있다.

2026-08-23 직접 확인한 대백저축은행 애플정기예금 공식 surface는 12개월 기준으로
채널/이자방식별 nominal 약정이율이 4.00%와 4.10%로 나뉜다.

## 3. source-source identity v3

자동 비교 key:

`normalized institution + normalized product + product type + term + join_channel + interest_method`

원칙:

1. source-source 비교에서는 저장된 6개 facet가 모두 같은 경우만 exact match다.
2. `any` / `unknown`도 source-source에서는 실제 저장값으로 취급한다.
3. 한쪽이 `branch`, 다른 쪽이 `internet`이면 같은 상품/기간이어도 자동 합치지 않는다.
4. 같은 base product가 있지만 variant facet가 다른 경우 `unmatched_variant`로 surfaced한다.
5. canonical product/variant row를 수정하거나 merge하지 않는다.

이렇게 해야 `any`를 임의 wildcard로 해석해 서로 다른 두 source variant를 자동 결합하는
새로운 false match를 만들지 않는다.

## 4. official evidence → source variant matching

공식 홈페이지 evidence는 source와 달리 채널/이자방식이 일부 생략될 수 있다.
따라서 source-source보다 제한적인 wildcard 규칙을 허용한다.

- exact facet가 있으면 exact candidate를 우선한다.
- `any` / `unknown`은 한쪽 facet의 정보가 없는 경우에만 wildcard compatibility로 본다.
- compatible candidate가 **유일한 경우에만** 연결한다.
- 같은 점수의 후보가 둘 이상이면 `ambiguous_variant`로 남긴다.
- 명시적으로 충돌하는 facet는 매칭하지 않는다.

이 규칙은 official evidence를 source 행에 붙이는 감사 경로에만 사용한다.
canonical identity나 FSB↔FINLIFE source-source matching에는 사용하지 않는다.

## 5. freshness metadata

각 source provenance에 다음 관찰 메타데이터를 추가한다.

- `source_effective_at`
- `last_seen_at`
- `effective_age_days`
- `last_seen_age_days`
- 각 시각의 known/unknown flag
- report `as_of`

공식 evidence에는 다음을 보존한다.

- `evidence_surface`
- `effective_at`
- `captured_at`
- `effective_age_days`
- `captured_age_days`
- `join_channel`
- `interest_method`

**freshness는 authority score가 아니다.**
최근에 캡처됐다는 이유만으로 해당 surface를 canonical truth로 자동 승격하지 않는다.
`scope.freshness_metadata_policy`와 `scope.official_freshness_metadata_policy`는 모두
observational-only 계약이다.

## 6. 2026-08-23 dated official evidence

운영 audit 입력은
`docs/evidence/source-discrepancy/20260823-official-savings-bank.json`으로 고정한다.

포함 범위:

- 청주저축은행 정기적금 6/12개월 — branch/simple
- 키움예스 e-회전yes 12개월 — 직접 상품공시 + 2026-08-20 시행 금리변경 공지
- 대백 애플정기예금 12개월 — internet/mobile × simple/compound 4개 surface

대백 4개 surface가 서로 다른 금리를 말하는 것은 하나를 오류로 단정하기 위한 것이 아니다.
동일 product family 안에서도 channel/method가 실제 truth question의 일부라는 증거로 사용한다.
공식 evidence group이 서로 다른 금리를 포함하면 기존 v2 계약대로 `official_conflict`가
우선하며 source authority를 선택하지 않는다.

## 7. 운영 Evidence Gate

`source-discrepancy-audit.yml`은 production R2 DB를 runner-local copy로만 복원한다.

실행 경로:

`production R2 restore → local migration → variant-aware FSB/FINLIFE audit → dated official evidence → P0~P3 triage + official contradiction queue → artifact`

금지:

- production DB write
- R2 canonical write
- rate-data write
- source precedence 변경
- canonical silent overwrite
- Strategy 계산/Release Gate 변경

## 8. Acceptance

- source-source exact match가 channel/method를 포함한다.
- 다른 channel/method는 `unmatched_variant`로 surfaced한다.
- official evidence는 unique non-conflicting wildcard만 허용한다.
- source/official freshness metadata가 report에 보존된다.
- freshness metadata가 authority를 자동 선택하지 않는다.
- 2026-08-23 dated official evidence가 production R2 audit에 사용된다.
- General CI: Ruff / full pytest / empty DB migration 통과.
- production R2 read-only discrepancy audit 통과.
- 최신 P0/P1/P2/P3 및 official contradiction queue를 artifact와 Issue #98에 기록한다.

## 9. 비범위

- 자동 official-site crawler
- source precedence 변경
- canonical 금리 보정
- historical DB migration/destructive repair
- stable product identity 변경
- Strategy 화면 경고 UI 변경
