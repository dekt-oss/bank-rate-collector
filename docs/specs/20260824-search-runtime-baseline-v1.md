# Search runtime baseline v1

기준일: 2026-08-24

## 1. 목적

Post-Merge 개선 통합 명세 v3 Phase 2.5를 실행한다.

Search UX의 전체선택 토글, empty-state render gate, exact 12개월 preset을 구현하기
**전에 현재 브라우저 동작을 고정**한다. 이 PR은 Search UX 동작을 바꾸지 않는다.

baseline은 이후 Track D PR에서 before/after 비교의 기준 artifact로 사용한다.

## 2. Runtime source

- GitHub `main`에서 분기한 exact branch source
- production R2 snapshot을 runner-local SQLite로 restore
- local copy에 migration 적용
- `RATE_MONITOR_STRATEGY_DASHBOARD=0`
- `rate-monitor build-site`로 Search 정적 사이트 생성
- Chrome / Playwright로 실제 `index.html + data/table.json` 실행

Production DB에는 write/upload하지 않는다.

## 3. Viewports

### Desktop

- Chromium / Chrome
- viewport width **1440px**
- height 1000px

### Mobile

- Chromium / Chrome
- viewport width **390px**
- height 844px

390px은 master plan에서 요구한 좁은 모바일 기준이다.

## 4. Default-state evidence

두 viewport 모두 다음을 DOM에서 검증하고 JSON에 보존한다.

- result count > 0
- `표시=100건`은 일반 결과 100건 한도
- 우리 회사 고정행이 존재하면 일반 결과 한도와 별도로 맨 위에 1행을 추가하므로 실제 본문은 최대 101행
- 실제 렌더 행 수 = `min(resultCount - pinnedRows, shownLimit) + pinnedRows`
- pinned row는 0~1건
- 상세 조건은 기본 접힘
- 금리 기준 = `최고금리(우대 포함)`
- 공시일 기본 = 최근 30일
- 기본 지역 = 서울 / 경기 / 부산
- region 외 main groups는 전부 선택
- scalar filter `q/rmin/tmin/tmax`는 비어 있음
- `hideZero=false`
- 표시 100건
- chart container visible
- histogram SVG 실제 렌더
- 가입기간 chart 실제 렌더
- 최종 배포 DOM에서 대한민국 지도 presentation shell 렌더
- 대한민국 지도 SVG path 존재 및 현재 금리 데이터가 연결된 `data-has-rate="1"` path 존재
- document/body horizontal overflow 없음
- console error / pageerror 없음

우리 회사 선택값, 부산 구·군 요약, filter summary, 첫 3개 렌더 row도 evidence에
기록한다.

### 4.1 pinned-row contract

첫 production-backed browser 실행에서 `표시=100건`인데 101행이 렌더되어 baseline
assertion이 실패했다. Search runtime을 확인한 결과 이것은 UI 버그가 아니라 기존 명시적
계약이었다.

`render()`는 다음 순서로 동작한다.

1. 현재 조건 결과에서 우리 회사 대표 고정행을 찾는다.
2. 고정행을 일반 body에서 제거한다.
3. body를 `shownLimit`만큼 slice한다.
4. 고정행을 결과 맨 위에 다시 추가한다.

따라서 결과가 충분히 많고 고정행이 있으면 `100 + 1 = 101`행이 정상이다. baseline은
이를 숨기지 않고 `pinnedRows`, `shownLimit`, `expectedVisibleRows`로 기록한다.

### 4.2 deployed map presentation contract

두 번째 production-backed browser 실행에서는 `regionBars()`가 만든 `.regtile`이 최종 DOM에
남아 있을 것이라고 가정해 실패했다. 실제 배포 경로를 다시 확인하면 `.regtile`은
**중간 계산 결과를 presentation으로 넘기는 transient DOM**이다.

최종 Search build는 `inject_main_map_presentation()`을 적용하고, 브라우저에서
`main_map_presentation`의 MutationObserver가 다음 순서로 동작한다.

1. `regionBars()`가 기존 계산 계약으로 `.regtile`을 만든다.
2. presentation이 그 타일의 지역명·중앙값·표본·drill-down 정보를 읽는다.
3. source SVG geometry에 해당 값을 연결한다.
4. `#reg`의 타일 DOM을 `.main-map-shell` + 대한민국 SVG 지도 DOM으로 교체한다.
5. 값이 연결된 SVG path에 `data-has-rate="1"`을 기록한다.

따라서 production runtime baseline은 transient `.regtile` 수를 성공 조건으로 사용하지
않는다. 최종 배포 surface 기준으로 다음을 검증한다.

- `#reg.main-korea-map .main-map-shell` 정확히 1개
- `.main-map-stage svg path` 1개 이상
- `path[data-has-rate="1"]` 1개 이상
- exact-12 URL reload 뒤에도 동일 presentation이 다시 생성됨

이 검증은 지도 계산 방식을 다시 구현하지 않고, 이미 계산된 결과가 실제 사용자에게
보이는 최종 presentation까지 전달되는지만 확인한다.

