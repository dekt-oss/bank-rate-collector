# 상호금융 최고금리 공통화·전략 확장 — Claude Review Work Order v2

```yaml
document_type: review_work_order
status: changes_applied_pending_re_review
created_at: 2026-08-17
updated_at: 2026-08-17
target_repository: dekt-oss/bank-rate-collector
base_commit: 89312caabe8caae7326a03028ef9d4c551ca1496
issue: 108
review_pr: 116
review_comment: 5313512589
review_verdict: CHANGE_REQUESTED
depends_on:
  - PR_113_merged
  - PR_114_merged
  - PR_115_merged
risk:
  - financial_rate_semantics
  - external_source_collection
  - stable_identity
  - shared_canonical_consumers
  - cross_sector_comparison
  - geography_scope
implementation_blocked: true
release_gate_change: false
```

> 이 문서는 PR #116의 Claude `CHANGE REQUESTED` 리뷰를 반영한 **재검토용 계약 문서**다.
> 현재 허용되는 다음 단계는 문서 재리뷰뿐이다.
> 재리뷰가 통과되기 전에는 Stage F/G/H 구현을 시작하지 않는다.
> 재리뷰가 통과되더라도 Stage G/H는 각 Entry Gate와 발주자 승인을 별도로 통과해야 한다.

---

## 1. 결론과 현재 Gate

장기 제품 목표는 유지한다.

> **가능한 업권에서는 전략 비교의 기본 금리축을 evidence-backed `max_rate`로 통일한다.**

단 다음은 금지한다.

- `max_rate ?? base_rate`를 최고금리로 표시
- 공식 linkage 없는 우대금리 산술 합산
- 이름 기반 product/institution fallback
- NH 조합명을 이름 prefix로 추정·병합
- coverage가 없는 업권을 포함된 것처럼 보이는 통합 랭킹

현재 판정:

| Stage | 상태 | 이유 |
|---|---|---|
| 문서 계약 | **재리뷰 필요** | Claude blocking 4건 및 correction 10건 반영 후 재검토 |
| Stage F source evidence | **GO with CHANGE → 재리뷰 후 착수 가능** | read-only 조사. KFCC/NH/CU 과제 재정의 |
| Stage G KFCC | **BLOCKED** | 현 중앙 공시는 기본이율(우대이율 제외)만 제공 |
| Stage G NH local | **BLOCKED** | 공통 최고금리 필드 부재, 채널 variant 계약 미확정 |
| Stage H strategy expansion | **BLOCKED** | Stage G 결과 및 coverage/단위/지도 계약 미확정 |
| Production Release Gate | **OFF 유지** | 변경 금지 |

---

## 2. 기준점과 기존 Evidence

main 기준 SHA:

```text
89312caabe8caae7326a03028ef9d4c551ca1496
```

완료:

- PR #113 — Issue #108 UX 후속 merged
- PR #114 — 상호금융 Evidence Gate merged
- PR #115 — strategy stable `product_id` 직접 전달 merged

PR #114 기준 `term_deposit`, 6/12/24/36개월 coverage:

| 업권 | 대상 행 | `base_rate` | `max_rate` |
|---|---:|---:|---:|
| 새마을금고 `kfcc` | 24,464 | 100% | **0%** |
| 신협 `cu` | 15,178 | 100% | **100%** |
| 농·축협 `nh_local` | 73,020 | 100% | **0%** |

> 행수는 snapshot 시점에 따라 이동할 수 있다. Claude 리뷰가 확인한 최신 preview에서는 CU가 15,200행이었다. 계약 판단은 특정 행수보다 source semantics와 coverage 비율을 우선한다.

PR #115 이후 strategy target은 stable `product_id`를 DB query 시점부터 직접 운반한다.

- KFCC target `product_id NULL = 0`
- NH local target `product_id NULL = 0`
- public canonical table에는 internal ID를 노출하지 않음

따라서 이번 후속에서 이름 fallback이나 entity merge를 다시 도입하지 않는다.

