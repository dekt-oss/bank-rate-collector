# 금리수집기 Post-Merge 개선 통합 명세 v2

- 기준일: 2026-08-24
- 상태: `draft / external-review-ready`
- 기준 `main`: `1325d54e9d28bf05040c4f6c51e92bc45bd69253`
- 관련 핵심 Issue: #98
- 목적: 2026-08-24 이후 개선 작업을 하나의 우선순위·안전경계·검증 계약으로 묶는다.

> 이 문서는 coordination spec이다. 기존 데이터·계산·제품 계약을 임의로 대체하지 않는다.
> 충돌 시 실제 `main` 코드/runtime, `docs/specs/CURRENT.md`, 기능별 최신 세부 spec, Issue/PR 결정이 우선한다.
> 특히 canonical 금리, source authority, stable identity, Production Strategy Release Gate를 이 문서만으로 변경하지 않는다.

---

## 0. 결론

향후 작업의 우선순위는 다음과 같다.

1. **#98 잔여 discrepancy 6건 forensic closure**
2. **payment-method ambiguity 51건 운영화**
3. **공식 홈페이지 evidence 수집·추적 자동화**
4. **검색 대시보드 minor UX 개선**
5. **Strategy release-readiness 패키지 완성** — Release Gate는 계속 OFF
6. **우대조건 구조화 / 관리자 편집 / 성능 / 장기 보존 등 중기 개선**

핵심 원칙은 새 기능을 계속 얹기 전에 **데이터 신뢰성을 설명 가능한 상태로 만들고, 그 설명을 반복 가능한 운영 절차로 만든다**는 것이다.

---

# 1. 현재 검증된 기준점

## 1.1 Main / Strategy

현재 기준 `main`:

`1325d54e9d28bf05040c4f6c51e92bc45bd69253`

PR #190 / #192까지 반영되어 Strategy runtime smoke는 실제 렌더링 기준으로 다음을 검증한다.

- Public Structural cockpit host visible
- Factual Rate Finder host visible
- mobile candidate pseudo-label content/display/visibility/rendered box
- Response Surface SVG display/visibility/non-zero rendered box
- desktop/mobile Chrome smoke

PR #192 merge 후 main production Strategy runtime E2E:

- run: `32673974893`
- conclusion: `SUCCESS`
- artifact: `9502219346`
- digest: `sha256:68776554b3a80b1a7646d11733cb5a64056324dc63a698fb4b495b8125566725`

Strategy decision evidence main run:

- run: `32673974873`
- conclusion: `SUCCESS`

**Production Strategy Release Gate는 계속 OFF다.**
구현·테스트 성공과 공개 승인은 별개의 결정이다.

## 1.2 Source discrepancy audit

PR #191 merge commit:

`a2f13e5d0ea47b37594434895edc7704304c4e51`

검증된 production R2 read-only audit:

- run: `32648131602`
- artifact: `9495439357`
- artifact digest: `sha256:91deac81bb1f6f5ae39c82b0c9782ea115adef011b7edd69a66ef1583d39f097`
- snapshot: `state/snapshots/20260824T000342-3e7439f3.sqlite3.gz`

현재 결과:

- exact comparable matches: **3,681**
- mismatch/incomplete queue: **6**
- P0: **0**
- P1: **2**
- P2: **0**
- P3: **4**
- payment-method ambiguity: **51**
- official contradiction queue: **0**

51건은 현재 artifact 재검사상 모두 `installment_savings`다.
41건은 ambiguity 반대편 정상 source representative가 `counterpart` provenance로 보존된다.

## 1.3 현재 남은 discrepancy queue

### P1

1. 대신저축은행 정기적금 24개월
   - `stale_source`
   - delta `1.00%p`
2. 대신저축은행 정기적금 36개월
   - `stale_source`
   - delta `1.00%p`

### P3

1. DH저축은행 정기예금 12개월 `branch/compound`
   - `freshness_gap`, `0.15%p`
2. DH저축은행 정기예금 12개월 `branch/simple`
   - `freshness_gap`, `0.15%p`
3. DH저축은행 정기예금(비대면) 12개월 `any/compound`
   - `freshness_gap`, `0.10%p`
4. DH저축은행 정기예금(비대면) 12개월 `any/simple`
   - `freshness_gap`, `0.10%p`

이 6건은 오류 확정 목록이 아니라 조사 queue다.

---

# 2. 절대 보존할 불변식

## 2.1 데이터 신뢰성

