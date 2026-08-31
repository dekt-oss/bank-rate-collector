# 구현 기준 문서

```
제품·화면·우선순위:
docs/specs/20260806-rate-monitor-v4.md

최신 공통 헤더·지도 가독성 UI 결정:
docs/specs/20260820-dashboard-shared-header-map-readability-v1.md

전략 대시보드 병렬 실험:
docs/specs/20260812-strategy-dashboard-v1.md

데이터 계약·식별체계·스냅샷·게이트:
docs/specs/20260805-rate-monitor-v3.1.md

현재 안정화 작업 범위:
docs/specs/20260810-stabilization-v1.md

두 기준 문서가 부딪히면:
화면·우선순위는 v4, 나머지는 v3.1

전략 대시보드 문서는 현행 검색·조회 화면을 대체하지 않고 별도 화면의
실험 범위만 정한다.

안정화 문서는 위 기준을 대체하지 않고,
실제 확인된 오류·운영 리스크를 고치는 현재 작업 범위만 정한다.
```

v4는 v3.1을 **폐기하지 않는다.** 아키텍처를 상속하고 제품 우선순위만
바꾼다. v3.1을 `superseded`로 적으면 데이터 계약이 갈 곳이 없어진다.

`20260820-dashboard-shared-header-map-readability-v1.md`는 사용자가 승인한 최신
화면 결정으로, 검색/Strategy의 공통 제품 헤더와 검색 권역 지도의 직접
`지역명 + 금리` 비교 방식을 정의한다. 금리 계산·수집·데이터 계약은 바꾸지 않는다.

`20260812-strategy-dashboard-v1.md`는 `index.html`의 검색·조회 계약을 유지한 채
같은 발행 데이터로 경쟁사 현황·시장 변화·신상품 금리 시나리오를 제공하는
`strategy.html` 실험을 정의한다. 안정화 전에는 메인 진입점으로 바꾸지 않는다.

`20260810-stabilization-v1.md`도 v4/v3.1을 대체하지 않는다. 기존 구조와
계약을 유지한 채 Partial Collection Gate, 행정구역 정규화, 이자방식 의미,
warning 관측성, source freshness, 업권 용어를 안정화하는 작업 범위다.

---

## 다음 설계 리뷰 — 상대금리 기반 목표형 시뮬레이터

아래 문서는 **구현 완료 문서가 아니라 `draft_for_review`**다. 기존 Public Structural v2와
private calibration 계약을 대체하지 않으며, Claude 설계 리뷰와 사용자 승인 전에는
새 구현 기준으로 승격하지 않는다.

- 기획: [`../plans/20260831-relative-rate-goal-simulator-plan.md`](../plans/20260831-relative-rate-goal-simulator-plan.md)
- 작업지시서: [`../plans/20260831-relative-rate-goal-simulator-work-order.md`](../plans/20260831-relative-rate-goal-simulator-work-order.md)
- Claude 리뷰 프롬프트: [`../reviews/20260831-relative-rate-goal-simulator-claude-review-prompt.md`](../reviews/20260831-relative-rate-goal-simulator-claude-review-prompt.md)

핵심 경계는 다음과 같다.

```text
현재 / 내부자료 미보정
= factual Relative Market Simulator
= 목표 수신 기반 권장금리 출력 금지

향후 / private calibrated champion 승인 후
= Goal-based inverse simulator
= 목표 수신 → 검증된 필요금리 범위 + What-if
```

---

## 문서 목록

