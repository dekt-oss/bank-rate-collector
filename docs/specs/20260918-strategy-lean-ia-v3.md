# Strategy Lean IA v3 — 지표 감량 + 자금환경 우선 + 경쟁사/기관 포지션 통합

작성일: 2026-09-18  
대상: `dekt-oss/bank-rate-collector` Strategy production surface  
기준 main: `7b35c75a56f168f25bb1956a6a43e439b6b6440f`

## 1. 목적

Strategy 화면의 다음 단계는 기능 추가가 아니라 **지표 감량과 판단 흐름 정리**다.

원칙은 아래 세 가지다.

1. 같은 질문에 답하는 지표는 하나만 대표로 노출한다.
2. 시장 판단에 직접 도움이 되지 않는 합성/요약 카드는 화면에서 제거한다.
3. 자금 담당자가 읽는 순서는 `자금환경 → 시장금리 → 금리설계 → 경쟁사/기관 포지션 → 보조분석`으로 고정한다.

금리 계산식, stable product identity, source precedence, ranking population, dedupe/identity,
예측계수, persistent data contract는 이번 작업에서 변경하지 않는다.

---

## 2. 현재 확인된 문제

### 2.1 시장 방향 중복

현재 화면에는 서로 다른 계약의 방향지표가 동시에 노출된다.

- `Market Intelligence`: 동일 stable product의 시작/종료 snapshot 비교
- `최근 30일 금리 변경 이벤트`: 실제 변경 event count
- `저축은행 시장 방향`: 위 event count를 다시 compact bar로 노출
- `시장 인사이트`: 다시 event count를 이용해 "30일 하락 우세"를 생성
- 시뮬레이터 planning strip에도 event 기반 방향을 별도 노출

같은 화면에서 사용자는 모두 "시장 방향"으로 읽게 된다.

### 2.2 상세 판단요소 / 시장 인사이트의 낮은 정보밀도

`상세 판단요소`와 `시장 인사이트`는 여러 신호를 다시 문장으로 합성하지만,
이미 화면에 존재하는 원천 KPI·시장 위치·지역·우대조건을 반복한다.

이번 버전에서는 한눈 대시보드 후보로 사용하지 않는다.
화면에서 제거하고, 향후 핵심요소를 다시 선정한 뒤 별도 dashboard로 재설계한다.

### 2.3 자금환경이 너무 아래에 있음

기준금리, 예금은행 신규취급 금리, 업권 수신잔액은 시장 판단의 기본 환경이다.
현재는 상세 영역 안쪽에 있어 정보 순서가 뒤집혀 있다.

### 2.4 Peer 메뉴 anchor 불안정

현재 `strategy_workspace_presentation`이 먼저 실행되고
`institution-funding-position`은 이후 refinement 단계에서 주입된다.

따라서 workspace가 `Peer|동급|규모` heading을 못 찾으면
`primary.querySelector("article:last-child")`로 fallback한다.
이 결과 왼쪽 `경쟁사 · Peer 분석` 메뉴가 실제 Peer/기관 포지션으로 이동하지 않을 수 있다.

### 2.5 경쟁사 TOP5 가독성 부족

현재 TOP5는 좁은 카드 안에 순위/업권/금융사/상품/기본금리/우대폭/최고금리 등을
동시에 노출한다. 글자크기도 작아 판단 우선순위가 약하다.

기관 수신 포지션과 별도 카드로 분리돼 있어
"금리 경쟁력"과 "수신규모·성장"을 연결해서 보기 어렵다.

### 2.6 의사결정 메뉴가 왼쪽 navigation과 중복

`의사결정 메뉴` 4단계 shortcut은 이미 왼쪽 floating navigation과 역할이 겹친다.
화면 높이만 늘리고 판단정보는 추가하지 않는다.

---

## 3. 목표 IA

### 01. 시장 자금환경 — 최상단

최상단에서 시장의 기본 환경을 먼저 확인한다.

표시:

- 한국은행 기준금리
- 예금은행 순수저축성예금 신규취급 가중평균
- 예금은행 1년 정기예금 신규취급 가중평균
- 저축은행/신협/새마을금고/광의 상호금융 수신잔액 흐름
- 업권 전체 수신잔액 최신값 및 YoY/MoM

정리:

- `external-market-context`를 Strategy 본문 최상단으로 이동한다.
- `market-funding-competition`의 **시장 전체 수신흐름 strip은 유지**한다.
- 같은 카드 안의 기관별 4분면/성장률 랭킹은 기본 화면에서 제거한다.
  기관별 분석은 아래 `경쟁사 · 기관 포지션`으로 통합한다.

### 02. 시장현황

대표 시장방향은 **Market Intelligence snapshot 비교 한 개**로 통일한다.