- discrepancy 결과만으로 canonical 금리를 자동 덮어쓰지 않는다.
- `FSB primary / FINLIFE secondary` 현행 precedence를 별도 승인 없이 변경하지 않는다.
- bank-direct official evidence는 read-only supporting third axis다.
- freshness는 observational metadata이며 authority score가 아니다.
- source가 제공하지 않는 variant dimension을 추정하지 않는다.
- payment method가 여러 개이고 rate pair가 다르면 fail-closed한다.
- raw/source locator/artifact hash/effective date/captured date provenance를 보존한다.

## 2.2 운영 안전성

- discrepancy 조사에서 production R2 canonical write를 하지 않는다.
- 감사 결과만으로 `rate-data`를 수정하지 않는다.
- schema/migration이 필요하면 별도 high-risk 작업으로 분리한다.
- collector/scheduler 변경은 source evidence와 runtime 검증 없이 섞지 않는다.

## 2.3 Strategy 공개

- Production Strategy Release Gate는 기본 OFF다.
- CI/runtime 성공은 Release Gate ON 승인이 아니다.
- Release Gate ON은 사용자의 별도 명시적 승인으로만 수행한다.

---

# 3. Track A — #98 잔여 discrepancy 6건 forensic closure

**우선순위: 최우선 / High-risk data**

## A1. 대신저축은행 P1 24/36개월

각 항목마다 다음을 확인한다.

- FSB raw payload / source locator / artifact provenance
- FINLIFE raw payload / source locator / artifact provenance
- `source_effective_at`
- `last_seen_at`
- `join_channel`
- `interest_method`
- `payment_method`가 있으면 해당 값
- 개별 저축은행 공식 상품공시
- 금리변경/시행 공지
- official `captured_at` / `effective_at`
- nominal rate와 annualized yield 구분

완료 조건:

- 두 source가 언제 어떤 값을 관찰했는지 시계열 설명 가능
- direct-bank evidence 확보 또는 `미확보` 명시
- `stale_source` 분류를 실제 evidence로 재검증
- authority를 자동 선택하지 않고도 mismatch 원인을 설명 가능

## A2. DH저축은행 P3 4건

완료 조건:

- branch/비대면 × simple/compound를 섞지 않음
- 0.10~0.15%p 차이가 publication/freshness lag인지 재검증
- official evidence가 variant별로 유일하게 연결되는지 확인
- 모호하면 fail-closed 유지

## A3. 금지

- 홈페이지 값 하나만 보고 canonical overwrite
- 검색 snippet/cache만으로 truth 확정
- 서로 다른 채널/이자방식/적립방식을 최고금리 기준으로 병합

---

# 4. Track B — payment-method ambiguity 51건 운영화

**우선순위: 높음 / Data-model decision gate**

현재 automatic source key는 6D다.

`institution + normalized product + product_type + term + join_channel + interest_method`

FINLIFE가 동일 6D 안에 여러 `payment_method`와 서로 다른 rate pair를 제공하면 최고값을 대표로 선택하지 않고 `ambiguous_variant_dimension`으로 차단한다.

다음 단계에서는 51건 전체 census를 만든다.

확인 항목:

- 기관/상품 분포
- 정액/자유적립 등 payment method 조합
- rate pair 차이 분포
- 반대편 source의 payment method coverage
- 시간에 따른 ambiguity 증감
- counterpart provenance completeness

### 중요한 설계 경계

`payment_method`를 지금 즉시 stable/canonical identity의 7번째 strict key로 올리지 않는다.

먼저 아래 영향도를 계산한 뒤 별도 decision spec/PR에서 판단한다.

- FSB payment-method coverage
- FINLIFE coverage
- 실제 상품 의미가 갈리는 비율
- 7D 전환 시 source-only 증가량
- 기존 exact comparable universe 변화량

---

# 5. Track C — 공식 홈페이지 evidence 운영 자동화

**우선순위: 높음 / Track A·B 안정화 후**

처음부터 모든 저축은행을 상시 크롤링하지 않는다.

MVP는 **queue-targeted evidence capture**다.

입력:

- P0~P3 discrepancy queue
- review 대상으로 지정된 dimension ambiguity

각 evidence record 최소 필드:

- institution / product / term
- `join_channel`
- `interest_method`
- 필요한 경우 `payment_method`
- source URL
- evidence surface 유형
- nominal rate
- annualized yield 별도 필드
- `captured_at`
- `effective_at` 또는 unknown
- capture method
- workflow/run ID
- artifact ID
- raw response artifact digest