| 문서 | 상태 | 비고 |
|---|---|---|
| [`20260823-public-structural-v2-g-factual-rate-finder.md`](20260823-public-structural-v2-g-factual-rate-finder.md) | **implemented/complete** | Stage G competitor-only 시장 benchmark와 factual-only 조건충족 금리 finder 계약. #169 완료 / #181 최종 QA 통과 |
| [`20260822-public-structural-v2-decision-cockpit-final.md`](20260822-public-structural-v2-decision-cockpit-final.md) | **implemented/complete** | #170 리뷰 반영 최종안. Stage A0~J 구현·실데이터 QA 완료, Issue #169 completed |
| [`20260820-dashboard-shared-header-map-readability-v1.md`](20260820-dashboard-shared-header-map-readability-v1.md) | **implementation/current-work** | 검색/Strategy 공통 헤더 + 검색 권역 지도 직접 `지역명 + 금리` 표시. 계산·수집 계약 불변 |
| [`20260817-mutual-finance-stage-g-entry-census.md`](20260817-mutual-finance-stage-g-entry-census.md) | **decision/evidence-gate** | 최신 전국 공식 raw 전수 census. NH local G2는 ENTRY GO, KFCC G1은 deterministic official-site linkage 부재로 BLOCKED 유지 |
| [`20260817-mutual-finance-max-rate-stage-f-evidence.md`](20260817-mutual-finance-max-rate-stage-f-evidence.md) | **decision/evidence-gate** | 상호금융 최고금리 Stage F source evidence. CU GO, KFCC/NH conditional evidence |
| [`20260817-mutual-finance-max-rate-claude-review.md`](20260817-mutual-finance-max-rate-claude-review.md) | **work-order/review** | 상호금융 최고금리 F→G→H staged work order와 canonical/shared-contract 검증 규칙 |
| [`20260817-strategy-stable-product-id.md`](20260817-strategy-stable-product-id.md) | **implementation** | 상호금융 strategy display-key 충돌을 stable `product_id` 직접 전달로 해소. public table 계약 보존 |
| [`20260817-strategy-mutual-finance-evidence.md`](20260817-strategy-mutual-finance-evidence.md) | **decision/evidence-gate** | 상호금융 전략 확장 전 최고금리·지역·coverage·identity Evidence Gate |
| [`20260817-strategy-dashboard-issue108-ux.md`](20260817-strategy-dashboard-issue108-ux.md) | **implementation** | Issue #108 요구 1·2: 기타 원문 drill-down·인사이트 선배치·전국 지도/TOP5 밀도 축소 |
| [`20260816-strategy-dashboard-v2-workorder.md`](20260816-strategy-dashboard-v2-workorder.md) | **draft/work-order** | 2026-08-16 설계 리뷰 반영 개선판 작업 명세. Stage A~E 순서와 인터페이스 계약 |
| [`20260816-inflow-prediction-v1.md`](20260816-inflow-prediction-v1.md) | **experimental** | 수신금액 예측엔진 v1 구조모형. 계수는 내부 실적 미보정 스트레스 밴드 |
| [`20260816-inflow-prediction-v1-evidence.md`](20260816-inflow-prediction-v1-evidence.md) | evidence_note | 예측엔진 근거와 가정 경계. 외부 연구 인용 범위 구분 |
| [`20260812-strategy-dashboard-v1.md`](20260812-strategy-dashboard-v1.md) | **experimental/current-work** | 현행 검색·조회 화면 보존 + 별도 전략 대시보드/시뮬레이션 실험 |
| [`20260810-stabilization-v1.md`](20260810-stabilization-v1.md) | **planned/current-work** | 2026-08-10 감사에서 확인된 오류·운영 리스크 안정화. P0/P1 최소 범위 |
| [`20260806-rate-monitor-v4.md`](20260806-rate-monitor-v4.md) | **current** | 제품·화면·우선순위. 메인 4업권 + 참고지표 |
| [`20260806-storage-prerequisite-v1.md`](20260806-storage-prerequisite-v1.md) | partially_implemented | 저장소·이력 보관. PR 1·2 완료, 3~5 미착수 |
| [`20260806-preference-conditions-v1.md`](20260806-preference-conditions-v1.md) | partially_implemented | §5 분류·§7 판정은 구현. `preference_conditions` 테이블(조건별 쪼개기)과 §10 관리자 화면은 미착수 |
| [`20260805-rate-monitor-v3.1.md`](20260805-rate-monitor-v3.1.md) | **architecture-base** | 데이터 계약·식별체계·게이트의 기준 |
| [`20260805-rate-monitor-v3.md`](20260805-rate-monitor-v3.md) | superseded | 새마을금고 독립 수집모델. 실행 모델이 로컬 FastAPI 전제 |
| [`20260805-rate-monitor-v2.md`](20260805-rate-monitor-v2.md) | superseded | SQLite 기반 재설계 |
| [`20260805-rate-monitor.md`](20260805-rate-monitor.md) | superseded | v1. JSON 스냅샷 기반 |

기획 문서: [`../plans/20260805-rate-monitor-plan-v3.md`](../plans/20260805-rate-monitor-plan-v3.md)
남은 작업: [`../roadmap.md`](../roadmap.md)

데이터를 업무 근거로 쓰는 사람에게 주는 문서: [`../data-trust.md`](../data-trust.md)
— 무엇이 보장되고 무엇이 보장되지 않는지, 이렇게 말하면 안 되는 것이 무엇인지.
화면 하단에서도 이 문서로 간다.

## 설정 파일

| 파일 | 무엇을 정하나 |
|---|---|
| `config/presentation.yaml` | 메인 4업권과 참고지표를 가른다 (v4 §9.1) |
| `config/storage.yaml` | 상태 DB를 어디에 두는가 (github_legacy / r2_migration / r2) |
| `config/regions.yaml` | 수집 범위 (전국·부산·수도권) |
| `config/preference_rules.yaml` | 우대조건 원문을 표준 분류로 옮기는 규칙 |

## 정찰 기록

| 문서 | 대상 | 수집기 |
|---|---|---|
| [`../source-recon/finlife.md`](../source-recon/finlife.md) | 금융감독원 오픈API | 있음 |
| [`../source-recon/fsb.md`](../source-recon/fsb.md) | 저축은행중앙회 | 있음 |
| [`../source-recon/kfcc.md`](../source-recon/kfcc.md) | 새마을금고 | 있음 |
| [`../source-recon/cu.md`](../source-recon/cu.md) | 신협중앙회 | 있음 |
| [`../source-recon/nh-local.md`](../source-recon/nh-local.md) | 지역농축협 | **없음** — §0 정정 참고 |
| [`../third-party/kfcc-reference.md`](../third-party/kfcc-reference.md) | 참고 저장소 `if1live/shiroko-kfcc` | 검증용 |

`nh-local.md`는 §1에서 "중앙 수집 불가"라고 단정했다가 §0에서 정정됐다.
농협 금융상품몰에 농·축협별 예금금리 화면이 실재한다. 정확한 HTTP 계약은
아직 모른다.

## 규칙

- 계약 변경은 코드로 우회하지 않는다. 문서를 먼저 고치고 구현한다.
- v1~v3는 수정하지 않는다. 설계 경위를 남기기 위해 보존한다.
- 정찰 기록도 지우지 않는다. 틀린 판정은 **정정 절을 앞에 붙이고 원문을
  남긴다** — 지운 자리에는 같은 실수를 다시 하게 된다.
- 기준 문서가 바뀌면 이 표와 각 문서의 `status` 메타를 함께 갱신한다.
- 안정화 작업은 `20260810-stabilization-v1.md`의 Task Boundary와 PR 분리 계획을 따른다.

## 뒤집힌 결정

판정이 바뀌어도 원문은 남긴다. 어디를 봐야 경위를 아는지만 여기 적는다.

| 날짜 | 무엇 | 어디에 |
|---|---|---|
| 2026-08-06 | 시중은행을 메인 비교표에 넣는다 (사용자 결정) | v4 §6.4 정정 절, §6.5, §17 |