표시:

- 시장 중앙값 변화
- 상위 10% 진입선 변화
- 동일상품 인상/유지/인하 breadth
- 당사 spread 변화
- 12개월 시장 추이 / 당사 위치

삭제:

- 우측 `최근 30일 금리 변경 이벤트` visible panel
- 별도 `저축은행 시장 방향` compact bar
- `시장 인사이트` 카드
- event-count 기반 `30일 시장 방향`을 대표지표처럼 노출하는 요소

데이터 자체는 삭제하지 않는다.
`strategy.market_changes`는 backend/evidence 용도로 유지한다.

### 03. 금리설계

현재 신상품 금리 시뮬레이션을 유지한다.

단, 상단 planning strip에서 event-count 기반 방향을 핵심 KPI처럼 보이지 않게 한다.

권고:

- `30일 변경 이벤트 방향` 항목은 제거
- 시장 최고 / 시장 평균 / TOP10 / 당사 현재 중심으로 단순화
- 예측모형 상세·민감도는 기존 disclosure 유지

### 04. 경쟁사 · 기관 포지션

현재 `경쟁사 TOP5`와 `기관 수신 포지션`을 같은 분석 섹션으로 묶는다.

#### 04-1. 12개월 경쟁금리 TOP5

판단용 최소 필드만 크게 노출한다.

- 순위
- 업권
- 금융사 / 상품
- 최고금리

기본금리/우대폭은 기본 표에서 제거한다.
원 데이터/계산은 유지한다.

폰트와 행간을 현재보다 키우고, 최고금리와 기관명을 시각적 우선순위로 둔다.

#### 04-2. 기관 수신 포지션

기존 기능 유지:

- 수신잔액
- 규모 percentile
- 6M / 12M 성장
- 업권 중앙값 대비
- Direct Peer 비교

`Direct Peer`는 별도 가짜 메뉴가 아니라 이 섹션 안의 실제 데이터로 취급한다.

왼쪽 메뉴 target은 새 통합 wrapper를 직접 가리킨다.

### 05. 보조분석

아래 항목만 유지한다.

- 우대조건 · 상품구조
- 특판 · 시장기회
- 데이터 근거 · 품질

지역/지도 상세는 기존 production 역할분리 계약대로 Search 화면에서 확인한다.
Strategy에는 Search handoff만 유지하고 지역지도 메뉴는 다시 만들지 않는다.

기존 `상세 판단요소`라는 추상적인 대분류/카드는 제거한다.
필요한 경우 각 실제 기능명으로만 navigation에 노출한다.

---

## 4. 왼쪽 floating navigation

Desktop 전용 원칙은 유지한다.
`max-width: 1280px`에서는 숨긴다.

최종 메뉴 후보:

### 기본환경
- 시장 자금환경
- 업권 수신 흐름

### 시장현황
- 시장 금리 방향
- 12개월 시장 추이

### 금리설계
- 신상품 금리 시뮬레이션

### 경쟁분석
- 경쟁사 · 기관 포지션

### 상품/보조
- 우대조건 · 상품구조
- 특판 · 시장기회
- 데이터 근거 · 품질

삭제할 메뉴:

- 상세 판단요소
- 시장 인사이트
- 경쟁사 · Peer 분석(불안정한 fallback anchor)
- 의사결정 메뉴

### anchor 계약

navigation은 최종 DOM이 만들어진 뒤 실제 id를 기준으로 구성한다.

특히 경쟁분석 target은
`workspace-competitor-position` 같은 명시적 wrapper id를 사용하고,
heading text 검색/fallback로 결정하지 않는다.

---

## 5. 구현 전략

현재 Strategy는 여러 presentation injector가 순차적으로 DOM을 조작한다.

기존 workspace를 전면 재작성하기보다,
**모든 late injector가 끝난 뒤 마지막에 Lean IA reconciler를 실행**한다.

신규 presentation 예:

`strategy_lean_ia_presentation.py`

역할:

1. 최종 DOM 존재 여부 확인
2. 중복/삭제 대상 visible UI 제거 또는 hidden 처리
3. 자금환경 섹션을 최상단으로 이동
4. TOP5 + 기관 수신 포지션 통합 wrapper 생성
5. 기존 workspace detail disclosure 제거
6. 왼쪽 floating navigation을 최종 DOM 기준으로 재구성
7. hash / browser back-forward / scroll active state 유지
8. 중복 실행 idempotent 보장

기존 계산 JS가 삭제된 DOM id를 참조해 오류가 날 수 있는 요소는
DOM 자체 삭제 대신 `hidden`/presentation suppression을 우선한다.

---

## 6. 삭제/숨김 계약

### 화면에서 제거