안전 규칙:

- direct-bank evidence가 canonical을 직접 쓰지 않는다.
- 공식 도메인이라는 이유만으로 최신 authority로 자동 승격하지 않는다.
- product page / rate-change notice / FSB-hosted surface가 충돌하면 conflict/ambiguity로 남긴다.
- audit path와 canonical collection path를 기본적으로 분리한다.

확인된 교훈:

- 키움예스 사례: 직접 공시와 FSB-hosted bank surface가 시점에 따라 다른 값을 보였음.
- 대백 사례: live HTTP raw response + capture time + artifact digest를 남겨야 historical truth를 재검토할 수 있었음.

---

# 6. Track D — 검색 대시보드 minor UX 개선

**우선순위: 중간 / 독립적인 UI PR로 병행 가능**

이 Track은 데이터 계산·수집·canonical contract를 바꾸지 않는 검색 화면 UX 개선이다.

## D1. `전체 선택`을 토글로 변경

### Current

현재 주요 필터 그룹의 `전체 선택` 버튼은 클릭할 때마다 전체 항목을 다시 선택한다.
또 개별 체크박스의 마지막 한 개를 해제하면 `selectAllGroup()`을 다시 호출하여 빈 선택 상태를 허용하지 않는다.

즉 현재는:

- `전체 선택` → 모두 체크
- 다시 `전체 선택` → 그대로 모두 체크
- 마지막 체크 해제 → 자동으로 다시 전체 체크

### Target

사용자 요구:

- `전체 선택` 버튼을 한 번 누르면 전체 선택
- **전체가 이미 선택된 상태에서 다시 누르면 전체 선택 해제**
- 다시 누르면 전체 선택으로 복귀

권고 UI:

- 상태에 따라 버튼 텍스트를 `전체 선택` ↔ `전체 해제`로 변경
- `aria-pressed` 또는 동등한 상태 표현 추가
- 부산 구·군, 세부 우대조건 등 nested group에도 같은 원칙 적용

### 중요한 구현 쟁점

현재 코드에는 “빈 체크를 전체로 해석하면 화면과 실제 조건이 반대로 보인다”는 이유로 마지막 체크 해제를 막는 안전장치가 있다.
따라서 토글을 구현하면서 아래 둘을 모순 없이 함께 정리해야 한다.

1. group empty state를 실제 `선택 없음`으로 정의할지
2. empty를 `필터 없음 = 전체`로 유지할지

**권고안:** 사용자에게 체크가 0개로 보이는 상태를 허용한다면 결과 의미도 `선택 없음`으로 일치시키고, hidden fallback으로 전체 결과를 보여주지 않는다.
즉 전체 해제 시 해당 dimension 결과는 0건이 되고, 다시 `전체 선택`하면 복구된다.

외부 리뷰에서 이 semantics가 기존 UX 계약과 충돌하지 않는지 반드시 검증한다.

## D2. `1년 예금 / 1년 적금` 업무 기준을 더 잘 보이게

### Current 확인 결과

현재 기본 필터는 다음과 같다.

- 업권: 전체
- 상품유형: 전체
- 가입기간: 전체
- 지역: 서울·경기·부산
- 공시일: 최근 30일

또 기간·상품유형을 별도로 고르지 않았을 때 일부 통계/차트는 **12개월 정기예금**으로 좁혀 비교한다.
즉 현재 “12개월” 개념은 이미 일부 분석 기준에 존재하지만:

- 검색 필터 자체의 기본값이 12개월인 것은 아님
- 정기적금 12개월은 동일 수준의 기본 업무 기준으로 노출되지 않음
- 사용자가 화면만 보고 `1년 예금 / 1년 적금`을 즉시 업무 기준으로 인지하기 어려움

### Target

검색 대시보드 상단 또는 조회조건 첫 영역에 **업무 기준 프리셋**을 눈에 띄게 제공한다.

필수 프리셋:

- `1년 예금`
- `1년 적금`

동작:

- `1년 예금` → `term=12`, `type=term_deposit`
- `1년 적금` → `term=12`, `type=installment_savings`
- 일반 가입기간/상품유형 필터와 상태가 동기화되어야 함
- 사용자가 일반 필터를 바꾸면 프리셋 active 상태도 실제 조건과 일치해야 함
- 숨은 별도 state를 만들지 않음

### 시각 디자인

프리셋은 기존 저채도 고려저축은행 계열 팔레트를 유지하면서 일반 필터보다 한 단계 강조한다.

권고:

- 채도가 과도한 원색 사용 금지
- `1년 예금` / `1년 적금`은 같은 중요도지만 서로 구분 가능한 tint 사용
- active 상태는 background + border + weight로 명확히 표현
- hover와 active를 색만으로 구분하지 말고 border/weight/indicator 병행
- 모바일 390px에서도 한 줄 또는 자연스러운 2열 배치

### 기본값 결정

외부 리뷰에서 다음 세 안을 비교한다.

**안 A — 1년 예금 기본 active + 1년 적금 즉시 전환**
- 기존 분석이 12개월 정기예금 중심이므로 변화가 작음
- 적금도 한 클릭으로 접근 가능

**안 B — `1년 예·적금` combined preset 추가**
- 12개월 예금/적금을 함께 보지만, 통계/차트에서 두 상품군을 하나의 중앙값으로 섞으면 안 됨
- combined view에서는 상품유형별 별도 통계가 필요해 minor scope를 넘어갈 가능성이 있음

**안 C — 초기 필터는 현재 그대로 두고 두 프리셋만 강하게 노출**
- 가장 안전하지만 “기본세팅” 요구를 가장 약하게 반영함

**현재 권고는 안 A다.**
이유는 현행 분석 baseline이 이미 12개월 정기예금 중심이고, 적금과 예금의 금리를 하나의 통계로 섞지 않으면서도 1년 적금을 즉시 비교할 수 있기 때문이다.

단, 외부 리뷰가 더 나은 UX/통계 계약을 제시하면 변경 가능하다.

## D3. Acceptance

- 전체 선택 버튼이 deterministic toggle로 동작
- all → none → all 왕복 가능
- nested group도 동일한 동작 원칙
- empty group semantics와 실제 결과가 화면 상태와 일치
- `1년 예금`과 `1년 적금` 프리셋이 명확히 보임
- 프리셋과 기존 필터가 양방향 동기화
- exact 12개월을 사용하며 `7~12개월` bucket으로 오인하지 않음
- 예금/적금 통계를 하나로 섞지 않음
- desktop/mobile에서 선택 상태가 명확함
- 기존 최고금리 기준, 최근 30일, 부산 세부구, 우대조건 세부보기 동작 회귀 없음
- 계산/수집/source precedence/canonical 변경 없음

---

# 7. Track E — Strategy release-readiness

**우선순위: Track A~C 이후 / Release decision**

Release-readiness package:

1. current main SHA
2. General CI
3. production-data Strategy runtime E2E
4. desktop/mobile evidence artifact
5. current source discrepancy summary
   - P0/P1/P2/P3
   - ambiguity count
   - official contradiction count
6. Strategy가 사용하는 canonical/source contract
7. 알려진 limitation 및 사용자 표시 문구
8. rollback/disable path
9. Release Gate ON 전 최종 수동 checklist

Release 판단은 다음 네 상태를 분리한다.

- `implementation_ready`
- `runtime_verified`
- `data_risk_reviewed`
- `user_approved_release`

앞의 세 개가 true여도 마지막 승인이 없으면 Release Gate는 OFF다.

---

# 8. Track F — 중기 제품 개선

## F1. 우대조건 구조화

후속 후보:

- 조건 문장 분해
- 표준 condition code
- 조건별 `add_rate`
- `mandatory`
- `stackable`
- 원천 미제공 / 명시적 없음 / 조건 있음 구분 유지

원천에 없는 우대금리를 추정하지 않는다.

## F2. Manual Override / 관리자 편집

UI부터 만들지 않는다.
먼저 다음을 결정한다.

- server runtime 여부
- GitHub/config 기반 운영 여부
- 원천값과 수동값의 표시 규칙
- override history/audit trail

## F3. Excel export

CSV/JSON이 이미 존재하므로 XLSX는 편의 기능으로 취급한다.

## F4. KFCC/NH 추가 상품 영역

- KFCC 요구불예탁금 금액구간 파싱
- NH local 입출금식 surface

실제 source fixture/contract 확보 후 parser를 설계한다.

---

# 9. Track G — 운영·성능·복구

## G1. Production smoke coverage audit

이미 Strategy production-data E2E가 있으므로 새 smoke를 무조건 추가하지 않는다.
검색/메인/API/Strategy 중 실제 production runtime evidence가 부족한 영역만 찾고 자동화한다.

## G2. Browser performance baseline

구조 변경 전에 측정한다.

- fetch/decompress
- JSON parse
- first meaningful render
- filter latency
- peak memory
- desktop/mobile 차이

