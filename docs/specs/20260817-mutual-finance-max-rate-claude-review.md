# 상호금융 최고금리 공통화·전략 확장 — Claude Review Work Order

```yaml
document_type: review_work_order
status: pending_claude_review
created_at: 2026-08-17
target_repository: dekt-oss/bank-rate-collector
base_commit: 89312caabe8caae7326a03028ef9d4c551ca1496
issue: 108
depends_on:
  - PR_113_merged
  - PR_114_merged
  - PR_115_merged
risk:
  - financial_rate_semantics
  - external_source_collection
  - stable_identity
  - cross_sector_comparison
  - geography_scope
implementation_blocked: true
release_gate_change: false
```

> 이 문서는 **구현 명령이 아니라 Claude 검토용 작업명세**다.
> Claude가 현재 코드·원천·데이터 계약을 다시 검증하고 `APPROVE` 또는 `CHANGE REQUESTED`를 남기기 전에는 아래 Stage F/G/H 구현을 시작하지 않는다.
> Claude 리뷰 후에도 실제 구현 시작은 발주자의 명시적 승인 이후다.

---

## 1. 이번 문서의 목적

Issue #108의 상호금융 전략 확장을 다음 세 단계로 분리한다.

1. **Stage F — 공식 원천에서 최고금리 의미를 증명**
   - 새마을금고(`kfcc`)
   - 농·축협(`nh_local`)
   - 신협(`cu`)은 현재 동작하는 참고 계약으로 사용
2. **Stage G — 증명된 업권만 collector/canonical `max_rate` 계약을 확장**
3. **Stage H — 세 업권의 `max_rate`가 동일 금융 의미를 만족한 뒤 전략 대시보드의 상호금융/혼합 mode를 구현**

핵심 사용자 결정은 다음과 같다.

> **전략 비교의 최종 기본 금리축은 가능한 한 업권 전체에서 `최고금리`로 통일한다.**
>
> 다만 현재 값이 없다는 이유로 `base_rate`를 `max_rate`처럼 대체하지 않는다. 공식 원천에서 동일 상품·기간·적용범위의 실제 최고금리를 증명하고 정규화한 후 사용한다.

---

## 2. 현재 main 기준점

현재 main 기준 SHA:

```text
89312caabe8caae7326a03028ef9d4c551ca1496
```

완료 상태:

- PR #113 — Issue #108 요구 1·2 UI 후속: merged
- PR #114 — 상호금융 Strategy Evidence Gate: merged
- PR #115 — strategy stable `product_id` 직접 전달: merged
- Production 전략 Release Gate: **여전히 OFF 유지**

### 2.1 PR #114에서 확인된 Production 금리 coverage

대상은 `term_deposit`, 6/12/24/36개월이다.

| 업권 | 대상 행 | `base_rate` | `max_rate` |
|---|---:|---:|---:|
| 새마을금고 `kfcc` | 24,464 | 100% | **0%** |
| 신협 `cu` | 15,178 | 100% | **100%** |
| 농·축협 `nh_local` | 73,020 | 100% | **0%** |

따라서 현재 canonical 데이터에서 아래 fallback은 계속 금지한다.

```python
max_rate if max_rate is not None else base_rate
```

이 식은 신협에는 최고 우대금리, 새마을금고/농·축협에는 기본금리를 넣어 하나의 “최고금리” 랭킹에서 서로 다른 금융 의미를 섞는다.

### 2.2 PR #115 이후 stable identity 상태

PR #114에서 발생했던 strategy display-key 미매칭:

- `kfcc`: 2,175행
- `nh_local`: 1,335행

은 persisted identity 누락이 아니라 표시명 기반 재조인의 ambiguity였다.

PR #115에서 Strategy build가 DB의 실제 `products.id`를 internal `product_id`로 직접 운반하도록 수정했다.

Production read-only 검증 결과:

- KFCC 대상 24,464행: `product_id NULL = 0`
- NH local 대상 73,020행: `product_id NULL = 0`
- public canonical table: internal ID OFF/ON 직렬화 동일

따라서 **identity는 Stage F/H의 blocker에서 제거**한다. 이름 fallback이나 entity merge는 다시 추가하지 않는다.

---

## 3. 목표 금리 계약

### 3.1 `base_rate`

같은 상품 variant·기간·적용범위에서 공식 원천이 공시하는 기본 금리.

### 3.2 `max_rate`

