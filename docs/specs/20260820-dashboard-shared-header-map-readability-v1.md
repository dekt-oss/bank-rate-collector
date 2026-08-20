# Dashboard Shared Header & Map Readability v1

- 상태: **implementation / user-approved UI decision**
- 기준일: 2026-08-20
- 범위: 검색 조회 `index.html` + 전략 대시보드 `strategy.html` presentation
- 비범위: 금리 계산, source precedence, stable product identity, 수집 계약, Strategy Release Gate, 예측계수

## 1. 사용자 결정

1. 검색 조회와 전략 대시보드는 같은 서비스이므로 **상단 제품 헤더와 페이지 전환 메뉴를 동일한 시각 계약**으로 사용한다.
2. 공통 헤더에는 제품 identity, `검색 조회 / 전략 대시보드` 전환, 보고서 출력, 수집 상태처럼 양쪽 화면에서 공통인 항목만 둔다.
3. 검색 조회에만 필요한 `전국 예·적금 금리 비교` 제목, 우리 회사 선택, 생성/공시 시각, 수집·관리 제어는 **공통 헤더 아래 검색 전용 context 영역**으로 내린다.
4. 검색 조회의 전국 권역 지도는 현재 choropleth 색상 강도를 유지하면서, **지도 자체에서 권역명 + 대표 금리를 바로 읽을 수 있어야 한다.**
5. 오른쪽 지역 상세 패널은 비교의 주 경로가 아니라 선택 지역의 보조 설명으로 축소한다.

## 2. 지도 표시 계약

### 2.1 계산값은 바꾸지 않는다

- 기존 `by_region`/조회 조건 재계산 결과와 `main_map_presentation`의 9개 권역 중앙값을 그대로 사용한다.
- `서울`, `인천·경기`, `강원`, `충청`, `전라`, `경북`, `경남`, `부산`, `제주`의 의미를 바꾸지 않는다.
- 색상 강도, 최고금리/중앙값 기준, 표본 부족 판정, 부산 drill-down은 유지한다.

### 2.2 직접 라벨

- 대한민국 SVG 위에 권역별로 1개의 라벨만 표시한다.
- 라벨은 `권역명` + `금리(%)` 2행 구조를 기본으로 한다.
- 표본 부족 권역은 임의 금리를 만들지 않고 `표본 부족`으로 표시한다.
- 17개 시도 path가 9개 권역으로 묶이더라도 동일 권역 라벨을 중복 생성하지 않는다.
- SVG path의 기존 접근성 문구는 유지하고 직접 라벨 layer는 `aria-hidden` 보조 presentation으로 둔다.

### 2.3 레이아웃

- 지도/상세 패널의 desktop 비율은 지도 중심으로 재조정한다.
- 지도의 과도한 세로 높이는 줄인다.
- 오른쪽 패널은 선택 권역 값, 표본, 당사 비교, 상단 권역 정도만 보조적으로 유지한다.
- 모바일에서는 직접 라벨 글자 크기를 보정하고 상세 패널은 지도 아래로 내려간다.

## 3. 공통 헤더 계약

### 3.1 공통 요소

양쪽 페이지 모두 다음 순서를 유지한다.

1. `SB` identity + `SB 인사이트`
2. `검색 조회 / 전략 대시보드` navigation
3. 공통 액션: `보고서 출력`, 수집 상태/기준 정보

active page만 달라진다.

### 3.2 검색 전용 context

공통 헤더 아래로 이동:

- `전국 예·적금 금리 비교` 제목과 설명
- `우리 회사` 선택
- 생성 시각/공시 기준일
- `지금 수집하기`/관리자 등 검색 운영 제어

기존 DOM id와 이벤트 리스너는 가능한 한 유지하기 위해 node를 복제하지 않고 runtime에서 이동한다.

### 3.3 Strategy 전용 context

- `수신상품 전략 대시보드` hero와 시장 scope는 기존처럼 공통 헤더 아래에 둔다.
- Strategy의 계산/의사결정 영역은 변경하지 않는다.

## 4. 구현 원칙

- 공통 UI는 `dashboard_ui_refinement_presentation.py` 한 계층에서 양쪽 페이지에 주입한다.
- 검색 지도 직접 라벨도 이 presentation layer가 기존 main map DOM을 읽어 추가한다.
- 원천 dataset, DB, canonical table, Strategy slice는 변경하지 않는다.
- UI 변경 때문에 hidden Strategy map을 다시 직접 조작하는 smoke 계약을 복원하지 않는다.

## 5. Acceptance Criteria

### Header

- [ ] 검색/Strategy 상단 헤더의 높이·배경·identity·navigation·active style이 동일하다.
- [ ] 검색 전용 제목/회사/생성정보가 공통 헤더 아래에 있다.
- [ ] 검색/Strategy 모두 보고서 출력 기능을 잃지 않는다.
- [ ] 검색의 수집 상태 버튼/수집 제어 동작을 잃지 않는다.

### Map

- [ ] 지도에서 오른쪽 패널을 보지 않아도 9개 권역의 지역명과 금리를 직접 비교할 수 있다.
- [ ] 기존 choropleth 색상 강도가 유지된다.
- [ ] 9개 권역 라벨이 중복되지 않는다.
- [ ] 표본 부족은 금리를 추정하지 않는다.
- [ ] 부산 클릭 drill-down은 유지된다.
- [ ] 조회 조건 변경 후 재렌더된 지도에도 직접 라벨이 다시 적용된다.
- [ ] desktop/mobile에서 수평 overflow가 없다.

## 6. 검증

최종 검증은 가능한 환경에서 다음 순서로 수행한다.

1. Python static/unit contract
2. `node --check` presentation smoke
3. Search/Strategy desktop browser smoke
4. mobile browser smoke
5. production-data static build
6. 실제 배포 HTML/화면 확인

실행하지 못한 항목은 PR에서 `미검증`으로 표시한다.