---

## 3. 공통 금리 계약

### 3.1 `base_rate`

같은 상품 variant·기간·적용범위에서 공식 원천이 공시하는 기본 금리.

### 3.2 `max_rate`

전략 비교에 사용할 `max_rate`는 다음 조건을 만족해야 한다.

1. 공식 또는 프로젝트가 승인한 1차 원천에서 확인 가능
2. 동일 상품/stable product identity와 연결 가능
3. 동일 가입기간과 연결 가능
4. 동일 기관·점포·rate scope와 연결 가능
5. **원천이 우대 구성 또는 우대 적용대상을 제공하면 그 내용을 보존한다. 원천이 우대 구성을 설명하지 않더라도 공식 `최고금리` 필드를 직접 제공하면 이 조건은 충족된 것으로 본다.**
6. 수집 시점 또는 공시 시점이 추적 가능
7. raw artifact/source evidence로 재현 가능

이 정의는 CU처럼 `highRate`를 공식 필드로 제공하지만 `prefCondMemo='없음'`일 수 있는 source를 허용한다.

### 3.3 `max_rate == base_rate`

숫자가 같다는 사실 자체는 문제가 아니다. 두 경로를 구분한다.

#### A. 공식 최고금리 필드 직접 제공

원천이 `max/high rate` 필드를 직접 제공한다면 그 값이 base와 같아도 그대로 저장한다. 이는 fallback이 아니다.

CU가 reference case다.

#### B. 최고금리 필드가 없고 추가 우대 없음이 공식적으로 보장됨

이론상 `max_rate=base_rate` 정규화를 허용할 수 있으나, **현재 검증된 KFCC/NH/CU 중 이 경로를 사용할 수 있는 업권은 없다.**

특히 KFCC 중앙 공시는 `기본이율(우대이율 제외)`를 명시하므로 이 경로 사용을 금지한다.

### 3.4 원천 선언 기반 계산의 제한적 허용

공식 원천이 우대의 대상상품·기간·채널·적용식을 스스로 명시하는 경우에만 계산형 `max_rate`를 검토할 수 있다.

예:

```text
대상상품 A/B
대상기간 1~12개월
인터넷 가입 전용
상품별 금리 + 0.1%p
```

이 경우에도 다음을 모두 맞춰야 한다.

- stable product
- 기간
- 기관/점포
- join channel
- effective date

채널 한정 우대는 기존 창구 variant의 `max_rate`에 합치지 않고 **별도 `join_channel` variant**로 취급한다.

---

# Stage F — 공식 Source Evidence Gate

## 4. 목적

Stage F는 collector 수정이 아니라 **read-only source evidence**다.

목표:

- KFCC: 현 endpoint가 아닌 대체 공식 최고금리 source 존재 여부 발굴
- NH local: 우대 행의 전수 구조와 채널 variant 가능성 검증
- CU: reference contract 보강 및 6개월 0건 원인 확인

DB·collector·Production 데이터·Release Gate는 변경하지 않는다.

## 5. 업권별 조사 계약

### 5.1 KFCC / 새마을금고

Claude 리뷰에서 이미 확인한 fact:

- 현 collector: `/map/list.do` + `/map/goods_19.do`
- `goods_19.do`는 기본이율 표를 제공
- 상품 설명은 `기본이율(우대이율 제외)`를 명시
- 공식 최고금리 필드가 확인되지 않음
- 현 parser는 `max_rate=None`

따라서 Stage F 질문을 다음으로 재정의한다.

1. 금고 개별 공식 홈페이지, MG더뱅킹/공식 공시 등 **대체 공식 source**에 최고/우대금리가 존재하는가?
2. 해당 source를 금고·상품·기간과 stable하게 연결할 공식 key가 있는가?
3. 우대조건/가입자격/채널/rate scope를 함께 추적 가능한가?
4. raw artifact와 effective date를 재현 가능한가?
5. 대체 source가 없다면 KFCC `max_rate`는 계속 unsupported로 유지한다.

