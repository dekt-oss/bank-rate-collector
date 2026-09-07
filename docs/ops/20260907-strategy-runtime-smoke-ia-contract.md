# Strategy runtime smoke IA contract — 2026-09-07

PR #304/#305의 현재 production UX는 기존 상세 `금리결정 인사이트`를 TOP5 앞에 직접 노출하지 않는다.

최종 composition의 사용자 순서는 다음과 같다.

1. 최근 30일 시장 방향
2. 의사결정 메뉴/준비도
3. 경쟁사 TOP5
4. 기본 접힘 `세부 인사이트`
5. 상품·우대조건/기획 영역

`세부 인사이트` 내부에는 기존 `.decision-integrated-insight`가 그대로 보존되어야 하며 기본 상태는 닫힘이다. 메뉴 레이블은 `시장 방향 / 경쟁사 TOP5 / 세부 비교 / 자동추천 범위`를 유지한다.

이 변경은 UI를 재배치하지 않고 `scripts/strategy_workspace_smoke.js`가 위 최종 composition 계약을 검증하도록 stale assertion만 갱신한다.
