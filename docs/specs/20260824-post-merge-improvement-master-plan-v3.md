# 금리수집기 Post-Merge 개선 통합 명세 v3

- 기준일: 2026-08-24
- 상태: `draft / adversarial-review-applied / external-re-review-ready`
- 기준 `main`: `1325d54e9d28bf05040c4f6c51e92bc45bd69253`
- 관련 핵심 Issue: #98
- 목적: 2026-08-24 이후 개선 작업을 하나의 우선순위·안전경계·검증 계약으로 묶고, v2 외부 적대적 리뷰에서 확인된 P0/P1을 구현 전에 닫는다.

> 이 문서는 coordination spec이다. 기존 데이터·계산·제품 계약을 임의로 대체하지 않는다.
> 충돌 시 실제 `main` 코드/runtime, `docs/specs/CURRENT.md`, 기능별 최신 세부 spec, Issue/PR 결정이 우선한다.
> canonical 금리, source authority, stable identity, Production Strategy Release Gate를 이 문서만으로 변경하지 않는다.

---

## 0. 결론

v2 외부 적대적 리뷰 결론은 `GO WITH CHANGES`였고, **Track D 검색 UX는 현 v2 설계로는 NO-GO**였다.

코드 재확인 결과 핵심 P0 4건은 실제 구조와 일치한다.

1. 빈 `state.picked[group]`은 현재 `matches()`에서 **전체/무제약**으로 해석된다.
2. 빈 group은 `syncUrl()`에서 URL에 기록되지 않아 공유 시 상태가 소실된다.
3. `term/type`이 비면 `noTermOrTypePicked()`가 12개월 정기예금 차트/기준을 활성화한다.
4. 기존 `COND_PRESETS`에는 이미 이름상 `1년` 예금/적금 4개가 있으나 실제 가입기간은 모두 `7~12개월` bucket이다.
5. exact 12개월은 현재 `tmin/tmax`로 표현해야 하지만 기존 `presetOn()`은 `state.picked`만 비교한다.

따라서 v3 실행 순서는 다음으로 수정한다.

1. **A0 — discrepancy 분류 규칙 재검증**
2. **잔여 6건 forensic closure**
3. **payment-method ambiguity 51건 census + 차단 착시 지표**
4. **queue-targeted official evidence 자동화 + canonical-write 기계 가드**
5. **검색 화면 runtime baseline 확보**
6. **D0 — 검색 UX 상태 계약 결정**
7. **D1 — main filter 전체선택 toggle**
8. **D2 — exact 12개월 `1년 예금 / 1년 적금` 업무 프리셋**
9. **Strategy release-readiness** — Release Gate는 계속 OFF
10. 중기 제품/운영 개선

---

# 1. 외부 리뷰 반영 판정

| Finding | 판정 | v3 처리 |
|---|---|---|
| P0-1 empty group ↔ matcher/URL 충돌 | 수용 | render 진입 gate + URL empty sentinel 계약 |
| P0-2 `noTermOrTypePicked()` 휴면 분기 재활성화 | 수용 | empty gate에서 차트·배지·표를 함께 종료 |
| P0-3 기존 `COND_PRESETS` 4개가 이미 `1년` 라벨 사용 | 수용 | 기존 프리셋 term 계약을 D0에서 명시적으로 정리 |
| P0-4 exact 12 프리셋 active 판정 불가 | 수용 | preset schema / `presetOn()` 확장 결정 포함 |
| P1-1 nested group parent/child cascade | 수용 | D1에서 제외, D1b 별도 결정 후 구현 |
| P1-2 discrepancy 분류 규칙 선검증 필요 | 수용 | A0 신설 |
| P1-3 ambiguity가 mismatch를 가리는 차단 착시 | 수용 | blocked-delta / candidate-count / no-counterpart census 추가 |
| P2-1 official evidence → canonical 유출 기계 가드 부재 | 수용 | contract test 추가 |
| P2-2 release readiness 상태 저장 위치 불명확 | 수용 | Phase 4 전용 GitHub Issue를 단일 상태 원장으로 사용 |
| P2-3 Search runtime baseline 부재 | 수용 | Phase 2.5로 앞당김 |
| P2-4 audit run head 추적성 | 수용 | run headSha와 main blob 동일성 근거 병기 |
| P3 color hierarchy | 부분 수용 | 새 임의 색상 금지, 기존 token 재사용 + 배치/라벨로 강조 |
| P3 390px 방법 미정 | 수용 | 390px browser smoke acceptance 고정 |
| P3 `CLAUDE.md` / `AGENTS.md` 부재 | 보류 | 현재 repo root에는 없음. 이 문서 PR에서 임의 생성하지 않음 |