현 `goods_19.do`만으로 `max_rate=base_rate`를 생성하는 구현은 **NO-GO**다.

### 5.2 NH local / 농·축협

Claude 리뷰에서 확인한 현재 구조:

- 전국 점포 목록 + 점포별 거치식 상세
- `max_rate=None`
- e-joy 인터넷예금 우대 0.1% 같은 우대가 별도 행으로 존재할 수 있음
- 해당 우대는 채널 한정이며 기존 창구 행의 max로 합치는 것이 안전하지 않음

Stage F에서 확인한다.

1. 전 점포에서 우대 행의 형태·대상상품 산문·기간·값이 얼마나 일관적인가?
2. 우대 행이 선언하는 대상상품을 stable product와 결정론적으로 매칭 가능한가?
3. `join_channel=internet` 별도 variant 계약으로 표현 가능한가?
4. 점포별 우대 행 존재/값 차이를 전수 또는 충분한 evidence로 분류 가능한가?
5. `smartmarket.nonghyup.com` 등 다른 공식 source가 존재하는가? 접근 불가 시 미검증으로 남긴다.
6. 공식 linkage가 불충분하면 공통 `max_rate`를 만들지 않는다.

### 5.3 CU / 신협 reference

CU는 공식 source의 `baseRate`, `highRate`, `prefCondMemo`, `pubiBeginDate`를 직접 제공하는 reference case다.

Stage F에서 추가 확인한다.

1. `provides_max_rate=True`의 실제 source contract를 문서화
2. `max_rate > base_rate`이지만 preference text가 `없음`인 경우가 공식 source semantics상 허용됨을 명시
3. **6개월 target 0건의 원천측 원인 규명**
4. `source_query_region`의 지역 의미와 district 불가 계약 재확인

## 6. Stage F Evidence Matrix

업권별 최소 다음을 기록한다.

| 필드 | 설명 |
|---|---|
| source | 공식 endpoint/page/channel |
| source field | 실제 필드/표 구조 |
| product key | 상품 연결 key |
| institution/outlet key | 기관/점포 연결 key |
| term key | 기간 연결 key |
| base rate | 기본금리 의미 |
| preferential component | 우대 구성 존재 여부 |
| max rate | 직접 제공/공식 계산/unsupported |
| calculation rule | 원천이 보장하는 경우만 |
| join channel | 창구/인터넷/비대면 등 |
| preference text | 제공 여부 및 보존 방식 |
| rate scope | institution / outlet / query-region 등 |
| effective date | 공시일/조회기준일/조회일 |
| raw trace | raw artifact 재현 여부 |
| coverage | 대상행 대비 max 확보율 |
| missing class | 미제공 / 미수집 / 공시없음 |
| ambiguity | key 다중매칭 여부 |

## 7. Stage F Go/No-Go

### GO

공식 source가 stable product·기간·scope·채널과 연결되는 최고금리를 제공하며 raw evidence가 재현 가능.

### CONDITIONAL GO

특정 상품군/채널만 안전하게 지원 가능.

- 지원 universe를 명시적으로 제한
- coverage와 결측 사유를 표출
- 기존 variant에 조용히 합치지 않음

### NO-GO

최고/우대 값은 보이지만 product·term·scope·channel과 안전하게 연결할 수 없음.

---

# Stage G — Collector / Canonical `max_rate` 확장

## 8. Entry Gate

업권별 Stage F가 GO 또는 명시적 CONDITIONAL GO여야 한다.

현재:

- KFCC: **BLOCKED**
- NH local: **BLOCKED**
- CU: existing reference

## 9. 구현 원칙

### 9.1 shared canonical contract

`max_rate`는 전략 화면 전용 필드가 아니다. public 검색 화면·benchmark·dashboard가 공유하는 canonical 계약이다.

따라서 Stage G는 collector 변경만으로 완료할 수 없다.

### 9.2 `provides_max_rate`