전략 비교에서 사용할 `max_rate`는 다음 조건을 모두 만족해야 한다.

1. 공식 또는 프로젝트가 승인한 1차 원천에서 확인 가능
2. 동일 상품 또는 stable product identity와 연결 가능
3. 동일 가입기간과 연결 가능
4. 동일 기관/점포/rate scope와 연결 가능
5. 우대조건이 있다면 어떤 우대가 해당 최고금리를 구성하는지 근거가 남음
6. 수집 시점/공시 시점이 추적 가능
7. raw artifact 또는 source evidence로 재현 가능

### 3.3 허용되는 `max_rate == base_rate`

`max_rate`가 `base_rate`와 같은 숫자인 경우 자체는 문제가 아니다.

다만 아래 중 하나가 공식 원천으로 증명되어야 한다.

- 원천이 해당 필드를 최종/최고 적용금리로 정의하고 그 값이 기본금리와 동일함
- 해당 상품/기간에는 추가 우대가 없고 공시된 기본금리가 실제 최대 적용금리임을 원천 계약이 명확히 보장함

즉 **UI/집계 단계의 fallback은 금지**하지만, source parser/normalizer가 공식 의미를 증명한 뒤 `max_rate=base_rate`로 정규화하는 것은 허용할 수 있다.

### 3.4 금지되는 추론

아래는 공식 linkage 없이 하지 않는다.

```text
기본금리 3.0%
+ 다른 행/문구의 우대금리 0.4%
= 최고금리 3.4%
```

우대가 정확히 같은 상품·기간·점포·가입조건에 적용된다는 근거가 없으면 `max_rate`는 NULL로 둔다.

---

# Stage F — 공식 Source Evidence Gate

## 4. 목적

새마을금고와 농·축협에서 **실제 최고금리를 수집할 수 있는 공식 데이터 경로가 존재하는지** 먼저 증명한다.

이 단계는 원칙적으로 **read-only 조사**다. collector/DB/화면을 변경하지 않는다.

## 5. 조사 대상

### 5.1 새마을금고 `kfcc`

현재 확인해야 할 질문:

1. 현재 collector가 읽는 중앙 금리조회가 기본이율만 제공하는가?
2. 같은 공식 도메인/응답/API/상품상세에 우대금리 또는 최고금리가 별도로 존재하는가?
3. 그 값이 금고·상품·기간 단위로 현재 canonical variant와 안정적으로 연결 가능한가?
4. 우대조건 원문도 함께 추적할 수 있는가?
5. 지점/금고별 차이가 있을 때 `rate_scope`는 무엇이어야 하는가?

### 5.2 농·축협 `nh_local`

현재 확인해야 할 질문:

1. 현재 점포별 기본금리 수집 경로와 최고/우대금리 원천이 동일한가?
2. 별도의 우대금리 행/상품이 실제로 “같은 상품의 우대”인지, 독립 상품인지 구분 가능한가?
3. 조합/점포/상품/기간을 연결하는 안정적인 source key가 있는가?
4. 최고금리를 점포 단위로 적용해야 하는지 institution 단위인지 증명 가능한가?
5. 우대조건 원문과 최고금리의 관계를 raw artifact에서 재현할 수 있는가?

### 5.3 신협 `cu` — Reference Contract

신협은 현재 `max_rate` coverage 100%이므로 다음을 reference로 확인한다.

- adapter의 `provides_max_rate=True` 의미
- source field → normalized `max_rate` 경로
- base/max/우대조건 연결 방식
- rate scope / geo basis
- raw artifact traceability

**신협 구현을 복제하라는 의미는 아니다.** 세 업권의 원천 구조가 실제로 같은지 비교 기준으로만 사용한다.

## 6. Stage F 산출물

업권별로 최소 아래 evidence matrix를 작성한다.

| 필드 | 설명 |
|---|---|
| source | 공식 원천/endpoint/page |
| source field | 실제 원천 필드 또는 구조 |
| product key | 상품 연결 key |
| institution/outlet key | 기관/점포 연결 key |
| term key | 기간 연결 key |
| base rate | 기본금리 의미 |
| preferential component | 우대 구성값 존재 여부 |
| max rate | 최고금리 직접 제공/계산 가능 여부 |
| calculation rule | 원천이 보장하는 경우에만 계산식 |
| preference text | 조건 원문 추적 가능 여부 |
| rate scope | institution / outlet / 기타 |
| effective date | 공시/적용 시점 |
| raw trace | raw artifact로 재현 가능한지 |
| coverage | Production 대상 대비 확보율 |
| ambiguity | 같은 key가 여러 상품/점포를 가리키는지 |