---

# 2. 현재 검증된 기준점

## 2.1 Main / Strategy

기준 `main`:

`1325d54e9d28bf05040c4f6c51e92bc45bd69253`

PR #190 / #192 반영 후 Strategy runtime은 실제 렌더 기준으로 다음을 검증한다.

- Public Structural cockpit host visible
- Factual Rate Finder host visible
- mobile candidate pseudo-label content/display/visibility/rendered box
- Response Surface SVG display/visibility/non-zero rendered box
- desktop/mobile Chrome smoke

PR #192 merge 후 main production Strategy runtime E2E:

- run `32673974893`
- conclusion `SUCCESS`
- artifact `9502219346`
- digest `sha256:68776554b3a80b1a7646d11733cb5a64056324dc63a698fb4b495b8125566725`

Strategy decision evidence main run:

- run `32673974873`
- conclusion `SUCCESS`

**Production Strategy Release Gate는 계속 OFF다.**
구현·테스트 성공과 공개 승인은 별개의 결정이다.

## 2.2 Source discrepancy audit

PR #191 merge commit:

`a2f13e5d0ea47b37594434895edc7704304c4e51`

production R2 read-only audit:

- run `32648131602`
- run head branch `feat/source-discrepancy-postmerge-review-hardening-20260824`
- run head SHA `dcb12b320fd9b36dd6444434302e8974d972c3a5`
- conclusion `SUCCESS`
- artifact `9495439357`
- artifact digest `sha256:91deac81bb1f6f5ae39c82b0c9782ea115adef011b7edd69a66ef1583d39f097`

이 run은 main head 자체에서 실행된 것은 아니다. 다만 재검증한 핵심 audit 파일은 run head와 current main의 Git blob SHA가 동일하다.

- `src/rate_monitor/services/source_discrepancy_service.py`
  - both: `23832f3b94f4b28b8d81dee172421d052caa43c6`
- `scripts/source_discrepancy_audit.py`
  - both: `78603a045a09208007278643c1be23b2b98963c3`

따라서 수치는 current main audit logic과 호환되는 evidence로 사용하되, run headSha를 숨기지 않는다.

현재 결과:

- exact comparable matches: **3,681**
- mismatch/incomplete queue: **6**
- P0: **0**
- P1: **2**
- P2: **0**
- P3: **4**
- payment-method ambiguity: **51**
- official contradiction queue: **0**

51건 전부 `installment_savings`, counterpart provenance 41건이라는 수치는 이전 artifact 직접 검사 결과를 근거로 한다. 이후 release-readiness 패키지에서는 동일 artifact 또는 최신 재실행 artifact로 다시 확인한다.

## 2.3 현재 잔여 discrepancy queue

### P1

1. 대신저축은행 정기적금 24개월 — `stale_source`, delta `1.00%p`
2. 대신저축은행 정기적금 36개월 — `stale_source`, delta `1.00%p`

### P3

1. DH저축은행 정기예금 12개월 `branch/compound` — `freshness_gap`, `0.15%p`
2. DH저축은행 정기예금 12개월 `branch/simple` — `freshness_gap`, `0.15%p`
3. DH저축은행 정기예금(비대면) 12개월 `any/compound` — `freshness_gap`, `0.10%p`
4. DH저축은행 정기예금(비대면) 12개월 `any/simple` — `freshness_gap`, `0.10%p`

이 6건은 오류 확정 목록이 아니라 조사 queue다.

---

# 3. 절대 보존할 불변식

## 3.1 데이터 신뢰성