현재 관례적 adapter class attribute 수준인 `provides_max_rate`를 Stage G에서 명시적 capability contract로 문서화/검증한다.

단순히 일부 행에 max 값이 생겼다는 이유로 capability를 true로 올리지 않는다.

### 9.3 Historical data

기본은 신규 정상 run부터 적용한다.

과거 raw artifact에 최고금리 정보가 없으면 backfill하지 않는다.

backfill은 **새 공식 source 자체가 과거 공시 이력을 제공하고 해당 시점·상품 linkage를 결정론적으로 재현할 수 있는 경우에만** 별도 작업으로 검토한다.

## 10. Stage G Verification Gate — downstream consumer audit 필수

각 Stage G PR은 source/parser test 외에 **기존 모든 `max_rate` consumer를 감사**해야 한다.

최소 감사 대상:

- `web/templates/site.html`
  - `rateOf = r.max` 기반 필터/순위/백분위
  - 평균/중앙값
  - 히스토그램
  - 지역/구 집계
  - `r.max == null`에 의존하는 우대조건 `원천 미제공` 표기
- `dashboard_service.py`
  - sector benchmark
  - `MAX(o.max_rate)` 기반 `max_rate_top`
- `validation_service.py`
  - kfcc 전용 max-rate hardcode 검사
- `tests/test_gate_contract.py`
  - `without == {"kfcc", "nh_local"}` 고정 계약

필수 evidence:

1. parser/adapter fixture test
2. 정상/결측/우대없음/다중기간/다중채널 test
3. product/term/channel cross-join 방지 test
4. raw artifact traceability
5. collection idempotency
6. `ruff`
7. full `pytest`
8. migration model consistency
9. shadow/read-only Production evidence
10. 공식 source spot-check와 canonical 값 대조
11. **Stage G 적용 전/후 public 검색 화면 및 dashboard OFF/ON diff**
12. 우대조건 `미제공 != 없음` 의미 보존 검증
13. benchmark/ranking denominator 변화 보고

Stage G PR은 downstream 변화가 의도된 것인지 명시적으로 승인받기 전 merge하지 않는다.

---

# Stage H — 전략 대시보드 업권 확장

## 11. Entry Gate

다음이 모두 필요하다.

1. stable `product_id` direct transport — 완료
2. 각 업권 max-rate semantic 판정
3. 편입 업권의 capability/coverage 계약 확정
4. ranking denominator 확정
5. geography/availability/freshness 계약 확정
6. slice payload 비용 재측정
7. 문서 재리뷰 APPROVE
8. 발주자 구현 승인

## 12. Mode / coverage 계약

후보 UI:

```text
[저축은행]
[상호금융]
[저축은행 + 상호금융]

상호금융 세부:
[신협] [새마을금고] [농·축협]
```

### 12.1 최고금리 mode에서 coverage 0%

`max_rate` coverage가 **0%인 업권은 최고금리 mode에서 선택 불가(disabled)** 처리하고 `최고금리 미수집/미지원` 상태를 명시한다.

따라서 현재 데이터 상태라면 `상호금융` 최고금리 mode에서 KFCC/NH를 선택된 것처럼 보이게 해서는 안 된다.

### 12.2 partial coverage

100% coverage를 절대 Gate로 요구하지 않는다.

편입을 위한 최소 계약:

1. 해당 adapter의 `provides_max_rate` capability가 공식 source로 증명됨
2. sector/term별 coverage가 데이터와 UI에 표시됨
3. 결측을 `미제공 / 미수집 / 공시없음`으로 구분
4. base-rate fallback 금지

**partial coverage 허용 임계값은 아직 확정하지 않는다.** Stage H 착수 전 발주자가 명시적으로 정한다.

기본 전체선택은 **그 시점의 coverage Gate를 통과한 업권에만** 적용한다.

---

## 13. Ranking / denominator 계약

### 13.1 NH local의 실제 비교 단위

현재 NH parser는 `source_institution_key == source_outlet_key == brc`이며 발행 데이터에서도 institution과 outlet이 1:1이다.

