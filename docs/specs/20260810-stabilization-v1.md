# 금리수집기 안정화 개선 작업명세서 v1.0

- status: `planned`
- date: `2026-08-10`
- base: `main @ 22e5c7f8`
- purpose: 기존 구조를 유지하면서 실제 확인된 데이터 오류·수집 실패 가능성·운영상의 신뢰성 문제를 최소 범위로 제거한다.
- implementation policy: 신규 기능·대규모 리팩터링·DB 전환 없이 안정화 작업만 수행한다.

---

## 0. 작업 성격

이번 작업은 신규 기능 개발이나 아키텍처 개편이 아니다.

**현재 금리수집기의 구조를 그대로 유지하면서, 실제 확인된 데이터 오류·수집 실패 가능성·운영상의 신뢰성 문제를 최소 범위로 제거한다.**

### 유지할 기본 구조

```text
Source
→ Collector
→ Raw 보존
→ Parser
→ Normalize
→ SQLite Canonical DB
→ Validation Gate
→ Static Build
→ Vercel Publish
```

이번 작업에서 유지한다.

- 기존 Collector 구조
- SQLite canonical DB
- RawArtifact / provenance 구조
- R2 저장 구조
- GitHub Actions 수집 구조
- Vercel static publish 구조
- Observation change history
- 실패 run의 observation 미반영
- 원천에 없는 값을 임의 생성하지 않는 원칙
- 우대조건 taxonomy
- CI와 실제 외부 수집의 분리

이번 작업에서 하지 않는다.

- DB 전면 교체
- Supabase/PostgreSQL 이전
- 수집기 전면 재작성
- 프론트엔드 프레임워크 교체
- 신규 금융기관 추가
- 대규모 신규 기능 개발

---

## 1. Current State

현재 repository/runtime 조사에서 다음이 확인됐다.

### 1.1 실제 운영 장애 — partial collection gate scope

2026-08-10 KFCC-only 수집은 수집 자체는 성공했다.

```text
KFCC 수집 성공
93,359건 valid
stored data validation 통과
site build 성공
export 성공

하지만 final gate에서
Finlife raw 0개 / historical observation 11,977건
조건으로 실패

→ publish 중단
→ KFCC 최신 데이터 미반영
```

원인은 partial run의 현재 workspace raw와 전체 historical DB provenance 검증이 같은 gate에 결합돼 있기 때문이다.

### 1.2 실제 데이터 오류 — 행정구역 parsing

생성 데이터에서 다음 형태가 확인됐다.

```text
sido = 대구
sigungu = 동덕로
```

`동덕로`는 행정구역이 아니라 도로명이다. 현재 주소 token 기반 정규화가 두 번째 token의 실제 행정구역 유효성을 충분히 검증하지 않는다.

### 1.3 의미 오류 가능성 — 이자방식

일부 NH parser는 사실상 다음 규칙을 사용한다.

```text
"복리" 포함 → compound
그 외 → simple
```

원천이 단리를 명시하지 않았는데도 `simple`로 확정될 가능성이 있으므로 실제 NH 원본 증거를 먼저 확인해야 한다.

---

## 2. Target State

```text
Source
  ↓
Collector
  ↓
Raw
  ↓
Normalize
  ↓
Canonical DB
  ↓
┌──────────────────────────────┐
│ Current Run Validation       │
│ Historical Integrity         │
│ Data Quality Validation      │
└──────────────────────────────┘
  ↓
Static Publish
  ↓
Vercel
```

그리고 사용자/운영자 화면에서는 각 source의 실제 최신 상태를 구분할 수 있어야 한다.

---

## 3. 전체 범위 재분류