- discrepancy 결과만으로 canonical 금리를 자동 덮어쓰지 않는다.
- `FSB primary / FINLIFE secondary` 현행 precedence를 별도 승인 없이 변경하지 않는다.
- bank-direct official evidence는 read-only supporting third axis다.
- freshness는 observational metadata이며 authority score가 아니다.
- source가 제공하지 않는 variant dimension을 추정하지 않는다.
- payment method가 여러 개이고 rate pair가 다르면 fail-closed한다.
- raw/source locator/artifact hash/effective date/captured date provenance를 보존한다.

## 3.2 운영 안전성

- discrepancy 조사에서 production R2 canonical write를 하지 않는다.
- 감사 결과만으로 `rate-data`를 수정하지 않는다.
- schema/migration이 필요하면 별도 high-risk 작업으로 분리한다.
- collector/scheduler 변경은 source evidence와 runtime 검증 없이 섞지 않는다.

## 3.3 Strategy 공개

- Production Strategy Release Gate는 기본 OFF다.
- CI/runtime 성공은 Release Gate ON 승인이 아니다.
- Release Gate ON은 사용자의 별도 명시적 승인으로만 수행한다.

---

# 4. Track A — discrepancy 6건 forensic closure

**우선순위: 최우선 / High-risk data**

## A0. 분류 규칙 재검증 — 새 선행 단계

직전 #98 forensic에서 P0가 실제 source 오류가 아니라 payment-method collapse 또는 stale/manual official evidence로 무효화된 사례가 있었다.

따라서 개별 6건을 조사하기 전에 다음 분류 규칙을 먼저 재검증한다.

- `stale_source`
- `freshness_gap`
- `same_reference_date`
- effective-date gap / last-seen gap 계산
- official evidence가 있을 때/없을 때 분류 변화
- variant ambiguity가 있을 때 queue 차단 조건

A0 산출물:

1. 각 classification의 deterministic condition 표
2. representative fixture 또는 current queue 6건을 이용한 재현 테스트
3. 동일 input이면 동일 classification이 나오는지 확인
4. classification은 investigation priority일 뿐 source authority가 아님을 재확인

A0 완료 후 current 6건을 **일괄 재분류**하고 A1/A2로 진행한다.

## A1. 대신저축은행 24/36개월

각 항목 최소 확인:

- FSB raw payload / source locator / artifact provenance
- FINLIFE raw payload / source locator / artifact provenance
- `source_effective_at`
- `last_seen_at`
- `join_channel`
- `interest_method`
- 필요한 경우 `payment_method`
- 개별 저축은행 공식 상품공시
- 금리변경/시행 공지
- official `captured_at` / `effective_at`
- nominal rate와 annualized yield 구분

완료 조건:

- 두 source가 언제 어떤 값을 관찰했는지 시계열 설명 가능
- direct-bank evidence 확보 또는 `미확보` 명시
- A0 규칙으로 classification 재판정
- authority를 자동 선택하지 않고도 mismatch 원인 설명 가능

## A2. DH저축은행 4건

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

# 5. Track B — payment-method ambiguity 51건 운영화

**우선순위: 높음 / Data-model decision gate**

현재 automatic source key는 6D다.

`institution + normalized product + product_type + term + join_channel + interest_method`

FINLIFE가 동일 6D 안에 여러 `payment_method`와 서로 다른 rate pair를 제공하면 최고값을 대표로 선택하지 않고 `ambiguous_variant_dimension`으로 차단한다.

## B1. 51건 census 필수 항목

기존 항목:

- 기관/상품 분포
- payment method 조합
- rate pair 차이 분포
- 반대편 source의 payment method coverage
- 시간에 따른 ambiguity 증감
- counterpart provenance completeness

외부 리뷰 반영 추가 항목:

1. **blocked rate-delta 분포**
   - ambiguity 때문에 P0~P3 queue에 들어가지 않은 candidate의 금리차 분포
   - 기존 P0/P1 임계와 같은 band에 해당하는 건수는 별도 `blocked_risk_band`로 보고
   - 이 수치를 authority score로 사용하지 않음
2. **동일 6D key 내 candidate 수 분포**
   - 2개
   - 3개 이상
3. **product_type 분포 재검증**
   - 현재 51건 전부 `installment_savings`라는 관측을 최신 artifact에서 재확인
4. **counterpart 없는 항목 분석**
   - current 51−41 = 10건의 원인 분류