## 5. Existing preset baseline

현재 Search preset 4개를 label/id/order/pressed/count와 함께 고정한다.

1. `sb-dep` — `부산 저축은행 · 1년 정기예금`
2. `sb-sav` — `부산 저축은행 · 1년 적금`
3. `mg-dep` — `부산 상호금융 · 1년 정기예금`
4. `mg-sav` — `부산 상호금융 · 1년 적금`

현재 이 네 preset의 `term`은 내부적으로 `7-12` bucket이다. baseline에서는 현재
동작을 바꾸거나 명칭을 수정하지 않는다. Track D2가 exact 12개월 preset과 기존 label
정정을 별도 구현한다.

기본 상태에서는 네 preset 모두 `aria-pressed=false`여야 한다.

## 6. Current all-selection semantics baseline

Track D1 전 현재 동작을 명시적으로 실행해 보존한다.

상품유형 group을 사용한 세 번째 production-backed browser 실행에서 master plan의
“마지막 checkbox 해제 시 화면도 전체 선택으로 복구”라는 표현보다 더 정확한 현재
동작이 확인됐다.

1. 기본 DOM은 all-selected다.
2. 현재 `전체 선택` 버튼을 다시 눌러도 all-selected가 유지된다.
3. checkbox를 하나씩 끈다.
4. 마지막 checkbox를 끄면 change handler가 내부 `state.picked.type`을
   `selectAllGroup()`으로 전체 복구한다.
5. 그러나 generic 상품유형 handler는 그 직후 `renderGroups()`를 호출하지 않는다.
6. 결과적으로 **화면 checkbox는 0개 선택으로 남지만**, 결과 건수와 URL의 `type` 값은
   전체 선택 상태로 복구된다.

즉 현재 before 상태에는 실제 hidden-state 불일치가 있다.

- DOM: `0 / N` checked
- internal filter/result: all-selected
- URL: 전체 type 값 기록
- 사용자에게 보이는 체크 상태와 실제 필터 결과가 다름

baseline evidence string:

`all-button-selects-all-only; last-checkbox-off-restores-state-all-but-leaves-dom-unchecked`

baseline은 이 버그를 정상 동작으로 승인하지 않는다. **D1 전의 실제 회귀 기준으로
보존**한다. D1에서는 자동복구 자체를 제거하고 main group의 explicit empty를 결과 0으로
정의하므로 이 hidden-state 불일치도 함께 사라져야 한다.

## 7. URL / chart sync baseline

현재 기본 상태에서 reset 후 scalar range를 exact 12개월로 설정한다.

- `tmin=12`
- `tmax=12`

검증:

1. URL query에 `tmin=12&tmax=12`가 저장됨
2. 결과 건수 > 0
3. histogram/term chart basis 문자열을 기록
4. 같은 URL을 reload
5. `tmin/tmax` input이 12로 복원됨
6. 결과 건수 exact match
7. histogram aria-label exact match
8. term chart caption exact match
9. 대한민국 지도 presentation 재생성
10. reload 뒤에도 horizontal overflow 없음

이 baseline은 Track D2 exact-12 preset이 기존 scalar/range URL contract를 재사용하거나
대체할 때 회귀를 판단하는 기준이다.

## 8. Evidence artifact

workflow artifact는 최소 다음을 포함한다.

- `search-baseline-desktop-1440.png`
- `search-baseline-mobile-390.png`
- viewport별 JSON
- summary JSON
- local HTTP server log
- site manifest
- runner-local DB pre-build SHA-256

모든 JSON에는 exact `github.sha`를 기록한다.

## 9. DB / Release safety

- production R2는 restore만 수행
- runner-local DB에 migration 적용 후 SHA-256 seal
- site build 후 SHA exact equality
- browser assertion이 실패해도 final DB SHA 검사는 `always()`로 실행
- browser execution 후 SHA exact equality
- rate-data write 없음
- production R2 upload 없음
- Strategy build/release gate OFF
- Search UX 코드 변경 없음
- canonical/source precedence/identity 변경 없음

## 10. Acceptance / DoD

- General CI SUCCESS
- dedicated `search-runtime-baseline` workflow SUCCESS
- exact final-head production snapshot restore SUCCESS
- site build SUCCESS with Strategy Gate OFF
- desktop 1440 runtime assertions SUCCESS
- mobile 390 runtime assertions SUCCESS
- pinned-row / 표시 건수 contract captured
- current preset contract captured
- current all-selection hidden-state mismatch captured
- exact-12 URL reload contract captured
- histogram / term chart rendered in both viewport baselines
- final 대한민국 지도 presentation shell + rate-bearing SVG paths rendered in both viewport baselines
- no browser console/page errors
- no horizontal page overflow
- screenshots + JSON artifact uploaded
- runner-local DB before/after exact SHA equality

이 기준이 충족되기 전에는 D1/D2 UX 변경에 착수했다고 보지 않는다.
