# Search main-group toggle / empty-state v1

기준일: 2026-08-24

## 1. 목표

Post-Merge 개선 통합 명세 v3 Track D의 D0/D1을 구현한다.

선행 baseline은 Draft PR #202의 production-backed Search runtime이다.

- baseline exact head: `ba59c9a46b2be3ed37ab5a6ca5340b8ea88f5380`
- General CI: `32691821112` SUCCESS
- Search runtime: `32691817670` SUCCESS
- artifact: `9507546122`

기존 Search에는 마지막 checkbox를 해제했을 때 화면은 0개 선택으로 보이지만 내부 state와 URL은 전체 선택으로 복구되는 hidden-state 불일치가 있다. D1은 이 상태를 제거한다.

## 2. 상태 계약

대상은 `GROUPS`의 8개 main group이다.

- 업권 `sector`
- 상품유형 `type`
- 가입기간 `term`
- 지역 `region`
- 가입채널 `channel`
- 가입제한 `scope`
- 이자방식 `method`
- 우대조건 `prefStatus`

### 2.1 main group 0개 선택

main group 중 하나라도 선택값이 0개이면:

- 의미는 `전체`가 아니라 **선택 없음**
- 조회 결과 = 0건
- 표 = explicit empty state
- 결과 평균 = 비움
- 당사 순위/격차 = empty-state 설명
- 참고카드 = 0건 empty-state
- 금리 분포 = 이전 SVG 제거 + empty-state caption/aria
- 가입기간 차트 = 이전 SVG 제거 + empty-state caption/aria
- 권역 지도 = 이전 map shell 제거 + empty-state caption/aria
- `더 보기` 숨김
- URL에 `key=` 형태로 explicit empty 보존
- 표 안에 해당 group `전체 선택` recovery action 제공

### 2.2 render gate

`matches()`의 기존 계약은 변경하지 않는다.

기존 matcher의:

```js
if (!picked.size) continue;
```

는 그대로 둔다.

main group empty는 `render()` 진입점에서 먼저 감지하고 0건 surface를 만든 뒤 return한다. 이렇게 해야 표/차트/순위/카드가 동일한 empty state를 공유하고 matcher 의미를 광범위하게 바꾸지 않는다.

## 3. 전체 선택 / 전체 해제

main group 상단 action은 실제 현재 상태를 표시한다.

- 모든 값 선택됨 → `전체 해제`, `aria-pressed=true`
- 하나라도 빠짐 → `전체 선택`, `aria-pressed=false`

동작:

- `전체 해제` → main group Set을 0개로 만든다.
- `전체 선택` → 기존 `selectAllGroup()`을 사용한다.
- 개별 checkbox는 마지막 하나까지 끌 수 있다.
- 마지막 checkbox를 끈다고 내부 state를 자동으로 전체 선택으로 되돌리지 않는다.

## 4. parent / child 경계

이번 D1은 **main group만** 변경한다.

기존 parent cleanup은 유지한다.

- `region`에서 부산이 꺼지면 부산 구·군 state를 비운다.
- `prefStatus`에서 `present`가 꺼지면 세부 우대조건 state를 비운다.

다음 nested action은 D1에서 토글로 바꾸지 않는다.

- 부산 구·군 `data-all="gu"`
- 세부 우대조건 `data-all="prefTags"`

둘 다 기존 `전체 선택` select-only semantics를 유지한다. nested 4-state semantics는 별도 D1b 범위다.

## 5. URL 계약

`syncUrl()`은 main group Set이 비어도 key를 생략하지 않는다.

예:

```text
?type=
```

`readUrl()`은 이미 `p.has(k)`를 `urlSetKeys`에 기록한다. 따라서 `type=`은 명시적 empty로 복원되고, 데이터 로드 후 default group refill 대상에서 제외된다.

검증:

1. `전체 해제`
2. 0건
3. URL에 `type=` 존재
4. reload
5. checkbox 0개 / 결과 0건 그대로
6. inline `전체 선택`
7. 원래 결과 및 map/chart surface 복구

## 6. 기본값 비변경

D1은 초기 검색 범위를 바꾸지 않는다.

- 기본 지역 = 서울 / 경기 / 부산
- 나머지 main groups = 기존 default
- 공시일 = 최근 30일
- 표시 = 100건
- 우리회사 pinned row 계약 유지
- exact 12개월 preset은 D2에서 처리

## 7. 검증

### 정적 계약

`tests/test_search_main_group_toggle_contract.py`

- render-entry gate 존재
- matcher `if (!picked.size) continue` 유지
- 마지막 checkbox auto recovery 제거
- explicit empty URL 기록
- table/chart/map/reference empty-state 존재
- nested gu/prefTags select-only 유지

### production-backed browser

`scripts/search_d1_runtime.js`

Desktop 1440 / Mobile 390에서 각각:

- 기본 결과 > 0
- 상품유형 all-selected → button `전체 해제`
- button click → DOM 0개 / 결과 0건
- table recovery action 표시
- filter summary / rank / reference card explicit empty
- histogram / term SVG / map shell stale output 없음
- URL `type=`
- reload 후 0건 유지
- inline recovery 후 기본 결과와 map 복구
- 개별 checkbox 마지막 해제도 0건 유지
- main group button으로 다시 전체 복구
- 부산 구·군 / 세부 우대조건 nested select-only 유지
- horizontal overflow 없음
- console/pageerror 없음

## 8. 데이터 / Release safety

- production R2 snapshot은 runner-local restore만 수행
- build/browser 전후 DB SHA exact equality
- production DB write 없음
- R2 upload 없음
- collector/scheduler 변경 없음
- canonical rate 변경 없음
- source precedence/authority 변경 없음
- stable product identity 변경 없음
- schema/migration 변경 없음
- Strategy Release Gate OFF

## 9. Rollback

D1 변경은 Search UI state machine과 검증 파일에 한정한다.

문제가 있으면 D1 PR 전체를 revert하면 #202 baseline의 기존 behavior로 돌아간다. 데이터/DB/source authority에는 rollback 대상이 없다.

## 10. DoD

- General CI SUCCESS
- D1 contract tests SUCCESS
- production-backed Search D1 runtime SUCCESS
- desktop 1440 SUCCESS
- mobile 390 SUCCESS
- explicit empty URL reload SUCCESS
- inline recovery SUCCESS
- stale chart/map 제거 및 복구 SUCCESS
- nested semantics 비변경 확인
- DB SHA exact equality
- Draft PR 상태 유지
- merge하지 않음
- Production Strategy Release Gate OFF