### 6.1 필수 샘플 검증

각 업권에서 최소 다음 유형을 직접 대조한다.

- 고금리 상품
- 일반 정기예금
- 우대조건 있음
- 우대조건 없음 또는 최고=기본 가능 사례
- 6/12/24/36개월 중 존재하는 기간
- 서로 다른 기관/점포

단순 HTML 문자열 존재 확인만으로 GO 판정하지 않는다.

## 7. Stage F Go/No-Go

### GO

업권의 `max_rate`를 stable product/variant에 공식적으로 연결할 수 있고 raw evidence가 재현 가능하다.

### CONDITIONAL GO

일부 상품군만 정확한 최고금리 linkage가 가능하다.

이 경우:

- 지원 상품군을 명시적으로 제한하거나
- row-level `max_rate` coverage를 표출하는 설계를 먼저 확정한다.

### NO-GO

우대/최고금리는 보이지만 같은 상품·기간·기관/점포와 안전하게 연결할 수 없다.

NO-GO 업권에는 `max_rate`를 추정해서 채우지 않는다.

---

# Stage G — Collector `max_rate` 계약 확장

## 8. Entry Gate

Stage G는 **Stage F에서 해당 업권이 GO 또는 명시적 CONDITIONAL GO**를 받은 경우에만 시작한다.

Claude review에서 Stage F 자체가 불충분하다고 판단하면 Stage G를 시작하지 않는다.

## 9. 구현 원칙

### 9.1 기존 schema 우선

현재 canonical에 `max_rate` 필드가 이미 존재하므로 가능한 경우 기존 모델을 재사용한다.

DB schema/migration 변경이 필요하다는 결론이 나오면 자동으로 범위를 넓히지 않고 별도 High-risk migration 작업으로 분리한다.

### 9.2 Source semantics를 adapter가 소유

- adapter/parser가 source field 의미를 해석
- normalized record에 evidence-backed `max_rate` 저장
- 화면이나 strategy service에서 계산하지 않음

### 9.3 `provides_max_rate`

해당 adapter의 capability 플래그는 실제 source contract가 증명된 뒤에만 변경한다.

단순히 일부 행에 숫자를 넣었다고 `provides_max_rate=True`로 올리지 않는다.

### 9.4 우대조건과의 연결

가능하면 함께 보존한다.

```text
base_rate
max_rate
raw_preference_text
normalized preference tags/status
source/effective date
```

`raw_preference_text`가 없더라도 최고금리가 공식 필드로 직접 제공되면 사용할 수 있다. 반대로 우대 문구만 있고 최종 최고금리를 안전하게 계산할 수 없으면 `max_rate`를 만들지 않는다.

### 9.5 Historical data

기존 historical observation을 임의 rewrite하지 않는다.

기본안:

- 새 collector contract 적용 이후 신규 정상 run부터 `max_rate` 확보
- 과거 raw artifact로 결정론적 재생성이 가능하고 실제 필요성이 있을 때만 별도 backfill 계획 수립

## 10. Stage G Verification Gate

업권별로 최소 확인한다.

1. parser/adapter fixture test
2. 정상/결측/우대없음/다중기간 테스트
3. 잘못된 product/term cross-join 방지 테스트
4. raw artifact traceability
5. collection idempotency
6. full `pytest`
7. `ruff`
8. migration model consistency
9. Production read-only 또는 shadow collection evidence
10. 공식 원천 spot-check와 canonical 값 대조

### 10.1 필수 invariant

```text
base_rate <= max_rate
```

는 일반적인 sanity check로 사용하되, 이 수식만으로 source correctness를 판정하지 않는다.

### 10.2 Coverage 보고

최종적으로 업권·기간별로 아래를 보고한다.

```text
rows
base_rate_non_null
max_rate_non_null
max_rate_coverage
source_effective_at freshness
warnings/errors
```

coverage가 100%가 아니면 그 이유를 상품군/원천 구조별로 분류한다.

---

# Stage H — 전략 대시보드 상호금융 확장

## 11. Entry Gate

Stage H는 다음이 모두 충족돼야 시작한다.