| ID | 항목 | 위험도 | 이번 안정화 |
|---|---|---:|---|
| P0-1 | Partial Collection Gate 수정 | High | **필수 구현** |
| P0-2 | 시군구 정규화 강화 | High | **필수 구현** |
| P0-3 | 단리/복리 unknown 처리 | High | **검증 후 구현** |
| P1-1 | Source freshness 표시 | Medium | **필수 구현** |
| P1-2 | Static Sharding | Medium~High | **이번 안정화 제외** |
| P1-3 | NH Warning 구조화 | Medium | **필수 구현** |
| P1-4 | 관리자 인증 개선 | High / Security | **별도 후속 PR** |
| P1-5 | `권역` → `업권` | Low | **필수 구현** |
| P2-1 | 수집 병렬화 | High / Concurrency | **설계만** |
| P2-2 | UI 모듈화 | Medium | **필요한 부분만** |
| P2-3 | 재배포 정책 | 운영/정책 | **체크리스트만** |
| P2-4 | 금리변동 이력 UI | 신규 기능 | **Backlog** |

---

## 4. P0-1 — Partial Collection Gate 수정

### Current

부분 수집 job에서도 현재 workspace에 전체 원천 raw가 존재하는 것을 전제로 검증한다.

### Target

검증을 역할별로 분리한다.

```text
Current Run Gate
→ 이번 run에서 실제 수집한 source만 검증

Historical Integrity Gate
→ 전체 canonical DB provenance 검증
→ 현재 workspace raw 존재 여부에 의존하지 않음
```

### 보존 불변식

다음 방식으로 고치지 않는다.

```text
금지: 검증 삭제
금지: 실패를 warning으로 낮춤
금지: provenance 검증 완화
```

올바른 수정은 **검증 강도는 유지하고 검증 범위만 올바르게 분리하는 것**이다.

### Acceptance Criteria

- KFCC-only 정상 run이 Finlife local raw 부재 때문에 실패하지 않는다.
- 전체 수집 run의 검증 강도는 감소하지 않는다.
- 이번 run에서 실제 수집한 source의 raw/observation mismatch는 publish를 차단한다.
- historical DB integrity 문제도 publish를 차단한다.
- 기존 fail-closed 동작을 유지한다.

---

## 5. P0-2 — 행정구역 정규화 강화

### Current

주소 token에서 시도/시군구를 추출하면서 도로명이 sigungu로 들어갈 수 있다.

### Target

```text
raw address
   ↓
sido normalize
   ↓
sigungu candidate
   ↓
행정구역 master validation
   ↓
valid   → sigungu 저장
invalid → NULL
```

### 원칙

- raw address는 그대로 보존한다.
- 정규화할 수 없는 값은 추정하지 않는다.
- suffix 검사만으로 행정구역을 확정하지 않는다.
- 가능하면 `sido → allowed sigungu` canonical master를 사용한다.

### Acceptance Criteria

- `동덕로` 같은 도로명이 sigungu에 들어가지 않는다.
- 부산 16개 구·군 filtering은 기존과 동일하게 동작한다.
- 기존 raw 주소는 손실되지 않는다.
- 판정 불가능한 주소는 NULL로 남긴다.
- parser/normalizer fixture test를 추가한다.

---

## 6. P0-3 — 단리·복리 의미 검증

이 항목은 실제 원천 확인 없이 즉시 수정하지 않는다.

### Evidence Gate

NH 실제 원본에서 이자계산 관련 문구를 수집하고 distinct pattern을 확인한다.

예:

```text
단리 명시
복리 명시
월복리
만기일시지급식
별도 표시 없음
기타 표현
```

### 목표 contract

```text
명확한 복리 근거 → compound
명확한 단리 근거 → simple
근거 부족 → unknown
```

금지:

```text
복리가 아니므로 단리
단리가 아니므로 복리
```

### Acceptance Criteria

- 판정 근거를 fixture/test로 고정한다.
- 명확하지 않은 경우 `unknown`이다.
- 기존에 명확히 식별되는 compound/simple 데이터는 회귀하지 않는다.

---

## 7. P1-1 — Source Freshness

사이트 생성시간과 각 source의 실제 최신 수집시간을 분리한다.

### Target

예:

```text
데이터 최신 상태

저축은행      08/10 정상
신협          08/10 정상
지역농축협    08/10 정상
새마을금고    08/07 이전 데이터
은행          08/10 정상
```

내부적으로 최소 다음 개념을 구분한다.

```text
site_generated_at
last_successful_collection_at
source_data_at / effective_at
```

source가 제공하지 않는 effective date는 만들어내지 않는다.