5. **queue masking indicator**
   - `comparable mismatch count`와 `ambiguity-blocked count`를 항상 함께 표시
   - P0=0만 단독으로 “데이터 위험 0”처럼 해석하지 않음

## B2. 7D 전환 결정 경계

`payment_method`를 지금 즉시 stable/canonical identity의 7번째 strict key로 올리지 않는다.

먼저 다음 영향도를 계산한 뒤 별도 decision spec/PR에서 판단한다.

- FSB payment-method coverage
- FINLIFE coverage
- 실제 상품 의미가 갈리는 비율
- 7D 전환 시 source-only 증가량
- 기존 exact comparable universe 변화량

---

# 6. Track C — 공식 홈페이지 evidence 운영 자동화

**우선순위: 높음 / A·B 안정화 후**

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

## C1. 안전 규칙

- direct-bank evidence가 canonical을 직접 쓰지 않는다.
- 공식 도메인이라는 이유만으로 최신 authority로 자동 승격하지 않는다.
- product page / rate-change notice / FSB-hosted surface가 충돌하면 conflict/ambiguity로 남긴다.
- audit path와 canonical collection path를 분리한다.

## C2. 기계적 canonical-write 가드 — 새 필수 계약

산문 규칙만으로 두지 않는다.

최소 하나 이상의 machine check를 둔다.

- official evidence capture/audit module이 canonical write service/repository를 import하지 않는지 import-boundary test
- 또는 테스트 중 canonical writer를 sentinel로 대체하여 evidence path 실행 시 call count가 0임을 assertion

DoD:

- evidence capture test 실행 후 canonical mutation count `0`
- production R2는 read-only evidence에서 write `0`

---

# 7. Phase 2.5 — Search dashboard runtime baseline

**Track D 코드 변경 전에 먼저 확보한다.**

현재 Strategy에는 production-data runtime E2E가 있지만 검색 대시보드의 동일 수준 baseline은 별도 확인이 필요하다.

최소 baseline:

### Desktop

- 1440px Chromium
- 초기 기본 필터 상태
- `자주 쓰는 조건` 4개 버튼 렌더
- 필터 1개 on/off
- 결과 건수 / table / chart 표시
- URL sync 확인

### Mobile

- **390px Chromium** 고정
- horizontal page overflow 없음
- presets 자연스러운 wrap
- 필터 panel 조작 가능
- active/disabled/empty 상태 읽기 가능

증거:

- workflow/run 또는 재현 가능한 browser test
- screenshot 또는 DOM assertion
- console error 여부

이 baseline을 Track D 전/후 비교 기준으로 사용한다.

---

# 8. Track D — 검색 대시보드 minor UX 개선

**상태: v2 NO-GO 해소 후 구현 가능**

이 Track은 데이터 계산·수집·canonical contract를 바꾸지 않는다.

## D0. 코드 구현 전 상태 계약 결정 — 필수 선행 단계

### D0-1. 현재 empty semantics

현재 코드상:

- `matches()`의 `if (!picked.size) continue` → empty main group = 무제약/전체
- `guNarrowed` / `prefNarrowed`도 `size > 0`일 때만 세부 필터 적용
- `syncUrl()`은 empty main group을 URL에 기록하지 않음
- `noTermOrTypePicked()`는 term/type 모두 empty면 12개월 정기예금 basis를 활성화
- 마지막 checkbox를 해제하면 `selectAllGroup()`으로 다시 전체 선택

따라서 단순히 `전체 선택` 버튼을 `clear()`로 바꾸면 안 된다.

### D0-2. v3 확정 원칙 — main group empty = 선택 없음 / 결과 0

사용자에게 0개가 선택된 상태를 보여준다면 실제 결과도 `선택 없음`이어야 한다.

단 matcher의 기존 empty semantics를 광범위하게 바꾸지 않는다.

**권고 구현 경계: render 진입 gate**

개념:

```text
if (MAIN_FILTER_GROUPS 중 하나라도 selected count == 0):
    table = 0건
    chart = empty state
    rank/reference cards = empty state
    region chart = empty state
    result summary = 0건
    inline recovery action = "전체 선택"
    URL에는 해당 group의 explicit empty를 보존
    return
```

효과:

- `matches()`의 기존 `empty = no constraint` 계약을 건드리지 않음
- `noTermOrTypePicked()`의 12개월 fallback에 도달하지 않음
- table 0건 + 12개월 chart 같은 모집단 불일치 방지
- rollback 범위가 작음

### D0-3. URL empty-state 계약

공유 링크에서 같은 화면이 재현되어야 한다.

main group이 empty일 때 `syncUrl()`은 해당 key를 **explicit empty parameter**로 기록한다.

예:

`?term=`

현재 `readUrl()`은 `p.has(k)`를 `urlSetKeys`에 기록하므로, explicit empty를 보존하면 default re-fill을 막을 수 있다.

Acceptance:

- empty 상태 URL copy → 새 탭 open → 동일 group 0개 / 결과 0건
- parameter 누락은 default filter 의미와 구분

### D0-4. main group vs nested group 분리

v2의 “nested group에도 같은 원칙”은 철회한다.

**D1에서는 main `GROUPS`만 toggle 대상으로 한다.**

- 업권
- 상품유형
- 가입기간
- 지역
- 그 외 main group

부산 구·군 / 세부 우대조건은 parent-child cascade가 있으므로 **D1b 별도 결정**으로 분리한다.

D1b 전에는 아래 4상태 의미표를 작성한다.

| Parent | Child | 의미 | 결과 |
|---|---|---|---|
| off | empty | ? | 결정 필요 |
| off | non-empty | ? | hidden stale state 금지 |
| on | empty | ? | 결정 필요 |
| on | non-empty | explicit narrow | 기존 의미 유지 |

부산 구·군과 preference tags는 의미가 같다고 가정하지 않는다.

## D1. main filter `전체 선택 ↔ 전체 해제` toggle

Target:

- 전체가 아닌 상태에서 버튼 클릭 → 전체 선택
- 전체가 이미 선택된 상태에서 다시 클릭 → 전체 해제
- 다시 클릭 → 전체 선택
- 버튼 label `전체 선택` ↔ `전체 해제`
- `aria-pressed` 또는 동등한 상태 제공
- 개별 checkbox 마지막 1개도 해제 가능
- 기존 `if (!set.size) selectAllGroup(...)` 자동복구 제거
- empty 결과 처리는 D0 render gate에 위임

Acceptance:

- all → none → all deterministic 왕복
- button과 checkbox가 같은 state machine 사용
- empty URL round-trip 성공
- empty 상태에서 chart/table/reference 모집단 불일치 없음

## D1b. nested group toggle — 별도 후속

사용자의 최종 목표에는 부산 구·군 / 세부 우대조건의 전체선택 재클릭 해제도 포함할 수 있다.

다만 D1과 동시에 구현하지 않는다.

선행 조건:

- parent-child 4상태 의미 확정
- parent 재선택 시 child 자동복구 여부 확정
- `guNarrowed` / `prefNarrowed` empty semantics 확정
- URL representation 확정

이후 독립 PR 또는 D1 후속 commit으로 구현한다.

## D2. `1년 예금 / 1년 적금` 업무 기준 프리셋

### D2-1. Current

현재 초기 필터:

- 업권 전체
- 상품유형 전체
- 가입기간 전체
- 지역 서울·경기·부산
- 공시일 최근 30일

기간·상품유형이 비어 있을 때 일부 분석 basis만 12개월 정기예금으로 좁히는 legacy fallback이 있다.

또 기존 `COND_PRESETS` 4개가 이미 존재한다.

- `부산 저축은행 · 1년 정기예금`
- `부산 저축은행 · 1년 적금`
- `부산 상호금융 · 1년 정기예금`
- `부산 상호금융 · 1년 적금`

그러나 네 개 모두 실제 `term`은 exact 12가 아니라 `7-12` bucket이다.

### D2-2. 기본값 결정 — v2 안 A 철회

**초기 필터는 현재 그대로 유지한다.**

즉 `1년 예금`을 initial active로 강제하지 않는다.

이유:

- minor UX에서 초기 result universe를 크게 바꾸지 않음
- 기존 사용자 동작 회귀 최소화
- `noTermOrTypePicked()` 등 기존 분석 fallback과의 예상치 못한 결합을 피함

대신 exact 12개월 업무 프리셋을 가장 앞에 눈에 띄게 배치한다.

