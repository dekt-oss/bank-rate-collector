# Strategy Market-first IA v2

작성일: 2026-09-17

## 목적

전략 대시보드의 기능 수는 유지하되, 사용자가 실제 수신상품 기획 업무에서 판단하는 순서에 맞춰 화면을 **시장현황 → 금리설계 → 상세 판단요소**로 재배치한다.

이번 변경은 presentation/IA 변경이다. 금리 계산, stable product identity, source precedence, peer 선정, 예측계수, 수신반응 계산 등 기존 **계산 계약을 변경하지 않는다**.

## 화면 순서

### 01 시장현황

1. 시장 요약
2. 금리 움직임
3. 당사 시장 위치

대표 시장방향은 stable product snapshot 비교 기반 Market Intelligence를 사용한다. 비교상품 전체를 분모로 인상·유지·인하, 중앙값 변화, 상위 10% 진입선 변화, breadth 및 실제 관측기간을 함께 보여주는 기존 계약을 유지한다.

기존 `strategy.market_changes`는 삭제하지 않는다. 다만 사용자에게 같은 지표처럼 보이지 않도록 **최근 30일 금리 변경 이벤트**로 명명한다. 이 값은 실제 금리가 변경된 상품 이벤트만 집계하므로 대표 시장방향과 분모가 다르다는 점을 화면에서 명시한다.

### 02 금리설계

- 신상품 금리 시뮬레이션
- 기본금리, 우대금리, 가입기간
- 시장 위치와 수신반응 시나리오
- 예측모형 상세는 progressive disclosure 유지

시뮬레이터는 시장현황을 확인한 직후 배치한다.

### 03 상세 판단요소

- 경쟁사 · Peer 분석
- 지역별 금리
- 우대조건 · 상품구조
- 특판 · 시장기회
- 외부 자금환경
- 데이터 근거 · 품질

기존 기능과 데이터를 삭제하지 않고 우선순위를 낮춰 하단 상세 근거로 배치한다.

## Desktop navigation

데스크톱에는 화면 왼쪽에 **왼쪽 floating navigation**을 제공한다. 메뉴는 `시장`, `설계`, `기타` 같은 추상명 대신 위 실제 기능명을 그대로 사용한다.

- 링크는 실제 DOM anchor/hash를 사용한다.
- 클릭 시 해당 기능 위치로 이동한다.
- 현재 viewport의 기능을 `aria-current="location"`으로 표시한다.
- 브라우저 hash/back-forward 의미를 보존한다.
- 본문을 가리지 않도록 데스크톱에서 본문 폭을 조정한다.

1280px 이하에서는 floating navigation을 숨긴다. 모바일/태블릿에는 별도 세로메뉴를 만들지 않고 기존 세로 스크롤을 유지한다.

## 경계

- `market_changes`와 Market Intelligence 숫자를 억지로 일치시키지 않는다.
- 데이터 payload와 계산 함수를 presentation에서 재구현하지 않는다.
- 부산 상세지도 `busan-focus` 동작을 유지한다.
- 기존 prediction/structural/public evidence disclosure를 유지한다.
- 특판 Radar의 fail-closed 정책과 공개 OFF 상태를 변경하지 않는다.
- Strategy 공개 여부는 기존 **Production Strategy Release Gate**를 그대로 따른다.

## 검증

- presentation injection idempotency
- 시장현황 → 금리설계 → 상세 판단요소 순서 계약
- 실제 메뉴명 및 anchor 계약
- desktop 왼쪽 floating navigation / mobile hide 계약
- 대표 시장방향과 변경 이벤트 설명 분리
- 기존 Busan focus / model disclosure 보존
- 전체 Strategy presentation composition 회귀 테스트