### Acceptance Criteria

- 전체 사이트 생성시간만 보고 모든 source가 최신인 것처럼 보이지 않는다.
- source별 마지막 성공 run을 확인할 수 있다.
- failed run 후 기존 성공 데이터를 쓰는 상태를 표현할 수 있다.

---

## 8. P1-3 — Warning Taxonomy

단순 총량만으로는 정상 warning과 신규 이상징후를 구별하기 어렵다.

현재 warning 발생 경로를 조사한 뒤 실제 category를 확정한다.

후보:

```text
PREFERENCE_RATE_ROW
TERM_PARSE_AMBIGUOUS
UNKNOWN_INTEREST_METHOD
UNKNOWN_PRODUCT_TYPE
ADDRESS_PARSE_FAILED
UNUSUAL_RATE
```

### Acceptance Criteria

summary 또는 운영 output에서 최소 다음을 확인할 수 있다.

```text
total warning
warning reason
warning count
```

기존에 정상적으로 예상되는 warning과 새로운 warning 증가를 구별할 수 있어야 한다.

---

## 9. P1-5 — `권역` → `업권`

금융기관 종류를 고르는 UI label의 `권역`을 `업권`으로 변경한다.

대상 예:

- 저축은행
- 새마을금고
- 신협
- 지역농축협
- 은행

### Acceptance Criteria

- 표시 문구만 변경한다.
- filter key/data contract는 변경하지 않는다.
- 기존 지역 필터 의미와 충돌하지 않는다.

---

## 10. 이번 안정화에서 제외

### 10.1 Static Sharding

성능 개선 가치는 있으나 publisher artifact format, frontend loader, caching, filter behavior까지 영향을 주므로 이번 안정화 PR에 섞지 않는다.

후속 작업 전 다음을 측정한다.

```text
payload download
decompression
JSON parse time
initial render
filter latency
browser memory
mobile behavior
```

### 10.2 관리자 인증 구조 변경

Security high-risk 항목이다. Vercel front-door validation으로 옮길 경우 secret ownership/hash management/deployment env/rate-limit/failure behavior까지 별도 Evidence Gate를 수행한다.

### 10.3 수집 병렬화

scheduler/concurrency high-risk 항목이므로 이번에는 구현하지 않는다.

후속 설계 목표는 다음과 같다.

```text
parallel fetch
→ independent raw artifact
→ retry / partial failure handling
→ deterministic merge
→ single DB writer
→ publish
```

### 10.4 UI 모듈화

독립적인 대규모 리팩터링은 하지 않는다. 이번 변경에 필요한 작은 helper/function 추출만 허용한다.

### 10.5 원천 재배포 정책

코드 변경과 분리한다. source별 수집 허용/내부 사용/외부 공개/재가공/출처 의무/자동수집 제한을 별도 체크한다.

### 10.6 금리변동 History UI

Observation history를 활용할 수 있으나 신규 제품 기능이므로 backlog로 둔다.

---

## 11. 최종 Task Boundary

### 이번에 한다

1. Partial Collection Gate 수정
2. 행정구역 validation
3. 단리/복리 원천 검증 및 필요 시 strict classification
4. Warning taxonomy
5. source별 freshness 표시
6. `권역` → `업권`

### 이번에 하지 않는다

- Static Sharding
- 관리자 인증 구조 변경
- 병렬수집
- 금리변동 이력
- 대규모 UI 리팩터링
- DB 이전
- collector 전면 재작성
- 새 금융기관 추가

### 반드시 보존한다

- Raw source
- Provenance
- Observation history
- 기존 DB/ID
- 기존 source adapter
- 기존 publish 방식
- fail-closed validation
- 기존 공개 filter contract

---

## 12. PR 분리 계획

### PR A — Collection Gate Correctness

```text
P0-1 Partial collection validation scope
```

가장 먼저 처리한다. 실제 최신 KFCC publish를 막은 운영 장애다.

### PR B — Normalization Correctness

```text
P0-2 Region
P0-3 Interest Method
```

둘 다 `원천값 → normalized value` 정확성 문제다. P0-3은 Actual Evidence에서 수정 필요성이 확인된 경우만 포함한다.

