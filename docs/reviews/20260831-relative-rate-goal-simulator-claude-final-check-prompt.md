# Claude 최종 문서 재검증 프롬프트 — 상대금리 목표형 시뮬레이터

아래 블록만 Claude에 전달한다.

---

`dekt-oss/bank-rate-collector`의 `docs/relative-rate-goal-simulator-20260831` 브랜치를 **최종 문서 재검증만** 해주세요.

원격 branch HEAD를 먼저 직접 확인하고 첫 줄에 SHA를 적으세요.

이번에는 전체 설계를 처음부터 다시 리뷰하지 말고, 직전 재리뷰에서 남긴 다음 항목이 실제로 닫혔는지만 repository Source of Truth와 대조해주세요.

필독:

- `AGENTS.md`
- `docs/specs/CURRENT.md`
- `docs/plans/20260831-relative-rate-goal-simulator-plan.md`
- `docs/plans/20260831-relative-rate-goal-simulator-work-order.md`
- `docs/plans/20260831-relative-rate-goal-simulator-plan-v2.md`
- `docs/plans/20260831-relative-rate-goal-simulator-work-order-v2.md`
- `docs/evidence/20260831-savings-bank-funding-identity-coverage.md`
- `docs/reviews/20260831-relative-rate-goal-simulator-claude-rereview-response.md`

관련 구현 대조:

- `src/rate_monitor/services/rate_funding_matrix_service.py`
- `src/rate_monitor/services/dashboard_service.py`의 source precedence/dedupe path
- `src/rate_monitor/services/institution_funding_direct_peer*.py`
- 현재 Strategy production workflow

검증할 항목:

1. **P0-5 대표금리 이중정의**
   - 기존 Matrix `institution_product_representative_max`는 이번 범위에서 그대로 유지되는가.
   - 신규 pricing 대표금리는 별도 policy id/version으로 병존하도록 명확한가.
   - 두 금리가 다를 때 payload/UI에서 차이를 숨길 수 없도록 fail-closed/라벨 계약이 있는가.
   - 기존 Matrix 계약을 몰래 바꾸라는 지시가 없는가.

2. **P0-6 CURRENT.md 진입경로**
   - CURRENT가 v2를 현행 리뷰 대상으로 가리키는가.
   - v1은 decision trail/superseded로만 가리키는가.

3. **P1-7 v1 정정절**
   - v1 plan/work-order 맨 앞에 정정절이 실제로 추가됐는가.
   - 원문은 보존되면서 잘못된 `Release Gate OFF`, factual cost 재사용 지시가 현행 구현 근거가 아님을 명시하는가.

4. **P1-8 source precedence**
   - 신규 institution rate reduction 계약이 `source_id`, precedence policy, applied flag 또는 동등한 추적수단을 요구하는가.
   - 우선 source가 fallback source에 의해 덮이지 않는 acceptance가 있는가.

5. **추가 hidden coupling**
   - pricing peer row에 `funding_as_of` 계약이 있는가.
   - rate/funding 시점이 다를 때 화면에서 동시점처럼 보이지 않게 하는가.
   - 업권 전체 funding missing이면 aggregate funding scalar가 숨겨지는가.

6. **availability scope**
   - 채움률이 아직 미검증임을 문서가 숨기지 않는가.
   - R0-A2 전 업권별 coverage/provenance 실측이 요구되는가.
   - 결측을 silent nationwide fallback으로 해석하지 않는가.

7. **pricing peer N**
   - NH funding peer N=16을 pricing peer에 복사하지 않는가.
   - pricing peer는 matched eligible institution 전수를 기본으로 하고 N cap을 evidence 이후 옵션으로 두는가.

8. **79/66/13 evidence 검증경로**
   - artifact에서 확인한 `mapped_count/unmapped_count`와 log/published payload의 독립 확인값을 구분했는가.
   - `funding_growth_6m_institutions=66`을 `mapped_count=66` 정의와 동일시하지 않는가.
   - 다음 canonical run에서 mapping coverage를 log/readback으로 재검증 가능하게 하는 후속 acceptance가 있는가.

9. branch diff가 계속 docs-only인지 확인하세요. 코드/DB/workflow/UI 변경이 있으면 반드시 지적하세요.

## 판정 형식

다음 중 하나만 첫 판정으로 주세요.

- `APPROVE FOR IMPLEMENTATION PLANNING`
- `CHANGES REQUIRED`

그 다음:

1. 남은 P0
2. 남은 P1
3. 구현 전에 실제 데이터로 확인해야 하는 미검증 항목
4. 구현 착수 순서가 `R0 evidence/contract → R1 factual`로 안전한지

만 간결하게 적어주세요.

코드 수정, PR 생성, merge는 하지 마세요. 이미 해결된 이전 P0를 새 문제처럼 반복하지 말고, 실제 미해결 연결만 지적하세요.
