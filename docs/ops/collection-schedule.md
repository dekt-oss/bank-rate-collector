# Production collection schedule

> 상태: **운영 기준표 (maintained operational reference)**  
> 최종 대조 기준: `main@3fae3d1a1e6fb9612483aa4bcd2d641d3955c7c3` / 2026-09-16  
> 실행 계약의 최종 Source of Truth는 `.github/workflows/*.yml`이다. 이 문서는 사람이 한눈에 운영 일정을 확인하는 기준표이며, **cron 변경 PR은 이 문서와 관련 회귀테스트를 같은 PR에서 함께 수정해야 한다.**

## 1. 핵심 운영 스케줄

모든 표기 시각은 **KST(Asia/Seoul)** 기준이다. GitHub Actions cron은 UTC이므로 KST 날짜와 UTC 요일이 다를 수 있다.

| KST 예약 시각 | KST 실행일 / 귀속 cycle | GitHub UTC cron | Workflow | 주요 수집 대상 | canonical writer | 운영 목적 |
|---|---|---|---|---|---|---|
| **전날 17:30** | 일~목 → 다음 영업일(월~금) morning cycle | `30 8 * * 0-4` | `.github/workflows/collect-nh.yml` | 농·축협(`nh_local`) 전국 | `rate-data-writer` | 장시간 NH 수집을 먼저 예약해 다음 영업일 07:30 발행 목표 확보 |
| **전날 17:40** | 일~목 → 다음 영업일(월~금) morning cycle | `40 8 * * 0-4` | `.github/workflows/collect.yml` | 새마을금고(`kfcc`) 전국 | `rate-data-writer` | NH 다음 장시간 지역 수집 lane 예약 |
| **00:15** | 월~금 morning cycle | `15 15 * * 0-4` | `.github/workflows/collect-institution-funding.yml` | Data.go 기관별 수신잔액 | `rate-data-writer` | 전략/자금 데이터 갱신 |
| **01:17** | 월~금 morning cycle | `17 16 * * 0-4` | `.github/workflows/collect.yml` | FINLIFE 시중·저축은행, BOK ECOS, FSB, CU 등 일반 source | `rate-data-writer` | 짧은 core source 수집 및 canonical 발행 |
| **10:00** | 월~금 당일 refresh | `0 1 * * 1-5` | `.github/workflows/collect-savings-fast.yml` | FINLIFE 시중·저축은행 + 저축은행중앙회 | `rate-data-writer` | 장시간 지역수집 없이 공시금리 빠른 재확인 |
| **15:00** | 월~금 당일 refresh | `0 6 * * 1-5` | `.github/workflows/collect-savings-fast.yml` | FINLIFE 시중·저축은행 + 저축은행중앙회 | `rate-data-writer` | 오후 공시금리 빠른 재확인 |
| **매월 2일 01:17** | 월 1회 | `17 16 1 * *` | `.github/workflows/collect-size-peer-total-assets.yml` | Size Peer 총자산 evidence | `rate-data-writer` | 저빈도 재무 공시 evidence 유지 |

### Morning cycle 순서

```text
전날 17:30  NH 전국
     17:40  KFCC 전국
당일 00:15  기관별 수신잔액
     01:17  일반/core 수집
     07:30  정상 publish 목표
     08:00  hard deadline
```

`07:30`은 정상 완료 목표이고 `08:00`은 현재 health/SLA 계약의 hard deadline이다. 단, **GitHub Actions의 cron은 예약 목표 시각이지 실제 시작 보장이 아니다.** scheduler가 지연되면 run의 `created_at`/`run_started_at`은 예약시각보다 늦을 수 있다.

## 2. 왜 NH/KFCC가 전날 17시대로 이동했나

2026-09-10 PR #326의 collection control-plane 정리 과정에서, 장시간 전국 수집을 다음 영업일 아침까지 직렬 처리하기 위해 evening writer lane으로 이동했다.

주요 변경 이력:

| Commit | 변경 |
|---|---|
| `2800390e9a7ee00663e7766ba6909b9ccda14d62` | `ops: move NH collection into evening SLA window` — NH를 전날 17:30 KST로 이동 |
| `454668ef269bf2b3dc1164cea8d12a17d265925a` | `ops: reserve midnight slot for funding refresh` — funding 00:15 lane 예약 |
| `885e8578d355739f16f7b10af4a4ac1d9c993955` | `ops: reserve evening writer lane for morning SLA` |
| `776f8bc02f25e33cb9c62a594b9823a654d636d5` | `ops: move core and KFCC into morning SLA schedule` — KFCC 17:40, core 01:17 계약 정리 |
| `27808ebb8aec9093dcd36d461ab62c8f1fb5598f` | `ops: avoid top-of-hour core schedule contention` |
| `c1c20020e2b40c0d9a58a6d1c0d6759635946b8d` | 07:30 이전 4.5시간 scheduler-delay budget 회귀테스트 추가 |