### PR C — Data Observability

```text
P1-1 Source freshness
P1-3 Warning taxonomy
P1-5 권역 → 업권
```

저위험 UI 문구 변경은 이 PR에 함께 넣어도 된다.

---

## 13. Verification Plan

### PR A

검증 사례:

```text
full collection
KFCC-only
other partial collection
failed collector
missing current-run raw
historical observation provenance
```

핵심 regression 질문:

> partial collection을 고치다가 validation 자체를 약화시키지 않았는가?

### PR B

검증 사례:

```text
정상 행정구역
도로명 주소
시군구 없는 주소
부산 구·군 filtering
단리
복리
미표기
```

금리/분류 의미는 test로 고정한다.

### PR C

검증 사례:

```text
source successful
source failed
source stale
mixed freshness
warning category aggregation
기존 filter behavior
```

### 공통 검증

repository의 실제 CI 정의를 기준으로 최소 다음을 수행한다.

```text
ruff check .
pytest
alembic migration consistency / schema check (CI가 수행하는 범위)
GitHub Actions CI
```

외부 source 실제 응답, scheduled collection, Vercel runtime은 CI와 별개로 확인하며 확인하지 못한 항목은 미검증으로 표시한다.

---

## 14. Adversarial Self-Review

각 PR 완료 전 다음을 반대로 검토한다.

### Gate

> 부분 수집이 성공하지만 실제 raw 오류도 통과하는 것은 아닌가?

### 주소

> 도로명 오류를 막다가 정상 행정구역도 제거하는 것은 아닌가?

### 이자방식

> unknown을 늘려 실제 명시된 단리 데이터까지 잃는 것은 아닌가?

### Freshness

> site build 시간이 source collection 시간처럼 표시되지 않는가?

### Warning

> category 변경으로 실제 warning을 숨기고 있지는 않은가?

P0/P1 문제가 발견되면 완료로 판단하지 않는다.

---

## 15. 구현 순서

```text
1. P0-1 Gate
      ↓
2. P0-2 Region
      ↓
3. P0-3 Interest Method Evidence
      ↓
4. Warning Taxonomy
      ↓
5. Source Freshness
      ↓
6. 업권 문구
      ↓
7. 전체 회귀검증
```

---

## 16. 후속 Backlog

### Performance

- Static Sharding
- Web Worker
- virtualization

### Collection scale

- parallel collector
- single deterministic merge

### Security

- Vercel front-door auth

### Product

- 금리변동 History

### Governance

- source별 collection / redistribution policy

---

## 17. 완료 정의

이번 안정화 작업은 PR 생성만으로 완료가 아니다.

```text
[ ] 실제 KFCC partial-run 문제를 재현하고 수정
[ ] 수정 후 partial collection 정상 publish 확인
[ ] full collection validation 강도 유지
[ ] 잘못된 sigungu 저장 방지
[ ] 이자방식 규칙이 source evidence와 일치
[ ] warning 원인 구분 가능
[ ] source별 최신 상태 확인 가능
[ ] 관련 테스트 추가
[ ] lint/test 통과
[ ] CI success
[ ] 가능한 runtime 검증 수행
[ ] adversarial self-review 통과
```

검증하지 못한 사항은 완료 보고서에서 별도로 표시한다.

---

## 18. 최종 판단

이 프로젝트는 현재 아키텍처를 다시 만드는 단계가 아니다.

이번 안정화에서는 수집기 기능 추가보다 **현재 데이터 파이프라인의 정확성과 운영 신뢰도를 먼저 굳힌다.**

```text
이번 안정화
 ├ Partial Gate
 ├ Region normalization
 ├ Interest-method evidence/strictness
 ├ Warning taxonomy
 ├ Source freshness
 └ 권역 → 업권

후속
 ├ Static Sharding
 ├ Admin Auth
 ├ Parallel Collection
 ├ UI Refactor
 ├ Redistribution Policy
 └ Rate History
```

기존의 좋은 구조를 보존하면서 실제로 확인된 문제를 먼저 닫는 것이 이 문서의 기준이다.
