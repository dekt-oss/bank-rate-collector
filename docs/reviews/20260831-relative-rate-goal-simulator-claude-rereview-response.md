# 상대금리 기반 목표형 금리결정 시뮬레이터 v2 — Claude 재리뷰 수용기록

```yaml
document_type: review_response
status: addressed_docs_only
reviewed_head: 66919e3f9aa6e90738a499de5fbfa5f45cf9f078
date: 2026-08-31
implementation_authorized: false
code_change: none
```

## 1. 결론

Claude 재리뷰의 판정은 `CHANGES REQUIRED`였으나 이전 P0 4건은 모두 `RESOLVED`로 확인됐다.

신규 지적은 v2 설계의 큰 방향 문제가 아니라 repository entry point와 기존 production 대표금리 계약 사이의 미연결이었다.

이번 docs-only 수정에서 다음을 반영했다.

1. `CURRENT.md`를 v2 현행 문서로 전환.
2. v1 plan/work-order 맨 앞에 superseded 정정 절 추가.
3. 기존 Rate × Funding Matrix 대표금리와 신규 pricing peer 대표금리의 관계를 명시.
4. source precedence를 institution rate reduction 반환/acceptance에 포함.
5. pricing peer funding enrichment에 `funding_as_of`와 업권 전체 funding missing guard 추가.
6. availability scope 채움률 실측 전 silent nationwide fallback 금지.
7. pricing peer N을 기본 전제로 두지 않고 eligible institution 전수를 기본 모집단으로 권고.
8. 비용 기준금액 input을 목표수신으로 오해하지 않도록 라벨 계약 강화.
9. 79/66/13 evidence의 artifact/log/published-payload 검증경로 차이를 명시.

코드/DB/migration/workflow/UI는 수정하지 않았다.

---

## 2. Finding별 처리

### P0-5 — 이중 institution 대표금리

**수용.**

최소범위 정책은 `병존 + 명시적 구분`으로 정한다.

기존 production Matrix:

```text
policy = institution_product_representative_max
```

은 이번 R1에서 변경하지 않는다.

신규 pricing peer 대표금리는 별도 policy id/version으로 계산한다.

두 값이 다르면 다음을 payload에 보존한다.

```text
matrix_representative_rate_policy_id
pricing_representative_rate_policy_id
matrix_representative_rate_pct
pricing_representative_rate_pct
representative_rate_gap_bp
```

화면에서 정책 차이 설명 없이 같은 기관의 서로 다른 대표금리를 동일 의미로 표시하는 것을 금지한다.

향후 공통화는 별도 contract-change PR로만 수행한다.

### P0-6 — CURRENT.md v1 진입

**수용 및 문서 수정 완료.**

`CURRENT.md`는 v2 plan/work-order, 1차 review response, identity evidence, rereview prompt를 현행으로 가리킨다.

v1은 `superseded / decision trail only`로 분리했다.

### P1-7 — v1 정정 절 부재

**수용 및 문서 수정 완료.**

v1 plan/work-order의 원문은 삭제하지 않고 맨 앞에 정정 절을 추가했다.

정정 내용:

- Strategy Release Gate OFF 서술은 오류.
- uncalibrated predicted-volume 기반 surface cost 재사용 지시는 R1 factual에 금지.
- v2가 현행 구현 근거.

### P1-8 — reduction source precedence 미표현

**수용.**

v2 작업지시서 최상위 우선규칙에 다음을 추가했다.

```text
source_id
source_precedence_policy_id
precedence_applied: true
```

Acceptance:

- 우선 source가 있을 때 fallback source가 대표금리를 덮지 않는다.
- precedence 적용 여부가 payload/provenance에서 추적 가능하다.

---

## 3. Hidden coupling 추가 반영

### rate/funding as-of

pricing peer row는 `rate_as_of`와 별도로 `funding_as_of`를 가진다.

둘이 다르면 화면에서 동일시점 데이터처럼 보이게 하지 않는다.

### 업권 전체 funding missing

예: CU처럼 pricing rate는 있으나 funding이 업권 전체 미확인인 경우:

- pricing peer row 유지
- funding `null / 자료없음`
- aggregate funding scalar는 `null`
- 합산금액 카드를 렌더링하지 않음

### availability scope

`availability_scope`가 존재한다는 것과 실제 채움률이 충분하다는 것은 다르다.

R0-A2 전에 업권별로 다음을 실측한다.

```text
population count
availability_scope known count
unknown count
known ratio
source/provenance
```

결측을 조용히 nationwide로 해석하지 않는다.

### pricing peer N

Pricing peer는 funding peer와 다르다.

기본 모집단은:

```text
same sector
+ matched product type/term
+ compatible availability/join scope
+ valid representative rate
```

을 만족하는 institution 전수다.

N cap은 evidence와 실제 UX/성능상 필요가 확인된 경우에만 별도 정책으로 도입한다.

---

## 4. 79 / 66 / 13 evidence 처리

재리뷰가 지적한 검증경로 차이는 타당하다.

원 evidence 작성 세션에서는 Actions artifact `publish/funding-report.json`을 직접 검사해 다음을 확인했다.

```text
institution_count 79
mapped_count 66
unmapped_count 13
```

Claude 재리뷰는 artifact를 열지 못했기 때문에 run log에서 `79`와 reconciliation을, published Strategy payload에서 계산가능 population `66`을 독립 확인했다.

따라서 evidence 문서를 수정해:

- artifact 확인값
- log 독립 확인값
- published payload 독립 확인값
- 각 정의가 상호 대체되지 않는다는 점

을 분리했다.

후속 canonical funding run에서는 mapping coverage가 로그/readback에서도 재검증 가능하도록 만드는 것을 acceptance로 둔다.

---

## 5. 아직 구현 전 확인할 것

다음은 docs-only 수정으로 해결된 것이 아니다.

1. `availability_scope` 업권별 실제 채움률
2. 미연결 13개 source identity의 fncoCd/CRNO exact correspondence
3. NH historical 2025-12 rate evidence 존재 여부
4. R1 production UI 실제 layout/runtime
5. pricing peer 신규 정책의 실제 모집단 분포

이는 구현 R0 evidence stage에서 확인한다.

---

## 6. 현재 완료판정

### 완료

- 1차 P0 4건 문서계약 수정
- 2차 P0/P1 repository entry 연결 수정
- v1 superseded correction
- Matrix/pricing 대표금리 병존 정책 결정
- evidence 검증경로 명시

### 미검증

- availability_scope runtime coverage
- identity 13개 exact mapping
- historical rate evidence
- browser rendering

### 남은 작업

Claude 최종 문서 재검증 → 사용자 정책 승인 → 새 구현 branch에서 R0 evidence/contract부터 시작.
