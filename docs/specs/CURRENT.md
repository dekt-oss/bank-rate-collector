# 구현 기준 문서

```
제품·화면·우선순위:
docs/specs/20260806-rate-monitor-v4.md

데이터 계약·식별체계·스냅샷·게이트:
docs/specs/20260805-rate-monitor-v3.1.md

두 문서가 부딪히면:
화면·우선순위는 v4, 나머지는 v3.1
```

v4는 v3.1을 **폐기하지 않는다.** 아키텍처를 상속하고 제품 우선순위만
바꾼다. v3.1을 `superseded`로 적으면 데이터 계약이 갈 곳이 없어진다.

---

## 문서 목록

| 문서 | 상태 | 비고 |
|---|---|---|
| [`20260806-rate-monitor-v4.md`](20260806-rate-monitor-v4.md) | **current** | 제품·화면·우선순위. 메인 4업권 + 참고지표 |
| [`20260806-storage-prerequisite-v1.md`](20260806-storage-prerequisite-v1.md) | partially_implemented | 저장소·이력 보관. PR 1·2 완료, 3~5 미착수 |
| [`20260806-preference-conditions-v1.md`](20260806-preference-conditions-v1.md) | accepted_not_started | 우대조건 표준화·분류. 착수 전 결정 셋이 문서 머리에 있다 |
| [`20260805-rate-monitor-v3.1.md`](20260805-rate-monitor-v3.1.md) | **architecture-base** | 데이터 계약·식별체계·게이트의 기준 |
| [`20260805-rate-monitor-v3.md`](20260805-rate-monitor-v3.md) | superseded | 새마을금고 독립 수집모델. 실행 모델이 로컬 FastAPI 전제 |
| [`20260805-rate-monitor-v2.md`](20260805-rate-monitor-v2.md) | superseded | SQLite 기반 재설계 |
| [`20260805-rate-monitor.md`](20260805-rate-monitor.md) | superseded | v1. JSON 스냅샷 기반 |

기획 문서: [`../plans/20260805-rate-monitor-plan-v3.md`](../plans/20260805-rate-monitor-plan-v3.md)
남은 작업: [`../roadmap.md`](../roadmap.md)

## 설정 파일

| 파일 | 무엇을 정하나 |
|---|---|
| `config/presentation.yaml` | 메인 4업권과 참고지표를 가른다 (v4 §9.1) |
| `config/storage.yaml` | 상태 DB를 어디에 두는가 (github_legacy / r2_migration / r2) |
| `config/regions.yaml` | 수집 범위 (전국·부산·수도권) |

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