1. PR #115 stable identity direct transport가 main에 존재 — **완료**
2. `cu`, `kfcc`, `nh_local`의 최고금리 semantic 판정 완료
3. 통합 대상 업권에서 비교 가능한 `max_rate` coverage가 충분하다는 Evidence Gate 통과
4. sector별 geography/rate scope 차이 처리 계약 확정
5. Claude review `APPROVE`
6. 발주자 구현 승인

## 12. 사용자 목표 UI

상위 mode:

```text
[저축은행]
[상호금융]
[저축은행 + 상호금융]
```

`상호금융` 내부는 기본적으로 다음 세 업권을 포함한다.

```text
☑ 신협
☑ 새마을금고
☑ 농·축협
```

세부 체크를 개별 ON/OFF할 수 있어야 한다.

기본값은 상호금융 mode 선택 시 세 업권 모두 선택된 상태를 후보로 한다. Claude는 실제 UX/데이터 coverage 관점에서 이 기본값이 안전한지 검토한다.

## 13. 공통 랭킹 기준

최종 목표는 다음이다.

> **선택된 모든 업권의 TOP5/TOP10/KPI는 evidence-backed `max_rate`를 공통 금리축으로 사용한다.**

금지:

```text
업권 A: max_rate
업권 B: base_rate fallback
업권 C: 추정 우대 합산값
```

### 13.1 결측 처리

`max_rate`가 없는 행은 최고금리 랭킹에서 `base_rate`로 대체하지 않는다.

대신 최소한:

- 비교가능 상품 수
- max_rate coverage
- 미제공/미수집/공시없음 구분

을 UI 또는 데이터 contract에 남긴다.

## 14. Representative product / denominator

기존 display name으로 대표상품을 묶지 않는다.

PR #115의 stable `product_id`를 기준으로 같은 상품의 여러 행/채널/관측을 안전하게 그룹핑한다.

Claude는 다음을 재검토한다.

- 상품 대표 최고금리를 `MAX(max_rate)`로 잡는 것이 각 업권 rate scope에서 타당한가
- outlet 단위 농·축협에서 같은 product_id의 여러 점포를 하나의 “상품 대표값”으로 합쳐도 되는가
- 기관 TOP5와 상품 TOP5의 denominator를 별도로 둬야 하는가

이 결론 없이 TOP5 계산을 구현하지 않는다.

## 15. Geography / Map Contract

PR #114 evidence:

| 업권 | 현재 geo/rate 의미 |
|---|---|
| 새마을금고 | 실제 주소 기반 / institution rate |
| 신협 | source query region / institution rate |
| 농·축협 | 실제 점포 주소 기반 / outlet rate |

따라서 지도는 단순 row append로 합치지 않는다.

필수 원칙:

- `geo_basis`를 집계에 보존
- query region과 실제 outlet address를 같은 district 정밀도로 취급하지 않음
- 부산 구 단위 drill-down은 해당 업권에서 district 근거가 있는 경우만 활성화
- 업권별 coverage가 다른 경우 동일한 “전국 평균”처럼 보이지 않게 함

## 16. 기간 coverage

PR #114 당시 신협 6개월은 대상 데이터가 0건이었다.

Stage H 구현 시:

- 0건을 다른 기간 값으로 보간하지 않음
- 버튼을 조용히 숨겨 사용자가 coverage 차이를 모르게 하지 않음
- `공시/수집 0건` 또는 동등한 명시적 상태를 사용

Stage G 후 최신 Production 데이터로 다시 측정한다.

## 17. Freshness / Availability

상호금융 mode에는 업권별로 최소 다음 상태가 필요하다.

- 마지막 정상 수집/공시 시점
- comparison coverage
- warning/error 상태
- `availability_scope`
- `geo_basis`

단순 금리순 TOP5가 곧 “모든 사용자가 가입 가능한 TOP5”라는 표현은 사용하지 않는다.

---

# 18. 구현 분할 권고

Claude가 다른 dependency를 발견하지 않는다는 전제에서 향후 PR은 최소 다음처럼 분리한다.

### PR-F — Source Evidence only

- 공식 원천 조사
- Production read-only evidence
- `kfcc`/`nh_local` max-rate semantics Go/No-Go 문서
- **코드 변경 없음**

### PR-G1 — KFCC max_rate

- GO일 때만 adapter/parser contract 변경
- tests + shadow/prod evidence

### PR-G2 — NH local max_rate

- GO일 때만 adapter/parser contract 변경
- tests + shadow/prod evidence

### PR-H1 — strategy data contract expansion

