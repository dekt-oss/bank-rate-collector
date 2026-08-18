# Stage B — Rate-to-Inflow Decision Cockpit 구현 기록

- Date: 2026-08-18
- Base: `main` (`f4b61cf135fb199598924f658b24a555dc582156`)
- Related: Issue #108, `20260818-deposit-pricing-decision-cockpit-v3.md`
- Production Strategy Release Gate: **OFF 유지**

## 목표

Strategy의 금리결정 영역을 순위 중심이 아니라 다음 질문 중심으로 재배치한다.

> 현재 금리에서 예상되는 신규자금·재예치는 얼마이며, 금리를 +5/+10/+15bp 또는 현재 제안금리로 바꾸면 총수신과 추가 표면이자비용은 어떻게 달라지는가?

## 범위

- 기존 `predictInflow()` / Python parity 계약 재사용
- 현재 / +5bp / +10bp / +15bp / 현재 제안금리 비교
- 예상 신규자금, 예상 재예치, 예상 총수신, 현재 대비 증감, 추가 표면이자비용 표시
- 기존 순위·상위 10%·포지션은 접힌 참고정보로 하향
- prediction panel 기본 노출
- `uncalibrated` 경고를 전면 표시

## 명시적 비범위

- 예측계수 변경 또는 고려저축은행 실적 보정
- `순수신` 예측
- FTP 반영 비용계산
- 내부자료 적재/스키마 변경
- 시장이력 확장(Stage C)
- 우대조건 효과 보정(Stage D/E)
- Strategy Release Gate ON

## 해석 계약

현재 엔진의 `predicted_total`은 **신규자금 + 재예치**이며 순수신이 아니다.
Stage B에서는 이를 `예상 총수신`으로만 표시한다.

현재 비용은 단순 표면이자 차이이며 **FTP 미반영**이다.

현재 계수는 내부 실적 미보정 stress assumption이므로 실제 forecast로 표현하지 않는다.

## 구현 방식

Strategy 템플릿 원본을 대규모 재작성하지 않는다.
`strategy_decision_cockpit.py`가 Strategy 빌드 산출물에 presentation CSS/JS를 idempotent하게 주입하고, `site_service.py`는 Strategy ON 렌더 경로에서만 이를 호출한다.

따라서 Gate OFF의 메인 빌드/산출물 삭제 계약은 기존대로 유지된다.