따라서 현 계약에서 NH의 `institution`은 사실상 **점포**다.

필수 원칙:

- UI/문서에서 NH 단위를 `기관·점포` 또는 동등하게 정직하게 표시
- NH를 조합 단위로 이름 prefix 병합하지 않음
- 조합 단위 대표화는 공식 parent/cooperative identifier 확보 전 금지
- NH의 점포×상품 분모가 타 업권 기관×상품 분모보다 훨씬 크다는 사실을 통합 KPI에 반영

### 13.2 통합 TOP5 기본 단위

현 권고 기본값:

> **기관 대표 TOP5**를 기본으로 하되 NH는 `기관·점포`임을 명시하고 업권별 비교상품 수/coverage를 병기한다.

- institution-rate 업권: 기관의 비교대상 상품 중 `MAX(max_rate)`를 대표값으로 검토 가능
- NH: 점포가 기관이므로 점포 대표값으로 해석
- 상품 TOP5는 통합 기본 랭킹으로 사용하지 않음 — NH 반복 분모가 지배할 수 있음
- 점포 TOP5는 NH 내부 drill-down 전용

Stage H 구현 전에 최신 production으로 denominator를 재측정하고 왜곡을 다시 검증한다.

---

## 14. Geography 계약

업권별 현재 의미가 다르다.

| 업권 | 지역/rate 의미 |
|---|---|
| 저축은행 | 본점 소재지 기반 공시 |
| KFCC | 실제 주소 기반 / institution rate |
| CU | source query region / institution rate |
| NH local | 실제 점포 주소 / outlet(=현 institution) rate |

금지:

- 서로 다른 `geo_basis`를 하나의 지역 평균으로 합산
- CU query-region을 실제 district 주소처럼 사용
- 본점 소재지와 점포 주소를 같은 의미의 부산 구 지도 값으로 합산

허용 방향:

- `geo_basis`를 집계·UI에 보존
- CU는 `조회조건 기준` 별도 layer
- district drill-down은 실제 district evidence가 있는 업권만
- 본점/점포/조회조건은 layer 또는 명시적 basis badge로 구분

---

## 15. Availability / 상품구조 계약

통합 최고금리는 곧 모든 사용자의 실가입 가능 최고금리를 뜻하지 않는다.

필수:

- `availability_scope` filter 또는 badge
- KFCC `workplace_members` 등 자격제한 표기
- 비대면/인터넷 전용 variant의 channel badge
- Block예금 등 구간·회전식 특수구조 상품은 일반 정기예금과 동일 의미로 랭킹 가능한지 별도 evidence

특수구조 원천 의미가 미검증이면 일반 TOP5에 조용히 포함하지 않는다.

---

## 16. Freshness 계약

`source_effective_at`의 의미가 업권별로 동일하지 않다.

예:

- 저축은행: 상품별 공시일
- KFCC: 조회기준일 성격
- CU: `pubiBeginDate`
- NH: 원천 공시일 미제공 시 조회일 성격

따라서 UI에서 모두를 동일한 `최신 공시일`로 부르지 않는다.

업권별로 `공시일 / 적용일 / 조회기준일 / 조회일` 의미를 구분해 표시한다.

---

## 17. Payload / 성능 Gate

기존 strategy slice는 저축은행 중심의 약 1.9k행 규모였다.

Claude 리뷰 추산상 세 상호금융 업권을 단순 포함하면 약 114k행 수준으로 약 60배 증가할 수 있다.

PR-H1 전에 최신 production으로 반드시 재측정한다.

- strategy-table row count/bytes
- build time
- browser parse time
- client-side filter/aggregation cost
- mobile memory/interaction 비용

필요하면 server/build-time preaggregation 또는 sector별 payload 분리를 설계한다.

---

# 18. PR 분할

### PR-doc — 현재 PR #116

- Claude Contract corrections 10건 반영
- 재리뷰 APPROVE 확보
- 코드 변경 없음

