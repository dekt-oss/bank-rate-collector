# Production collection schedule

> 상태: **운영 기준표 (maintained operational reference)**  
> 최종 대조 기준: `main@3fae3d1a1e6fb9612483aa4bcd2d641d3955c7c3` / 2026-09-16  
> 실행 계약의 최종 Source of Truth는 `.github/workflows/*.yml`이다. 이 문서는 사람이 한눈에 운영 일정을 확인하는 기준표이며, **cron 변경 PR은 이 문서와 관련 회귀테스트를 같은 PR에서 함께 수정해야 한다.**

## 1. 핵심 운영 스케줄

모든 표기 시각은 **KST(Asia/Seoul)** 기준이다. GitHub Actions cron은 UTC이므로 KST 날짜와 UTC 요일이 다를 수 있다.

> **중요: `Action 예약 시각`과 `실제 수집 시각`은 같은 개념이 아니다.**  
> `Action 예약 시각`은 GitHub scheduler가 workflow run 생성을 시도하는 cron 목표 시각이다.  
> `실제 수집 시각`은 run이 생성되고 writer queue를 통과한 뒤 실제 collector가 원천 데이터를 읽기 시작해서 끝나는 시각이며, 매 실행마다 달라진다. 따라서 아래 cron 시각을 실제 데이터 수집 시작 시각으로 해석하면 안 된다.

| Action 예약 시각(KST) | 실제 수집 시각 | KST 실행일 / 귀속 cycle | GitHub UTC cron | Workflow | 주요 수집 대상 | canonical writer | 운영 목적 |
|---|---|---|---|---|---|---|---|
| **전날 17:30** | **가변** — run 생성·queue 대기 후 collector 시작/종료 시각을 runtime evidence로 확인 | 일~목 → 다음 영업일(월~금) morning cycle | `30 8 * * 0-4` | `.github/workflows/collect-nh.yml` | 농·축협(`nh_local`) 전국 | `rate-data-writer` | 장시간 NH 수집을 먼저 예약해 다음 영업일 07:30 발행 목표 확보 |
| **전날 17:40** | **가변** — NH 등 선행 writer가 끝난 뒤 시작될 수 있음. 실제 collector 시작/종료를 확인 | 일~목 → 다음 영업일(월~금) morning cycle | `40 8 * * 0-4` | `.github/workflows/collect.yml` | 새마을금고(`kfcc`) 전국 | `rate-data-writer` | NH 다음 장시간 지역 수집 lane 예약 |
| **00:15** | **가변** — writer queue 통과 후 실제 수집 시작 | 월~금 morning cycle | `15 15 * * 0-4` | `.github/workflows/collect-institution-funding.yml` | Data.go 기관별 수신잔액 | `rate-data-writer` | 전략/자금 데이터 갱신 |
| **01:17** | **가변** — 앞선 NH/KFCC/funding writer 상태에 따라 실제 시작이 늦어질 수 있음 | 월~금 morning cycle | `17 16 * * 0-4` | `.github/workflows/collect.yml` | FINLIFE 시중·저축은행, BOK ECOS, FSB, CU 등 일반 source | `rate-data-writer` | 짧은 core source 수집 및 canonical 발행 |
| **10:00** | **가변** — run/job/collector 실제 시작·종료 시각으로 판정 | 월~금 당일 refresh | `0 1 * * 1-5` | `.github/workflows/collect-savings-fast.yml` | FINLIFE 시중·저축은행 + 저축은행중앙회 | `rate-data-writer` | 장시간 지역수집 없이 공시금리 빠른 재확인 |
| **15:00** | **가변** — run/job/collector 실제 시작·종료 시각으로 판정 | 월~금 당일 refresh | `0 6 * * 1-5` | `.github/workflows/collect-savings-fast.yml` | FINLIFE 시중·저축은행 + 저축은행중앙회 | `rate-data-writer` | 오후 공시금리 빠른 재확인 |
| **매월 2일 01:17** | **가변** — writer queue 통과 후 실제 총자산 evidence 수집 시작 | 월 1회 | `17 16 1 * *` | `.github/workflows/collect-size-peer-total-assets.yml` | Size Peer 총자산 evidence | `rate-data-writer` | 저빈도 재무 공시 evidence 유지 |