신규:

1. `1년 예금 · 12개월`
2. `1년 적금 · 12개월`

동작:

- 1년 예금 → `type=term_deposit`, exact `term=12`
- 1년 적금 → `type=installment_savings`, exact `term=12`
- 지역/업권은 현재 선택을 불필요하게 덮어쓰지 않는 방향을 기본으로 검토
- exact term은 `7-12` bucket과 구별

### D2-3. 기존 4개 `1년` 프리셋 라벨 정정

같은 `1년`이라는 단어에 서로 다른 기간이 섞이지 않게 한다.

권고 라벨:

- `부산 저축은행 · 7~12개월 정기예금`
- `부산 저축은행 · 7~12개월 적금`
- `부산 상호금융 · 7~12개월 정기예금`
- `부산 상호금융 · 7~12개월 적금`

기존 동작 자체를 exact 12로 자동 변경하지 않는다. label과 실제 bucket 의미를 먼저 일치시킨다.

### D2-4. exact 12 preset state model

현재 `term` checkbox group에는 exact 12 값이 없고 `7-12` bucket만 있다.
exact 12는 `tmin=12`, `tmax=12`로 표현 가능하다.

따라서 preset schema는 `state.picked`만으로 제한하면 안 된다.

D0에서 다음 중 하나로 확정한다.

**권고: preset schema가 pick + scalar/range state를 함께 표현**

개념:

```text
preset = {
  pick: { type: [...] },
  values: { tmin: 12, tmax: 12 }
}
```

그에 맞춰 다음 세 동작을 같은 contract로 통일한다.

- apply preset
- preset button count (`rowMatchesPreset`)
- active 판정 (`presetOn`)

Acceptance:

- 버튼 클릭 직후 active=true
- 사용자가 tmin/tmax/type을 바꾸면 active 즉시 실제 상태와 동기화
- URL reload 후 active 상태 동일
- `7~12개월` 기존 preset과 exact 12 preset의 건수가 다른 경우 라벨로 이유 설명 가능

### D2-5. Combined 예·적금 preset 제외

`1년 예·적금`을 하나의 combined preset으로 만들지 않는다.

예금과 적금을 한 모집단의 중앙값/순위로 섞으면 기존 분석 계약을 깨므로, 별도 이중 통계 설계 없이는 minor scope를 넘는다.

### D2-6. 시각 강조

사용자 요구인 “1년 예금/적금을 더 잘 보이게”는 유지한다.

다만 새 임의 색상 체계를 만들지 않는다.

원칙:

- 기존 `--accent`, `--accent-ink`, `--accent-bg`, `--line` token 재사용
- exact 12개월 두 프리셋을 프리셋 영역 **맨 앞**에 배치
- 필요하면 `업무 기준` 짧은 라벨/구분선을 사용
- inactive는 기존 surface + accent 계열의 낮은 강도
- active는 기존 `.presets button[aria-pressed="true"]` 패턴 재사용
- 색만으로 상태를 구분하지 않고 label + border/weight + `aria-pressed` 병행
- 새 쨍한 원색 금지

390px에서는 기존 `flex-wrap`을 우선 사용하고, 신규 layout system을 만들기 전에 실측한다.

## D3. Track D Acceptance

- Search runtime baseline before/after 비교
- main group all → none → all 성공
- 마지막 checkbox 해제 가능
- explicit empty URL round-trip 성공
- empty state에서 모든 chart/table/reference가 동일하게 empty
- nested group은 D1 PR에서 기존 동작 회귀 없음
- exact 12 `1년 예금` / `1년 적금` 표시
- 기존 4개 preset은 `7~12개월` 의미가 라벨에 드러남
- exact-12 preset active/count/apply가 하나의 state model 사용
- 초기 default universe는 변경하지 않음
- desktop 1440 / mobile 390 runtime smoke
- horizontal page overflow 없음
- 최고금리 기준, 최근 30일, 부산 세부구, 우대조건 기존 동작 회귀 없음
- 계산/수집/source precedence/canonical 변경 없음

---

# 9. Track E — Strategy release-readiness

**우선순위: Data Trust / Evidence 안정화 후**

Release-readiness package:

1. current main SHA
2. General CI
3. production-data Strategy runtime E2E
4. desktop/mobile evidence artifact
5. current source discrepancy summary
   - P0/P1/P2/P3
   - ambiguity count
   - blocked risk band
   - official contradiction count
6. Strategy가 사용하는 canonical/source contract
7. limitation 및 사용자 표시 문구
8. rollback/disable path
9. Release Gate ON 전 최종 수동 checklist

상태는 다음 네 개를 분리한다.

- `implementation_ready`
- `runtime_verified`
- `data_risk_reviewed`
- `user_approved_release`

## E1. 상태 원장

Phase 4 시작 시 **전용 GitHub Release Readiness Issue 하나**를 생성하고 네 상태의 단일 원장으로 사용한다.

- workflow artifact는 evidence
- PR merge는 implementation evidence
- 전용 Issue checklist가 readiness state source of truth
- `user_approved_release`는 사용자 명시 승인 없이는 false

앞의 세 개가 true여도 마지막이 false면 Release Gate는 OFF다.

---

# 10. Track F — 중기 제품 개선

## F1. 우대조건 구조화

- 조건 문장 분해
- 표준 condition code
- 조건별 `add_rate`
- `mandatory`
- `stackable`
- 원천 미제공 / 명시적 없음 / 조건 있음 구분 유지

원천에 없는 우대금리를 추정하지 않는다.

## F2. Manual Override / 관리자 편집

UI부터 만들지 않는다.

먼저 결정:

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

# 11. Track G — 운영·성능·복구

## G1. Production smoke coverage audit

Strategy production-data E2E가 이미 있으므로 무조건 새 smoke를 추가하지 않는다.

검색 화면은 Track D 때문에 Phase 2.5에서 먼저 baseline을 확보한다.
그 외 메인/API/Strategy 중 runtime evidence가 부족한 영역만 식별한다.

## G2. Browser performance baseline

구조 변경 전에 측정한다.

- fetch/decompress
- JSON parse
- first meaningful render
- filter latency
- peak memory
- desktop/mobile 차이

측정값이 실제 문제를 보일 때만 sharding/lazy loading 검토.

## G3. Collector reliability

NH/KFCC 병렬화를 먼저 하지 않는다.

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

# 12. 수정된 실행 순서와 PR 경계

## Phase 1 — Data Trust Closure

1. A0 classification rule 재검증
2. current 6건 일괄 재분류
3. 대신 2건 forensic
4. DH 4건 forensic
5. ambiguity 51건 census + blocked-risk 지표

PR 원칙:

- source discrepancy 범위끼리만 묶음
- canonical write 없음
- production R2 read-only audit 필수

## Phase 2 — Evidence Automation

1. queue-targeted official capture MVP
2. raw artifact digest/provenance
3. canonical-write boundary contract test
4. rerun reproducibility

## Phase 2.5 — Search Runtime Baseline

Track D 전 desktop/mobile baseline을 고정한다.

## Phase 3 — Search UX Minor

### D0 — decision/spec only

- empty main-group semantics
- explicit empty URL representation
- render gate 범위
- 기존 4개 `1년` preset term 의미
- exact 12 preset schema
- nested parent-child state table

### D1 — main group toggle PR

- 전체 선택 ↔ 전체 해제
- last checkbox 해제 허용
- empty render gate
- URL round-trip
- nested group 변경 없음

### D1b — nested group 후속

parent-child state table 승인 후 별도 구현.

### D2 — exact 12개월 업무 preset PR

- `1년 예금 · 12개월`
- `1년 적금 · 12개월`
- 기존 4개 `7~12개월` label 정합성
- existing color tokens 재사용

## Phase 4 — Release Readiness

전용 GitHub Issue에 네 상태를 기록하고 evidence를 링크한다.
Release Gate는 계속 OFF.

## Phase 5 — Product / Operations

우대조건, 관리자 편집, export, 성능, retention을 독립 작업으로 진행.

---

# 13. 공통 Definition of Done

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

추가 machine guards:

- official evidence path canonical mutation `0`
- source discrepancy PR은 current production read-only rerun
- Track D는 desktop 1440 + mobile 390 browser smoke
- filter state가 URL round-trip 후 동일한지 검증

검증하지 못한 항목은 `미검증`으로 표시한다.

---