- `#market-flow details.changes`
- `.strategy-market-direction`
- `.ux-decision-readiness`
- `.workspace-insights` 내 시장 인사이트 visible card
- `#workspace-label-detail`
- `#workspace-detail-disclosure` 자체
- market-funding의 기관 4분면/성장률 ranking pane
- simulator의 event-direction planning tile

### 유지

- `strategy.market_changes` payload
- market intelligence snapshot payload
- external features / funding payload
- institution funding position payload
- Direct Peer payload
- TOP5 underlying rows
- regional/preference/special-offer/evidence payload

---

## 7. 비기능/안전 요구사항

- presentation cleanup만 수행
- financial calculation 변경 금지
- ranking population 변경 금지
- source precedence 변경 금지
- identity/dedupe 변경 금지
- prediction coefficient 변경 금지
- persistent schema/API 변경 금지
- Strategy production publication 유지
- UI merge 후 `Publish UI — main presentation changes` 자동 재발행 경로 검증

---

## 8. 테스트 요구사항

### 정적 계약

- 중복 UI marker가 새 lean IA에서 visible이 아님
- 자금환경이 market intelligence보다 앞에 위치
- 통합 경쟁사/기관 wrapper 존재
- left nav가 명시적 wrapper id를 가리킴
- 1280px 이하 nav hidden
- 기존 market_changes payload / 계산 JS는 제거되지 않음

### runtime/DOM

- Peer/경쟁사 메뉴 클릭 시 `경쟁사 · 기관 포지션`으로 이동
- hash 직접 진입 정상
- browser back/forward 정상
- TOP5 렌더 후에도 wrapper 유지
- institution funding late injection 후에도 wrapper 유지
- 모바일에서 floating nav 없음
- hidden 중복요소가 공간을 차지하지 않음

### repository

- Ruff
- full pytest
- empty DB migration
- Strategy browser/runtime E2E
- production-data Strategy E2E

---

## 9. Production 완료 판정

PR merge만으로 완료로 보지 않는다.

1. CI green
2. UI publish workflow success
3. `rate-data/site-public/site-manifest.json.generated_at`이 merge 이후
4. Vercel deployment success
5. 실제 Strategy HTML에서:
   - 자금환경 최상단
   - 변경 이벤트 panel 없음
   - 저축은행 시장 방향 bar 없음
   - 의사결정 메뉴 없음
   - 시장 인사이트 없음
   - 경쟁사/기관 포지션 통합
   - 왼쪽 메뉴 경쟁분석 anchor 정상
6. production data row count 및 canonical R2 state가 UI-only publish 전후 동일

---

## 10. 이번 작업에서 하지 않는 것

- 새로운 KPI 추가
- "한눈에 보는 시장 인사이트" 재설계
- 새로운 추천점수 생성
- 금리 방향 산식 통합을 위한 backend 계산 변경
- Direct Peer 모집단/규칙 변경
- 수신 성장과 금리 사이 인과추정

향후 별도 작업에서 실제 사용자 판단에 도움이 되는 핵심지표만 다시 선정해
상단 executive dashboard를 재설계한다.


---

## 11. 리뷰 반영 보정

2026-09-18 적대적 구현 리뷰 결과(`docs/reviews/20260918-strategy-lean-ia-v3-review.md`)를 반영한다.

- `market_changes` 관련 DOM은 기존 JS runtime 계약 때문에 삭제하지 않고 visible UI만 숨긴다.
- `inject_strategy_market_direction` / `inject_strategy_decision_scope_compact`는 최종 compositor에서 더 이상 주입하지 않는다.
- `.ux-decision-readiness`와 `.decision-integrated-insight`는 final reconciler에서 숨긴다.
- TOP5와 `institution-funding-position`은 late injection 완료 후 `#workspace-competitor-position` wrapper로 합친다.
- `#map-card`는 기존 Strategy/Search 역할분리 계약대로 Strategy에서 hidden 상태를 유지하고 왼쪽 메뉴에서도 제외한다.
- `market-funding-competition`은 시장 전체 수신흐름 strip만 기본 노출하고 기관 4분면/성장랭킹은 숨긴다.
- TOP5 visible summary는 순위/업권/금융사·상품/최고금리로 축소한다.
- 시뮬레이터의 event-direction tile은 숨긴다.
- `#relative-pricing-r1`과 `#rate-funding-matrix`는 계산/payload를 유지하되 기본 화면에서는 숨긴다.
- 왼쪽 메뉴는 final DOM 기준으로 다시 만들며 `데이터 근거 · 품질`은 메뉴에서 제외한다.
- 신규 finalizer가 production-data browser E2E를 자동으로 타도록 관련 workflow path filter를 보강한다.