측정값이 실제 문제를 보일 때만 sharding/lazy loading을 검토한다.

## G3. Collector reliability

NH/KFCC 등에 대해 병렬화를 먼저 하지 않는다.

순서:

1. latency/timeout/retry 측정
2. transient failure 분류
3. bounded retry + jitter/backoff
4. source-friendly pacing 확인
5. 근거가 있을 때 제한적 병렬화

## G4. Retention / recovery

- current R2 restore 정기 검증
- snapshot integrity
- raw 1년 보존 요구 확정
- 필요 시 raw archive 설계
- 정기 restore drill

---

# 10. 실행 순서와 PR 경계

## Phase 1 — Data Trust Closure

1. 대신 P1 2건
2. DH P3 4건
3. ambiguity 51건 census

PR 원칙:

- source discrepancy 범위끼리만 묶음
- canonical write 없음
- production R2 read-only audit 필수

## Phase 2 — Evidence Automation

1. queue-targeted official capture MVP
2. raw artifact digest/provenance
3. rerun reproducibility

## Phase 3 — Search UX Minor

별도 UI PR로 진행한다.

포함:

- 전체 선택 ↔ 전체 해제 toggle
- empty-state semantics 정리
- 1년 예금 / 1년 적금 업무 프리셋
- 시각 강조
- desktop/mobile runtime smoke

비포함:

- 데이터 계산 변경
- source authority 변경
- Strategy 변경

## Phase 4 — Release Readiness

데이터 신뢰성 결과와 Strategy runtime evidence를 한 묶음으로 검토한다.
Release Gate ON은 사용자 승인 전까지 하지 않는다.

## Phase 5 — Product / Operations

우대조건, 관리자 편집, export, 성능, retention을 각각 독립된 작업으로 진행한다.

---

# 11. 공통 Definition of Done

각 구현 PR은 최소 다음을 보고한다.

1. current state / target state
2. changed files
3. 계약 변경 여부
4. targeted tests
5. full regression
6. lint/typecheck/build 해당 항목
7. 가능한 runtime evidence
8. production/read-only evidence가 필요한 경우 결과
9. adversarial self-review
10. magic number / heuristic 검토
11. remaining risks
12. current main/head SHA
13. 사용자가 직접 확인하는 방법

검증하지 못한 항목은 `미검증`으로 표시한다.

---

# 12. 외부 리뷰용 프롬프트

아래 내용을 그대로 Claude/Codex/다른 외부 리뷰어에게 전달할 수 있다.