### PR-F — Source Evidence only

- KFCC: 대체 공식 source 발굴
- NH: 우대 행 전수 구조 + channel variant feasibility
- CU: 6개월 0건 원인
- code/DB 변경 없음

### PR-G1 — KFCC max_rate

현재 **BLOCKED**.

대체 공식 source가 GO일 때만 시작.

- collector/parser contract
- downstream consumer audit
- validation/gate tests 갱신
- shadow/production evidence

### PR-G2 — NH local max_rate/channel variant

현재 **BLOCKED**.

- source-declared 우대 linkage가 안전할 때만
- 인터넷/비대면 channel variant 분리
- downstream consumer audit
- shadow/production evidence

### PR-H1 — strategy data contract expansion

- sector universe
- coverage/missing classification
- availability/freshness/geo basis
- denominator
- payload 재측정 및 성능 설계

### PR-H2 — mode selector

- 저축은행 / 상호금융 / 통합
- 신협 / 새마을금고 / 농·축협
- coverage Gate 기반 enable/disable/default

### PR-H3 — 지도/KPI/TOP5

- 최고금리 공통축
- 기관·점포 단위 의미
- geography layers
- availability/freshness 표출

각 PR은 선행 PR merge 후 최신 main에서 시작한다. stacked PR을 기본값으로 사용하지 않는다.

---

# 19. FREEZE

재리뷰 및 발주자 승인 전:

- Stage F 실행 금지
- collector 변경 금지
- DB/schema/migration 변경 금지
- strategy universe 확대 금지
- `max_rate ?? base_rate` fallback 금지
- 임의 우대금리 합산 금지
- identity/name fallback 금지
- NH 조합명 추정 grouping 금지
- public 검색 화면 의미 변경 금지
- Production Release Gate ON 금지

---

# 20. Claude 재리뷰 체크리스트

이번 재리뷰에서는 전체 조사 재실행보다 **CHANGE REQUESTED 10건이 계약에 정확히 흡수됐는지**를 우선 검증한다.

필수 확인:

1. §3.2 우대조건 요구가 CU 공식 highRate contract와 모순되지 않는가
2. Stage G downstream consumer audit가 충분한가
3. `site.html` 우대 표기에서 `미제공 != 없음`을 보존하도록 Gate가 잡혔는가
4. coverage 0 업권이 최고금리 mode에 포함된 것처럼 보일 가능성이 제거됐는가
5. partial coverage를 100% 강제하지 않으면서 축 혼합을 막는가
6. NH institution=outlet 1:1 구조가 ranking/label에 정확히 반영됐는가
7. KFCC 과제가 대체 공식 source 발굴로 바뀌었는가
8. NH e-joy형 우대가 기존 행의 max가 아닌 channel variant 후보로 정의됐는가
9. freshness 비대칭, CU 6개월 0건, payload 증가가 후속 Gate에 포함됐는가
10. Stage G/H가 여전히 BLOCKED인가

결과 형식:

```markdown
# Re-review verdict
APPROVE | CHANGE REQUESTED

## Blocking findings
- ...

## Contract correction verification
1. PASS / FAIL — ...
...
10. PASS / FAIL — ...

## Remaining owner decisions
- partial coverage enablement threshold
- ...

## Final go/no-go
- PR-doc: MERGEABLE / BLOCKED
- Stage F: GO / BLOCKED
- Stage G KFCC: BLOCKED / GO
- Stage G NH: BLOCKED / GO
- Stage H: BLOCKED / GO
```

Blocking finding이 하나라도 있으면 APPROVE하지 않는다.

---

# 21. 완료 판정

이 문서의 현재 완료 조건:

```text
Claude CHANGE REQUESTED 10건 반영
→ Claude 재리뷰
→ APPROVE 시 PR #116 문서 merge 후보
→ 발주자 승인
→ Stage F read-only evidence 시작
```

현재 **Stage F/G/H 구현은 시작하지 않는다.**