### 1.1 시간 정의

운영 화면·장애 분석·사후 보고에서는 아래 시간을 섞지 않는다.

| 구분 | 의미 | 확인 기준 |
|---|---|---|
| **Action 예약 시각** | workflow YAML의 cron이 의도한 예약 목표 시각 | `.github/workflows/*.yml`의 `schedule.cron` |
| **Action run 생성 시각** | GitHub가 실제 workflow run 객체를 만든 시각 | Actions run의 `created_at` |
| **Job 실제 시작 시각** | runner가 배정되어 job이 실제 시작한 시각 | Actions job/run의 `run_started_at` / `started_at` |
| **실제 수집 시작 시각** | collector가 원천기관/API/웹에 실제 요청을 시작한 시각 | collector 로그 또는 source-specific runtime evidence |
| **실제 수집 종료 시각** | 해당 source의 원천 수집·파싱이 끝난 시각 | collector 로그 / source result |
| **canonical 반영 완료 시각** | gate 통과 후 DB/R2/current snapshot 발행이 완료된 시각 | publish/upload 로그 및 canonical readback |

즉, 예를 들어 **`NH 전날 17:30`은 Action 예약 시각이지 `17:30에 NH 데이터 수집이 시작된다`는 뜻이 아니다.** `rate-data-writer` queue나 GitHub scheduler 지연 때문에 실제 수집은 그보다 늦게 시작할 수 있다.

### 1.2 Morning cycle — 예약 기준과 실제 실행 기준

```text
[Action 예약 기준]
전날 17:30  NH workflow 예약
     17:40  KFCC workflow 예약
당일 00:15  기관별 수신잔액 workflow 예약
     01:17  일반/core workflow 예약
     07:30  정상 publish 목표
     08:00  hard deadline

[실제 실행 기준]
run created_at
  -> writer queue 대기
  -> job run_started_at
  -> collector 실제 수집 시작
  -> collector 실제 수집 종료
  -> gate 검증
  -> canonical publish 완료
```

`07:30`은 정상 완료 목표이고 `08:00`은 현재 health/SLA 계약의 hard deadline이다. **GitHub Actions의 cron은 Action 예약 목표 시각이지 실제 수집 시작 보장이 아니다.** scheduler 또는 `rate-data-writer` queue가 지연되면 `created_at`, `run_started_at`, 실제 collector 시작 시각이 모두 예약시각보다 늦을 수 있다.

## 2. 왜 NH/KFCC가 전날 17시대로 이동했나

2026-09-10 PR #326의 collection control-plane 정리 과정에서, 장시간 전국 수집을 다음 영업일 아침까지 직렬 처리하기 위해 evening writer lane으로 이동했다.

주요 변경 이력:

| Commit | 변경 |
|---|---|
| `2800390e9a7ee00663e7766ba6909b9ccda14d62` | `ops: move NH collection into evening SLA window` — NH **Action 예약 시각**을 전날 17:30 KST로 이동 |
| `454668ef269bf2b3dc1164cea8d12a17d265925a` | `ops: reserve midnight slot for funding refresh` — funding Action 예약 00:15 lane 설정 |
| `885e8578d355739f16f7b10af4a4ac1d9c993955` | `ops: reserve evening writer lane for morning SLA` |
| `776f8bc02f25e33cb9c62a594b9823a654d636d5` | `ops: move core and KFCC into morning SLA schedule` — KFCC 예약 17:40, core 예약 01:17 계약 정리 |
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

### 4.1 GitHub scheduler / writer queue 지연