# 14. 외부 재리뷰용 프롬프트

```text
당신은 `dekt-oss/bank-rate-collector` 개선 통합 명세 v3를 적대적으로 재검토하는 외부 리뷰어입니다.

이전 v2 리뷰에서 P0 4건과 P1/P2가 제기되었고, v3는 이를 반영한 문서입니다.
칭찬보다 “이제 실제 구현을 시작해도 되는가”를 판정하세요.

## Source of Truth

1. 저장소 최신 main
2. `docs/specs/CURRENT.md`
3. `docs/specs/20260824-post-merge-improvement-master-plan-v3.md` ← 대상
4. `docs/specs/20260823-source-discrepancy-payment-ambiguity-v4.md`
5. `docs/specs/20260823-source-discrepancy-variant-freshness-v3.md`
6. `web/templates/site.html`
7. Issue #98 최신 코멘트
8. PR #191 / #192 및 관련 workflow metadata

현재 repo root에 `CLAUDE.md` / `AGENTS.md`가 없다면 없다고 기록하고, 읽은 척하지 마세요.

## 특히 재검토할 것

### Data
- A0 classification rule 재검증이 직전 false-P0 재발 방지에 충분한가?
- ambiguity census의 blocked-rate-delta / candidate-count / no-counterpart 지표로 “P0 감소 착시”를 탐지할 수 있는가?
- 6D 유지 + fail-closed가 여전히 7D 즉시 전환보다 안전한가?
- official evidence path의 canonical-write machine guard가 충분한가?

### Search UX
- main group empty를 matcher 변경 대신 render entry gate로 처리하는 것이 안전한가?
- `?term=` 같은 explicit empty URL 계약이 readUrl/default restore와 실제로 왕복 가능한가?
- `noTermOrTypePicked()`가 empty state에서 실행되지 않는 것이 보장되는가?
- main group과 nested group을 분리한 경계가 타당한가?
- 기존 `COND_PRESETS` 4개의 `7~12개월` 의미와 신규 exact 12개월 preset이 혼동 없이 공존 가능한가?
- exact 12 preset의 apply/count/active를 pick+range state로 통일하면 숨은 상태가 생기지 않는가?
- 초기 default를 유지하고 exact-12 preset만 앞에 배치하는 것이 사용자의 “1년 예금/적금 업무 기준 강조” 요구를 충분히 만족하는가?
- 기존 color token만 재사용하면서도 상태가 충분히 명확한가?
- 390px baseline/after smoke가 실제 회귀를 잡기에 충분한가?

### Release
- 전용 GitHub Issue를 readiness 네 상태의 단일 원장으로 쓰는 것이 충분한가?
- Production Strategy Release Gate OFF 원칙이 우회될 경로가 없는가?

## 출력

1. `GO / GO WITH CHANGES / NO-GO`
2. P0~P3 finding
3. 이전 v2 P0/P1이 실제로 닫혔는지 항목별 `CLOSED / PARTIAL / OPEN`
4. 구현 전에 반드시 고칠 항목만 별도 checklist
5. 구현 순서 수정 필요 시 제안

자동 merge나 Production Strategy Release Gate ON을 제안하지 마세요.
```

---

# 15. 이번 문서 PR의 비범위

이 문서 PR 자체에서는 다음을 하지 않는다.

- 검색 UX 코드 구현
- canonical 금리 수정
- source precedence / authority 변경
- DB/schema/migration
- collector/scheduler 변경
- production R2/rate-data write
- Strategy 기능 변경
- Production Strategy Release Gate 변경
- Issue #98 close
- `CLAUDE.md` / `AGENTS.md` 신규 생성

---

# 16. 다음 액션

이 v3가 재리뷰에서 P0/P1 없이 통과하면 다음 두 흐름을 독립 branch/PR로 병행할 수 있다.

1. **Data Trust:** A0 → current 6건 재분류/forensic
2. **Search UX:** Phase 2.5 runtime baseline → D0 decision → D1 main toggle

단:

- D1b nested toggle은 D0 parent-child 의미 확정 전 구현 금지
- exact-12 D2는 preset state model 확정 전 구현 금지
- 명시적 승인 없이 #193 merge 금지
- Production Strategy Release Gate는 계속 OFF
