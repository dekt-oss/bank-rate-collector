# Review — Strategy Lean IA v3

대상 명세: `docs/specs/20260918-strategy-lean-ia-v3.md`  
리뷰일: 2026-09-18  
판정: **PASS WITH CHANGES**

## 1. 총평

사용자 요구인 "지표 추가보다 감량", "자금환경 최상단", "중복 시장방향 제거",
"Peer 메뉴 anchor 수정", "시장 인사이트/상세 판단요소 제거", "TOP5 가독성 개선 및
기관 수신 포지션과 통합"은 현재 코드 구조와 일치한다.

다만 현재 Strategy는 여러 presentation injector가 DOMContentLoaded 시점에 순차적으로
DOM을 이동/추가하기 때문에, 기존 workspace presentation만 수정하면 late injection이
다시 순서를 깨뜨릴 위험이 있다.

따라서 구현은 **final reconciler** 방식으로 진행한다.

## 2. 필수 보완

### R1. market_changes는 backend/DOM 계약을 유지하고 visible UI만 제거

기존 `renderChangesEnhanced()` 등은 `changes/ups/downs/feed` id를 직접 참조한다.
템플릿에서 DOM을 삭제하면 JS runtime error가 날 수 있다.

결론:

- `strategy.market_changes` payload 유지
- `details.changes` DOM 유지
- 최종 Lean IA에서 `hidden` + CSS suppression
- 화면에는 노출하지 않음

### R2. 저축은행 시장방향/의사결정 메뉴는 injector 자체를 중단

다음 두 presentation은 사용자 요구상 더 이상 필요 없다.

- `inject_strategy_market_direction`
- `inject_strategy_decision_scope_compact`

단순히 숨기기보다 `dashboard_ui_refinement_presentation` compositor에서 더 이상
주입하지 않는다.

`.ux-decision-readiness` 자체는 기존 Strategy UX refinement가 생성하므로
final reconciler에서 visible UI만 숨긴다.

### R3. 시장 인사이트는 이동 위치와 무관하게 제거

`strategy_decision_evidence_refinement`가 `.insightcard`를
`.decision-integrated-insight`로 다른 위치에 이동할 수 있다.

따라서 parent인 `.workspace-insights`만 숨겨서는 부족하다.

최종 reconciler는:

- `.decision-integrated-insight`
- `.workspace-insights .insightcard`

둘 다 제거/숨김 대상으로 잡는다.

### R4. TOP5 + 기관 수신 포지션은 late DOM을 기다린 뒤 통합

`institution-funding-position`은 dashboard refinement에서 뒤늦게 생성된다.
workspace 시점 heading search로 target을 잡으면 다시 틀릴 수 있다.

최종 wrapper:

`#workspace-competitor-position`

wrapper 안에:

1. `.top5-card`
2. `#institution-funding-position`

순으로 이동한다.

MutationObserver 또는 bounded retry로 둘 다 준비된 뒤 합성한다.
왼쪽 메뉴는 wrapper id를 직접 사용한다.

### R5. 지역지도는 hidden primary 밖으로 꺼낸다

기존 decision refinement가 `.workspace-detail.primary`를 hidden 처리한다.
TOP5는 이미 밖으로 이동하지만 지도는 parent와 함께 숨는다.

최종 reconciler에서 `#map-card`를 보조분석 영역으로 이동시켜
`지역별 금리` 기능은 유지한다.

### R6. 자금환경의 범위 축소

`market-funding-competition`의 시장 전체 수신잔액 strip은 기본환경으로 가치가 있다.

반면 같은 카드의:

- 기관별 금리×성장 4분면
- 성장률 ranking

은 아래 `기관 수신 포지션`과 중복도가 높다.

기본 화면에서는 `.funding-analysis-grid` 및 caveat를 숨기고,
시장 전체 수신흐름 strip만 유지한다.

### R7. TOP5는 컬럼을 줄여 가독성을 높인다

TOP5 underlying 계산/rows는 변경하지 않는다.

visible summary는:

- 순위
- 업권
- 금융사 / 상품
- 최고금리

만 남긴다.

기본금리 / 우대폭 컬럼은 summary에서 숨긴다.
폰트·행간을 확대한다.

### R8. 시뮬레이터 event-direction tile도 숨긴다

대표 시장방향을 Market Intelligence snapshot으로 통일한다면
planning strip의 `30일 변경 이벤트 방향`도 핵심 KPI에서 제외해야 한다.

DOM은 유지하되 parent tile을 hidden 처리한다.

### R9. 왼쪽 메뉴는 final DOM 기준으로 다시 생성

기존 `strategy-workspace-nav`는 제거 후 재생성한다.

최종 메뉴:

- 시장 자금환경
- 업권 수신 흐름
- 시장 금리 방향
- 12개월 시장 추이
- 신상품 금리 시뮬레이션
- 경쟁사 · 기관 포지션
- 지역별 금리
- 우대조건 · 상품구조
- 특판 · 시장기회

`데이터 근거 · 품질`은 화면 하단에 유지하되 메뉴에서는 제외한다.
메뉴 자체도 줄이는 방향을 적용한다.

### R10. E2E trigger 보강

신규 finalizer와 compositor 변경이 실제 production-copy browser E2E를 자동으로 타도록
다음 workflow path filter에 신규 파일을 추가한다.

- `strategy-main-runtime-e2e.yml`
- `strategy-ux-production-copy-e2e.yml`

## 3. 비범위 재확인

이번 PR은 다음을 변경하지 않는다.

- market_changes 계산
- Market Intelligence snapshot 계산
- TOP5 ranking population/정렬
- institution funding percentile/direct peer 계산
- source precedence
- identity/dedupe
- 수신예측 계수
- DB/schema/API

## 4. 구현 승인 판정

위 R1~R10을 명세에 반영한 뒤 구현 진행 가능.

구현 성공 기준은 repository CI뿐 아니라 production-data browser E2E와
merge 후 UI-only republish까지 포함한다.