GitHub history상 위 커밋의 author/committer는 저장소 계정 **`dekt-oss`** 이며, PR #326으로 `main`에 반영됐다. 이 문서는 특정 사람의 의도를 추정하지 않고 Git 기록에 남은 변경만 기록한다.

## 3. 재시도·복구·감시 트리거

아래 workflow는 정시 cron 자체가 아니라 수집 결과나 운영자 요청에 반응한다.

| Workflow | Trigger | 역할 |
|---|---|---|
| `.github/workflows/recover-failed-scheduled-collection.yml` | 정기 수집 `workflow_run` 완료 후 | 실패/soft-failure로 판정된 정기 source를 1회 복구. 이미 정상인 source를 무조건 재수집하지 않음 |
| `.github/workflows/source-health-watch.yml` | NH/KFCC/core 수집 완료 `workflow_run`, 또는 수동 | canonical DB를 read-only로 점검하고 source health 이슈를 동기화. 자체 재수집은 하지 않음 |
| `.github/workflows/recover-stale-collections.yml` | 수동, 또는 명시적 `[recover-stale]` main push | 누락된 일반 → KFCC → NH 수집을 직렬 dispatch하는 운영 복구 오케스트레이터 |

NH/KFCC checkpoint 정책은 2026-09-16 PR #333 이후 다음과 같다.

- **새 scheduled cycle의 첫 시도:** `fresh`
- **같은 실행 안의 후속 retry/recovery:** `auto`
- 목적: 전날 `complete` checkpoint를 다음 날 새 cycle로 잘못 재생하지 않으면서, 현재 cycle에서 이미 받은 장시간 수집 진척은 보존한다.

## 4. 현재 알려진 운영 리스크 / drift

### 4.1 GitHub scheduler 지연

GitHub cron은 정확한 실행시각을 보장하지 않는다. 실제 운영에서 수시간 지연이 관측됐다. 따라서 위 표의 시각은 **target/enqueue schedule**이며 `17:30에 실제 collector 프로세스가 반드시 시작된다`는 보장이 아니다.

운영 확인 시에는 반드시 다음을 구분한다.

1. 예정 cron 시각
2. GitHub run `created_at`
3. 실제 job `run_started_at`
4. collector 시작/종료
5. canonical publish 완료

정기 run 자체가 생성되지 않은 경우에는 실패 run도 없으므로 `workflow_run` 기반 복구가 작동할 사건이 없다는 점도 별도 보완 대상이다.

### 4.2 `/api/health` schedule contract drift — 2026-09-16 기준 미해결

`web/api/health.js`의 schedule 판정은 아직 과거 slot(`core 00:17`, `NH 00:37`, `KFCC 04:17`)을 기준으로 하는 코드가 남아 있다. 현재 실제 workflow의 `NH 17:30 / KFCC 17:40 / core 01:17`과 일치하지 않는다.

따라서 schedule health/SLA를 수정할 때는 단순 시각 숫자만 바꾸지 말고 **전날 저녁 NH/KFCC run을 다음 영업일 morning cycle에 귀속하는 business-cycle attribution**까지 함께 수정해야 한다.

이 drift가 해결되기 전에는 `/api/health`의 schedule 누락/지연 판정을 실제 workflow run과 대조해 해석한다.

## 5. 스케줄 변경 관리 규칙

앞으로 production collection schedule을 바꾸는 PR은 다음을 모두 만족해야 한다.

1. `.github/workflows/*.yml`의 cron과 **이 문서의 KST/UTC 표를 같은 PR에서 수정**한다.
2. UTC ↔ KST 변환과 요일 이동을 명시한다. 특히 전날 UTC/KST가 섞이는 schedule은 다음 영업일 cycle 귀속을 테스트한다.
3. canonical DB/R2를 쓰는 작업은 `rate-data-writer` 충돌과 직렬화 시간을 다시 계산한다.
4. `tests/test_morning_collection_sla.py` 및 schedule 관련 회귀테스트를 갱신한다.
5. schedule 변경이 health 판단에 영향을 주면 `web/api/health.js`와 `tests/test_collection_schedule_health.py`를 **같은 PR**에서 갱신한다.
6. CI 성공만으로 운영 성공을 선언하지 않는다. merge 후 실제 scheduled run의 `created_at`, source 결과, gate, R2/canonical publish를 확인한다.
7. 실제 runtime에서 새 지연 상한이 관측되면 기존 delay budget 가정을 재검토한다. 과거 테스트 숫자를 영구 상수처럼 사용하지 않는다.

## 6. 문서 범위

이 문서는 **Production 데이터 수집 및 직접 연결된 복구/감시 일정**을 관리한다.

- 포함: canonical 금리/자금/Size Peer 수집, 정기 refresh, 직접 복구·health trigger
- 제외: CI, PR 전용 E2E, 일회성 recon/evidence workflow, 운영자 승인형 maintenance workflow

새 production schedule을 추가할 때는 이 표에도 반드시 추가한다.
