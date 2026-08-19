# Strategy Decision Workspace UX v1 — 2026-08-19

## 배경

현재 production-data Strategy 화면은 기능적으로는 Stage B/C/D/E0가 모두 표시되지만, 실제 스크린샷 기준으로 각 분석 카드의 위계가 비슷하고 세로 길이가 길다. 특히 모바일은 KPI·원천근거·시장환경·시장변화·우대조건·지도·시뮬레이터가 모두 단일 문서처럼 이어져 금리결정 작업의 시작점이 늦다.

Issue #108의 기존 요구인 `시장 인사이트 선배치`, `전국 지도/TOP5 축소`, `부산 drill-down 가독성 보존`을 현재 Decision/Pricing 방향과 합친다.

## 목표 작업순서

1. **금리 결정** — 현재/제안금리와 +5/+10/+15bp 수신반응을 먼저 비교
2. **시장 근거** — BOK 자금환경, C2 최근 경쟁방향, 63일 시장 추이 확인
3. **상품 설계** — 시장 인사이트와 우대조건 구조 확인
4. **지역·경쟁사 상세** — 전국 지도와 TOP5를 보조근거로 확인

## UX 변경

- `planning-zone`을 시장근거/지도보다 앞에 배치
- 네 영역에 01~04 작업순서 라벨 부여
- 최근 변경 이벤트는 기본 접힘
- D2가 더 풍부한 우대조건 구조를 제공하므로 기존 단순 `우대조건 트렌드` 카드는 접힌 참고영역으로 보존
- 비부산 전국 지도/TOP5 블록 높이 축소
- `busan-focus` 상태에는 축소 CSS를 적용하지 않아 부산 구·군 가독성 보존
- 390px 모바일에서 KPI 4개와 source evidence 4개를 각각 2열로 압축
- 모바일 E0 금리/업권 흐름 카드는 내부 가로 스크롤로 바꾸어 세로 길이 축소
- C2/D2 selector는 모바일에서 한 줄 스크롤형으로 유지

## 변경하지 않는 것

- canonical `max_rate`
- Strategy `strategy_rate_basis`
- stable product identity / source precedence
- NH e-joy base+add linkage
- C1/C2/D1/D2 계산
- inflow prediction coefficient
- E0 external feature 값
- DB/schema/migration
- Production Strategy Release Gate

## 검증 Gate

- Ruff / full pytest / empty DB migration
- current production canonical DB read-only restore
- isolated Strategy build
- existing Strategy desktop/mobile smoke
- external feature populated smoke
- workspace 전용 Chrome smoke
  - DOM 순서: 결정 → 외부환경 → C2 → 시장추이 → 시장인사이트 → D2 → 지도/TOP5
  - 변경 이벤트 기본 접힘
  - 기존 우대요약 기본 접힘
  - desktop 비부산 map stage <= 300px
  - mobile KPI/evidence 2열
  - mobile 비부산 map stage <= 310px
  - page horizontal overflow 없음
- desktop/mobile full-page screenshot artifact 보존

Production Strategy Release Gate는 OFF로 유지한다.
