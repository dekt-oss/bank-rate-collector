# 구현 기준 문서

```
현재 유일한 구현 기준:
docs/specs/20260805-rate-monitor-v3.1.md

v1·v2·v3:
설계 이력이며 신규 구현 기준으로 사용하지 않음
```

---

## 문서 목록

| 문서 | 상태 | 비고 |
|---|---|---|
| [`20260805-rate-monitor-v3.1.md`](20260805-rate-monitor-v3.1.md) | **current** | 유일한 구현 기준 |
| [`20260805-rate-monitor-v3.md`](20260805-rate-monitor-v3.md) | superseded | 새마을금고 독립 수집모델. 실행 모델이 로컬 FastAPI 전제 |
| [`20260805-rate-monitor-v2.md`](20260805-rate-monitor-v2.md) | superseded | SQLite 기반 재설계 |
| [`20260805-rate-monitor.md`](20260805-rate-monitor.md) | superseded | v1. JSON 스냅샷 기반 |

기획 문서: [`../plans/20260805-rate-monitor-plan-v3.md`](../plans/20260805-rate-monitor-plan-v3.md)

## 정찰 기록

| 문서 | 대상 |
|---|---|
| [`../source-recon/finlife.md`](../source-recon/finlife.md) | 금융감독원 오픈API |
| [`../source-recon/kfcc.md`](../source-recon/kfcc.md) | 새마을금고 공식 페이지 |
| [`../third-party/kfcc-reference.md`](../third-party/kfcc-reference.md) | 참고 저장소 `if1live/shiroko-kfcc` |

## 규칙

- 계약 변경은 코드로 우회하지 않는다. v3.1을 먼저 고치고 구현한다.
- v1~v3는 수정하지 않는다. 설계 경위를 남기기 위해 보존한다.
- v3.1을 대체하는 문서가 생기면 이 표와 각 문서의 `status` 메타를 함께 갱신한다.