GitHub cron은 정확한 실행시각을 보장하지 않는다. 또한 이 저장소의 canonical writer들은 `rate-data-writer`로 직렬화되어 있어 앞선 writer가 길어지면 뒤 run은 생성돼도 실제 job/collector 시작은 늦어질 수 있다.

따라서 장애 분석에서는 반드시 다음을 순서대로 기록한다.

1. **Action 예약 시각** — cron target
2. **Action run 생성 시각** — `created_at`
3. **Job 실제 시작 시각** — `run_started_at` / `started_at`
4. **실제 수집 시작 시각** — collector runtime evidence
5. **실제 수집 종료 시각** — collector runtime evidence
6. **canonical publish 완료 시각** — DB/R2/current snapshot 반영

**예약 시각 ≠ 실제 수집 시각**이다. 운영 보고서에는 `17:30 수집`처럼 쓰지 않고, `17:30 Action 예약 / 실제 수집 HH:MM~HH:MM`처럼 구분해 기록한다.

정기 run 자체가 생성되지 않은 경우에는 실패 run도 없으므로 `workflow_run` 기반 복구가 작동할 사건이 없다는 점도 별도 보완 대상이다.

### 4.2 `/api/health` schedule contract drift — 2026-09-16 기준 미해결

`web/api/health.js`의 schedule 판정은 아직 과거 slot(`core 00:17`, `NH 00:37`, `KFCC 04:17`)을 기준으로 하는 코드가 남아 있다. 현재 실제 workflow의 **Action 예약 시각**인 `NH 17:30 / KFCC 17:40 / core 01:17`과 일치하지 않는다.

따라서 schedule health/SLA를 수정할 때는 단순 시각 숫자만 바꾸지 말고 **전날 저녁 NH/KFCC run을 다음 영업일 morning cycle에 귀속하는 business-cycle attribution**과 **예약 시각/실제 수집 시각의 분리**까지 함께 반영해야 한다.

이 drift가 해결되기 전에는 `/api/health`의 schedule 누락/지연 판정을 실제 workflow run과 collector runtime evidence를 대조해 해석한다.

## 5. 스케줄 변경 관리 규칙

앞으로 production collection schedule을 바꾸는 PR은 다음을 모두 만족해야 한다.

1. `.github/workflows/*.yml`의 cron과 **이 문서의 Action 예약 시각 KST/UTC 표를 같은 PR에서 수정**한다.
2. UTC ↔ KST 변환과 요일 이동을 명시한다. 특히 전날 UTC/KST가 섞이는 schedule은 다음 영업일 cycle 귀속을 테스트한다.
3. 문서·UI·health에서 **Action 예약 시각과 실제 수집 시각을 별도 필드/개념으로 유지**한다.
4. canonical DB/R2를 쓰는 작업은 `rate-data-writer` 충돌과 직렬화 시간을 다시 계산한다.
5. `tests/test_morning_collection_sla.py` 및 schedule 관련 회귀테스트를 갱신한다.
6. schedule 변경이 health 판단에 영향을 주면 `web/api/health.js`와 `tests/test_collection_schedule_health.py`를 **같은 PR**에서 갱신한다.
7. CI 성공만으로 운영 성공을 선언하지 않는다. merge 후 실제 scheduled run의 `created_at`, `run_started_at`, collector 시작/종료, source 결과, gate, R2/canonical publish를 확인한다.
8. 실제 runtime에서 새 지연 상한이 관측되면 기존 delay budget 가정을 재검토한다. 과거 테스트 숫자를 영구 상수처럼 사용하지 않는다.

## 6. 문서 범위

이 문서는 **Production 데이터 수집 및 직접 연결된 복구/감시 일정**을 관리한다.

- 포함: canonical 금리/자금/Size Peer 수집, 정기 refresh, 직접 복구·health trigger
- 제외: CI, PR 전용 E2E, 일회성 recon/evidence workflow, 운영자 승인형 maintenance workflow

새 production schedule을 추가할 때는 이 표에도 반드시 추가한다.
