# Strategy Light Theme UX v2 — 2026-08-19

## 목적

Strategy Decision Workspace의 작업순서와 계산계약은 유지하고, 장시간 사용하는 금융 실무 화면에 맞게 시각 피로와 정보 대비를 개선한다.

이번 테마는 Databricks의 `Design Beautiful Dashboards in AI/BI`에서 제안한 다음 원칙을 참고한다.

- 최종 사용자가 먼저 찾는 정보를 상단에 두고 위젯 크기로 계층을 만든다.
- 정보밀도가 높은 대시보드는 산세리프 글꼴과 충분한 대비를 우선한다.
- 라이트 모드에서 순수 검정/순수 흰색의 과도한 대비를 피하고 중립 배경과 밝은 surface를 구분한다.
- 60-30-10 원칙으로 canvas/surface·본문/시각화·accent의 역할을 분리한다.
- accent는 선택·필터·핵심상태 등 실제 주의를 끌어야 하는 곳에 제한한다.

참고 URL: https://www.databricks.com/kr/blog/design-beautiful-dashboards-aibi

## 테마 계약

### 60% — neutral canvas / surface

- canvas: `#eef2f5` 계열
- primary card: white
- secondary surface: `#f7f9fb` 계열
- 얇은 cool-gray border와 낮은 shadow만 사용

### 30% — typography / information color

- primary text: `#17232d` 계열의 deep slate
- secondary text: slate gray
- 데이터의 방향성은 muted green / amber / red로 구분
- 지도와 표도 동일한 중립 surface 위에서 읽히도록 재정렬

### 10% — interaction accent

- primary accent: muted blue `#4f6f9f`
- 선택 tab, filter, active 상태, 핵심 focus에만 사용
- 쨍한 blue flood fill은 사용하지 않는다.

## Typography

외부 font CDN 및 font binary를 추가하지 않는다.

기본 stack:

`Pretendard Variable → Pretendard → Noto Sans KR → Apple SD Gothic Neo → Segoe UI → Arial → sans-serif`

숫자/KPI도 monospace 대신 sans-serif를 사용하되 `tabular-nums`, `lining-nums`를 적용한다.

목표:

- 한글 본문 장시간 가독성
- 금리·bp·금액 열 정렬
- 기술 콘솔 같은 monospace 인상을 줄이고 업무용 BI 화면 톤 강화

## 범위

포함:

- Strategy 전용 canvas/card/navigation/pill/control 색상
- KPI·예측·시장환경·C2/D2·지도·TOP5 surface 재정의
- typography / numeric rendering
- desktop/mobile 동일 theme contract

제외:

- 메인 금리 조회 화면
- 계산식 및 prediction coefficient
- canonical `max_rate` / `strategy_rate_basis`
- source precedence / stable identity
- ECOS 및 collector
- DB/schema/migration
- Production Strategy Release Gate ON

## 검증

- Python injection idempotence
- 외부 font/CDN 의존 없음
- Pretendard-first fallback stack
- tabular numeral contract
- production-data Strategy build
- Chrome desktop/mobile computed-style smoke
  - `data-strategy-theme=light-v1`
  - `color-scheme=light`
  - card surface `rgb(255,255,255)`
  - body text `rgb(23,35,45)`
  - KPI font가 monospace가 아님
  - KPI numerals `tabular-nums`
- 기존 Strategy interaction smoke / Busan drill-down 유지
- final production-data desktop/mobile screenshot 육안검토

Production Strategy Release Gate는 계속 OFF로 유지한다.