- sector universe
- stable product_id 유지
- metric/coverage/freshness contract
- UI 변경 최소화

### PR-H2 — mode selector + 상호금융 세부 체크

- 저축은행 / 상호금융 / 통합
- 신협 / 새마을금고 / 농·축협

### PR-H3 — 지도/KPI/TOP5 sector-aware refinement

- 최고금리 공통 기준
- geography basis
- availability/freshness 표출

각 PR은 앞 단계 merge 후 최신 main에서 시작한다. stacked PR을 기본값으로 사용하지 않는다.

---

# 19. FREEZE / 금지사항

Claude review와 발주자 승인 전:

- collector 변경 금지
- DB/schema/migration 변경 금지
- 전략 universe 확대 금지
- `max_rate ?? base_rate` fallback 금지
- 우대 문구 임의 산술 합산 금지
- institution/product identity merge 금지
- canonical name fallback 금지
- Production Release Gate ON 금지
- 현재 저축은행 전략 계산식/예측엔진 변경 금지

---

# 20. Claude에게 요청할 Review Scope

Claude는 이 문서를 단순 문장 리뷰하지 말고 **최신 main 코드와 Production 계약을 기준으로 반증 시도**한다.

최소 확인사항:

1. `kfcc`, `nh_local`, `cu` collector/parser의 실제 source path
2. `provides_max_rate` capability의 현재 사용처와 부작용
3. `base_rate` / `max_rate`가 DB에 저장되는 실제 execution path
4. raw artifact에서 상품·기간·기관/점포 linkage를 재현 가능한지
5. PR #115의 stable product ID transport가 상호금융 universe에도 안전한지
6. product representative / TOP5 denominator 정의의 함정
7. outlet-rate와 institution-rate를 혼합할 때 생기는 왜곡
8. 신협 6개월 및 기타 coverage gap 처리
9. historical backfill 필요 여부
10. 기존 public `data/table.json` 계약 및 검색 화면 회귀 가능성
11. Strategy Preview / Vercel / Release Gate 경로
12. Stage F→G→H 순서가 실제 dependency graph와 맞는지

## 20.1 Claude Review 결과 형식

아래 형식으로 답변한다.

```markdown
# Review verdict
APPROVE | CHANGE REQUESTED

## Blocking findings
- ...

## Non-blocking findings
- ...

## Source-semantic findings
### KFCC
...
### NH local
...
### CU reference
...

## Contract corrections
- ...

## Recommended PR decomposition
- ...

## Final go/no-go
- Stage F: GO / CHANGE
- Stage G KFCC: GO / BLOCKED
- Stage G NH: GO / BLOCKED
- Stage H: GO / BLOCKED
```

**Blocking finding이 하나라도 있으면 구현을 시작하지 않는다.**

---

# 21. Claude가 특히 판단해야 할 미확정 사항

이 문서에서 임의로 확정하지 않고 reviewer 판단을 요청한다.

### Q1. `max_rate` coverage Gate

상호금융 통합 랭킹을 열기 위한 sector별 coverage를 반드시 100%로 요구할지, 명시적 coverage UI를 전제로 일부 결측을 허용할지.

### Q2. `max_rate == base_rate` 정규화

공식 원천에 별도 최고금리 필드가 없지만 “추가 우대 없음”을 결정론적으로 증명할 수 있는 경우 `max_rate=base_rate`로 저장하는 계약이 안전한지.

### Q3. NH outlet rate 대표화

농·축협의 점포별 금리에서 같은 stable product의 여러 outlet 중 최고값을 상품 대표 `max_rate`로 사용할지, outlet 자체를 전략 비교 단위로 유지할지.

### Q4. 통합 TOP5의 단위

금융기관 TOP5 / 상품 TOP5 / 점포 TOP5를 명확히 분리해야 하는지.

### Q5. Historical backfill

새로운 최고금리 source contract 확보 후 과거 raw artifact를 재처리할 가치가 있는지, 신규 run부터 시작하는 것이 더 안전한지.

---

# 22. 완료 판정

이 문서 자체의 완료 조건은 **Claude 리뷰를 받을 준비가 된 상태**까지다.

현재 단계에서 하지 않는 것:

- Stage F 실제 외부 source 조사 실행
- Stage G collector 구현
- Stage H UI/집계 구현
- Release Gate 변경

다음 진행은:

```text
이 문서 Claude review
→ review 반영해 문서/계약 수정
→ 발주자 승인
→ Stage F부터 순차 진행
```