```text
당신은 `dekt-oss/bank-rate-collector`의 향후 개선 계획을 적대적으로 검토하는 외부 리뷰어입니다.

목표는 문서를 칭찬하는 것이 아니라, 실제 구현 전에 잘못된 우선순위·데이터 계약 위반·UX 회귀·운영 위험을 찾아내는 것입니다.

## 반드시 읽을 것

GitHub 저장소 `dekt-oss/bank-rate-collector`의 최신 상태를 Source of Truth로 사용하세요.

1. `CLAUDE.md`
2. `AGENTS.md`가 있으면 해당 파일
3. `docs/specs/CURRENT.md`
4. `docs/specs/20260824-post-merge-improvement-master-plan-v2.md`  ← 리뷰 대상
5. `docs/specs/20260823-source-discrepancy-payment-ambiguity-v4.md`
6. `docs/specs/20260823-source-discrepancy-variant-freshness-v3.md`
7. `web/templates/site.html`의 검색 조건/전체선택/12개월 기준 관련 현재 구현
8. Issue #98 최신 코멘트
9. PR #191, #192 최신 상태 및 검증 근거

접근하지 못한 파일이나 runtime evidence는 읽은 척하지 말고 `미확인`으로 표시하세요.

## 현재 기준점

- main: `1325d54e9d28bf05040c4f6c51e92bc45bd69253`
- source discrepancy production audit:
  - exact comparable 3,681
  - mismatch/incomplete 6
  - P0 0 / P1 2 / P2 0 / P3 4
  - payment-method ambiguity 51
  - official contradiction 0
- Strategy main production runtime E2E는 성공했지만 Production Strategy Release Gate는 OFF

## 리뷰해야 할 핵심

### A. 데이터 신뢰성

- 잔여 discrepancy 6건 조사 순서가 타당한가?
- 6D source identity를 유지하고 payment_method를 즉시 7D stable identity로 올리지 않는 판단이 안전한가?
- ambiguity 51건 census 전에 놓친 dimension/반례가 있는가?
- freshness와 authority가 충분히 분리되어 있는가?
- bank-direct evidence 자동화가 canonical을 우회해 변경할 위험이 없는가?
- audit provenance가 historical 재검증에 충분한가?

### B. 검색 대시보드 minor UX

현재 코드는 상품유형/가입기간을 기본적으로 전체 선택하며, 기간·유형 조건이 없을 때 일부 차트/통계만 12개월 정기예금으로 좁힙니다.
또 `전체 선택`은 항상 전체를 채우며 마지막 체크 하나를 해제하면 다시 전체 선택으로 복귀합니다.

새 요구는:
1. `전체 선택`을 다시 누르면 전체 해제되는 toggle
2. `1년 예금` / `1년 적금`을 업무 기준 프리셋으로 더 눈에 띄게 노출
3. 현재 권고안은 `1년 예금`을 initial active로 하고 `1년 적금`을 동일 수준의 즉시 전환 프리셋으로 제공

다음을 검토하세요.

- all → none → all toggle semantics가 기존 필터 계약을 깨지 않는가?
- 전체 해제 시 0건으로 보는 것이 UX상 맞는가, 아니면 더 나은 명시적 semantics가 있는가?
- 개별 마지막 체크 해제 동작도 함께 바꿔야 하는가?
- 부산 구·군 / 세부 우대조건 nested group에도 같은 toggle 계약을 적용하는 것이 맞는가?
- 12개월 exact term과 현재 `7~12개월` bucket이 혼동될 가능성은 없는가?
- `1년 예금` initial active가 적절한가?
- `1년 예금/적금` combined default가 더 낫다면 예금과 적금 통계를 섞지 않고 어떻게 설계해야 하는가?
- 색상 강조가 기존 저채도 고려저축은행 계열 디자인과 접근성을 해치지 않는가?
- mobile 390px에서 조작/가독성 문제가 없는가?

### C. Release / 운영

- Strategy release-readiness를 데이터 신뢰성 Track 뒤에 두는 순서가 맞는가?
- Release Gate와 구현 완료가 충분히 분리되어 있는가?
- production smoke / performance / retention 순서가 과도하거나 빠진 항목은 없는가?

## 리뷰 방식

문서의 의도를 그대로 받아들이지 말고, 현재 코드와 runtime evidence를 먼저 확인한 뒤 반례를 찾으세요.

각 finding은 반드시 아래 형식으로 작성하세요.

- `P0 / P1 / P2 / P3`
- 문제 요약
- 근거: 파일/함수/Issue/PR/runtime evidence
- 실제 실패 시나리오
- 필요한 수정
- 수정하지 않아도 되는 이유가 있다면 그 이유

우선순위 의미:

- P0: 데이터 손상, 잘못된 금리 의사결정, destructive/public 위험
- P1: 구현 전에 반드시 해결해야 할 설계 결함
- P2: 중요한 회귀/모호성/운영 리스크
- P3: 품질 개선 또는 문서 명료화

## 최종 출력

1. 결론: 이 명세서를 구현 기준으로 사용해도 되는지 `GO / GO WITH CHANGES / NO-GO`
2. P0~P3 findings
3. 검색 대시보드 UX에 대한 권고안
   - 전체선택 toggle semantics
   - 1년 예금/적금 default/preset 방식
   - 색상/상태 표현
4. 데이터 신뢰성 Track의 누락 위험
5. 구현 순서 변경이 필요하다면 수정된 순서
6. 반드시 문서에 반영해야 할 변경사항만 별도 체크리스트

자동 merge나 Production Strategy Release Gate ON을 제안하지 마세요.
```

---

# 13. 이번 문서의 비범위

이 문서 PR 자체에서는 다음을 하지 않는다.

- 코드 구현
- canonical 금리 수정
- source precedence / authority 변경
- DB/schema/migration
- collector/scheduler 변경
- production R2/rate-data write
- Strategy 기능 변경
- Production Strategy Release Gate 변경
- Issue #98 close

---

# 14. 다음 액션

외부 리뷰를 먼저 받아도 되고, 리뷰 없이도 Phase 1과 Phase 3은 서로 다른 branch/PR에서 병행 가능하다.

단 다음은 지킨다.

- Phase 1은 source-discrepancy high-risk gate 적용
- Phase 3은 search UX-only PR로 분리
- Production Strategy Release Gate는 계속 OFF
- 명시적 승인 없이 merge하지 않는다.
