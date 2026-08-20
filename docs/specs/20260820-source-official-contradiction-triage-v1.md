# 공식 공시 모순 자동분류 v1

기준일: 2026-08-20  
관련 Issue: #98  
선행 PR: #153 → #154

## 1. 목적

#154의 mismatch queue는 `FSB ↔ FINLIFE`가 서로 다른 행만 조사한다. 그러나 두 중앙
원천이 서로 같은 금리를 내더라도 개별 저축은행 공식 공시가 그 값을 부정할 수 있다.

현재 재현 사례:

- 대백저축은행 애플정기예금 12개월
- FSB 4.10%
- FINLIFE 4.10%
- 개별 금융사 공식 상품공시 3.80%
- official signal: `neither_supported`

이 경우 source-source 비교만 보면 `agree`라서 #154의 27건 mismatch queue에는 들어가지
않는다. 따라서 official evidence를 별도 축으로 보고 **silent consensus contradiction**을
자동 surface 한다.

## 2. 불변 조건

이 queue는 조사 우선순위일 뿐 source authority가 아니다.

- canonical 금리 수정 없음
- FSB/FINLIFE source precedence 변경 없음
- stable product identity 변경 없음
- 수동 `comparison_product` alias는 official evidence 감사 범위 밖으로 전파하지 않음
- production DB/R2 write 없음
- `rate-data` write 없음
- Vercel deploy 없음
- Strategy 계산/Release Gate 변경 없음
- official evidence 값으로 canonical을 자동 overwrite하지 않음

## 3. 대상 signal

`official_evidence_groups` 중 다음만 별도 queue에 넣는다.

### `neither_supported`

consistent 공식 evidence가 FSB와 FINLIFE를 모두 지지하지 않는다.

두 중앙 원천의 최고금리가 서로 같으면 특히 위험하다. 중앙 두 원천만 교차검증하면
정상처럼 보이기 때문이다.

분류:

- source-source max rate agree → `source_consensus_official_contradiction`
- source-source도 mismatch → `official_rejects_both_sources`

### `official_conflict`

같은 금융사의 공식 evidence surface끼리 금리가 충돌한다.

분류:

- `official_internal_conflict`

이 경우 공식 홈페이지를 무조건 truth source로 승격하지 않고 authority 판정을 차단한다.

### `mixed_support`

공식 evidence가 일부 필드/record에서만 일치한다.

분류:

- `official_partial_contradiction`

`primary_supported`, `secondary_supported`는 #154 mismatch triage에서 이미 직접 evidence
P0로 처리하므로 이 별도 contradiction queue에는 중복 추가하지 않는다.

## 4. Priority

| 분류 | Priority | Score |
|---|---|---:|
| `source_consensus_official_contradiction` | P0 | 100 |
| `official_internal_conflict` | P0 | 95 |
| `official_rejects_both_sources` | P0 | 90 |
| `official_partial_contradiction` | P1 | 70 |

점수는 deterministic 조사 순서이며 정답 확률이나 source 신뢰도 점수가 아니다.

## 5. 출력 계약

full discrepancy report에 `official_contradictions`를 추가한다.

별도 artifact:

`work/source-discrepancy-official-contradictions.json`

각 item은 다음을 보존한다.

- rank / P0~P3 / score
- classification
- evidence group
- institution
- official product / comparison product
- product type / term
- official status / reconciliation signal
- source support
- official base/max rates
- source-source pair status
- FSB/FINLIFE max/base rate comparison
- source effective dates
- raw artifact/source locator provenance
- source consensus max rate
- consensus vs official absolute gap
- 원본 official evidence records
- suggested action

## 6. 대백 사례의 기대 결과

현재 dated official evidence와 production source pair 기준:

- institution: 대백저축은행
- comparison product: 애플정기예금
- term: 12개월
- source pair max rate: 4.10% / 4.10%
- official max rate: 3.80%
- gap: 0.30%p
- signal: `neither_supported`
- classification: `source_consensus_official_contradiction`
- priority: P0
- score: 100

이 항목이 queue에 없으면 regression으로 본다.

## 7. 공식 내부 충돌

키움YES e-회전yes 12개월처럼 공식 상품공시와 시행 공지가 서로 다른 경우:

- classification: `official_internal_conflict`
- P0 / 95
- primary/secondary source authority는 둘 다 선택하지 않는다.

이 항목은 #154 mismatch queue에도 나타날 수 있다. 두 queue의 의미가 다르므로 중복은
허용한다.

- mismatch queue: source-source discrepancy 관점
- official contradiction queue: official evidence 관점

## 8. Production Evidence Gate

GitHub Actions `Source discrepancy audit`는 production R2 snapshot을 read-only로 복원한 뒤:

1. migration 적용
2. 기존 3중 discrepancy report 생성
3. mismatch priority queue 생성
4. official contradiction queue 생성
5. canonical/source authority 불변 assertion
6. 대백 silent consensus contradiction 존재 assertion
7. artifact 업로드

production DB/R2에 쓰기는 하지 않는다.

## 9. 후속 범위

이 PR 이후 #98의 다음 후보는 다음과 같다.

1. 안전한 product alias registry
2. 개별 저축은행 official evidence 수집 adapter/crawler
3. source freshness/authority/reconciliation ADR
4. Strategy의 원천 불일치/공식 모순 경고 UI

공식 evidence 자동 수집이 도입되기 전까지 contradiction queue의 coverage는 dated evidence
파일에 실제로 등록된 금융사/상품 범위에 한정된다.

## 10. 검증 추적성

최종 PR head에는 반드시 다음 두 검증이 같은 head 계열에서 남아야 한다.

- 일반 CI: Ruff + full pytest + empty DB Alembic/model parity
- Source discrepancy audit: production R2 read-only restore + official contradiction assertions

PR 생성이나 merge 가능 상태만으로 기능 동작을 검증한 것으로 보지 않는다. stacked parent가
merge된 뒤 base를 `main`으로 바꾸는 경우에도 같은 검증을 다시 수행한다.
