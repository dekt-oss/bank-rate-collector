# Production collection schedule

> 상태: **운영 기준표 (maintained operational reference)**  
> 기준일: **2026-09-17**  
> 실행 계약의 Source of Truth는 `.github/workflows/*.yml`이다. cron·business-cycle·SLA 판정을 바꾸는 PR은 **이 문서, `web/api/health.js`, 관련 회귀테스트를 같은 PR에서 함께 수정**한다.

## 1. 최종 운영 스케줄

모든 표기 시각은 KST(Asia/Seoul) 기준이다. GitHub Actions cron은 UTC다.

| Action 예약 시각 | 실제 수집 시각 | 귀속 cycle | UTC cron | Workflow | 대상/역할 |
|---|---|---|---|---|---|
| **전날 14:50** | **20:45 KST 이후**. 예약 run이 늦게 생성되면 생성 즉시 | 일~목 예약 → 다음 영업일 월~금 morning cycle | `50 5 * * 0-4` | `.github/workflows/collect-morning-cycle.yml` | morning control plane: NH → 기관별 수신잔액 → 일반+KFCC |
| **10:00** | 가변 | 월~금 당일 refresh | `0 1 * * 1-5` | `.github/workflows/collect-savings-fast.yml` | FINLIFE/저축은행중앙회 fast refresh |
| **15:00** | 가변 | 월~금 당일 refresh | `0 6 * * 1-5` | `.github/workflows/collect-savings-fast.yml` | 오후 fast refresh |
| **매월 2일 01:17** | 가변 | 월 1회 | `17 16 1 * *` | `.github/workflows/collect-size-peer-total-assets.yml` | Size Peer 총자산 evidence |

Morning child workflow인 `.github/workflows/collect-nh.yml`, `.github/workflows/collect-institution-funding.yml`, `.github/workflows/collect.yml`은 각각의 production 정기 cron을 갖지 않는다. 이들은 `workflow_call`/수동 실행용 canonical writer로 남고 morning parent가 순서를 고정한다.

### 시간 정의

- **Action 예약 시각**: YAML cron이 의도한 scheduler target.
- **Action run 생성 시각**: GitHub가 run 객체를 실제 생성한 `created_at`.
- **Job 실제 시작 시각**: runner가 job을 시작한 `run_started_at` / job `started_at`.
- **실제 수집 시작 시각**: collector가 원천기관/API/웹 요청을 시작한 시각.
- **실제 수집 종료 시각**: 해당 source 수집·파싱 완료 시각.
- **canonical 반영 완료 시각**: validation/gate를 통과하고 R2/current snapshot/rate-data 반영을 끝낸 시각.

**예약 시각 ≠ 실제 수집 시각**이다. `전날 14:50`은 데이터를 14:50에 읽는다는 뜻이 아니다. Morning parent가 일찍 생성되면 gate에서 기다렸다가 **실제 수집 시작 하한 20:45 KST** 이후에만 NH 원천 요청을 시작한다.

## 2. Morning cycle 실행 순서

```text
전날 14:50  GitHub Action 예약
      │
      ├─ run이 20:45 전에 생성됨 → gate에서 20:45까지 대기
      └─ run이 20:45 이후 생성됨 → 즉시 release
      │
      ▼
20:45+  NH 전국
      │ success
      ▼
        Data.go 기관별 수신잔액 incremental
      │ success
      ▼
        일반 source + KFCC 전국
        └─ 한 writer pass에서 snapshot / validate / dashboard / P1-A /
           size / volume / R2 / rate-data publish
      │
      ▼
07:30   정상 완료 목표
08:00   hard deadline
```

각 child는 기존 `rate-data-writer`, `queue: max`, `cancel-in-progress: false` 계약을 유지한다. Parent의 `morning-sla-cycle` concurrency는 같은 morning chain의 중복 실행만 막으며 canonical writer lock을 대체하지 않는다.

## 3. 2026-09-17 Production 실측과 보정

기존 분리 스케줄의 2026-09-17 영업일 cycle은 다음과 같았다.

| 단계 | 실제 실행 |
|---|---|
| NH 전국 | 22:41~02:30 수집, 02:37 publish 완료 |
| KFCC 전국 | 02:38~05:17 수집, 05:24 publish 완료 |
| Data.go funding | 05:25 1차 실패 → 자동복구 후 06:31~06:33 재수집, 06:38 R2 byte-for-byte 검증 완료 |
| 일반/core | 05:27 시작, 06:30 rate-data publish 완료 |

즉 실제 데이터는 07:30 목표 전에 정상화됐지만, 개별 GitHub cron은 예약보다 3~5시간 늦게 생성됐다. 이 실측은 **개별 cron을 더 정교하게 맞추는 방식이 아니라 하나의 early reservation + 실제 수집 not-before gate + 단일 chain으로 제어해야 한다**는 어제 개선안의 방향을 지지한다.

실측이 기존 capacity budget보다 빨랐더라도 한 영업일 자료만으로 안전 예산 자체를 축소하지 않는다. 기존 보수 예산을 유지한다.

| 단계 | 보수 예산 |
|---|---:|
| NH full writer pass | 266분 |
| 기관별 수신잔액 | 38분 |
| 일반 + KFCC 통합 pass | 230분 |
| **Morning chain 합계** | **534분 = 8시간 54분** |
| fast writer contention reserve | **50분** |

`20:45`는 위 보수 예산을 그대로 둔 상태에서 prompt-run의 여유를 가능한 한 소비해 맞춘 값이다.

```text
20:45 actual-start lower bound
+ 50분 writer contention reserve
+ 8시간 54분 morning chain
= 다음 날 06:29 모델 완료
→ 07:30 정상 목표까지 61분 margin
```

최근 관측 최대 scheduler delay **6시간 41분**이면 14:50 예약 run이 21:31에 생성되므로 gate는 이미 지난 상태다.

```text
14:50 + 6시간 41분 = 21:31 actual start
+ 50분 writer reserve
+ 8시간 54분 chain
= 다음 날 07:15 모델 완료
```

따라서 recent-max 지연에서도 07:30 목표를 만족한다. 과거 **약 10시간** scheduler 지연에서는 GitHub-only cron으로 08:00 hard deadline을 보장할 수 없다. 독립 scheduler/watchdog는 별도 high-risk control-plane 작업으로 유지한다.

## 4. 왜 예약은 14:50이고 실제 수집은 20:45인가

GitHub scheduler는 최근 production에서 약 **4시간 46분~6시간 41분** 지연됐고 과거 약 10시간 지연도 관측됐다. cron 자체를 원하는 실제 수집시각에 맞추면 지연량이 그대로 SLA 위험이 된다.

14:50 예약은 15:00 fast refresh와 같은 minute의 scheduler 경쟁을 피하면서 가능한 runway를 확보하기 위한 control-plane 시각이다. 20:45는 검증된 원천기관 최종공시 시각이라는 뜻이 아니라, 영업시간 중간 조기 스냅샷을 피하면서 07:30 SLA에 60분 이상 prompt-run margin을 남기는 운영상 실제 수집 시작 하한이다.

14:50→20:45 대기는 355분이다. GitHub-hosted job의 6시간 한도를 넘기지 않도록 parent gate timeout은 360분으로 고정한다. 20:45보다 더 늦추면 prompt-run 기준 60분 safety margin이 깨지므로 현재 evidence에서는 늦추지 않는다.

## 5. Checkpoint / retry 계약

2026-09-16 PR #333에서 확립한 `COMPLETE_REPLAY_UNPROVEN` 방어를 유지한다.

- 새 business cycle의 parent `run_attempt == 1`: NH/KFCC `fresh`.
- 동일 parent의 `rerun-failed-jobs`인 `run_attempt > 1`: NH/KFCC `auto`.
- NH child 내부 attempt 2/3: `auto`.
- KFCC 첫 attempt 실패 뒤 bounded checkpoint recovery: `auto`.
- volume drop, 0건, source minimum, P1-A 등의 fail-closed 안전 gate는 자동 승인하지 않는다.

Parent scheduled attempt 1이 terminal failure면 `.github/workflows/recover-failed-scheduled-collection.yml`이 `rerun-failed-jobs`를 한 번 수행한다. 성공한 선행 단계는 다시 실행하지 않고 실패 job과 dependent downstream만 재실행한다.

## 6. health 계약

`web/api/health.js`는 다음 계약으로 판정한다.

- scheduled evidence는 morning parent 하나를 기준으로 한다.
- 전날 일~목 14:50 nominal reservation을 다음 날 월~금 morning cycle에 귀속한다.
- GitHub가 자정을 넘겨 run을 생성해도 bounded attribution window 안이면 원래 cycle로 본다.
- **20:45 전 parent 미생성은 `pending`**이다.
- **20:45 이후 parent가 없거나 20:45 이후에 처음 생성됐으면 `warning`**이다.
- 08:00 hard deadline까지 parent evidence가 없으면 `breached`다.
- 특정 KFCC run을 항상 finisher라고 가정하지 않고, cycle의 성공한 canonical publish 중 가장 늦은 완료를 사용한다.

`.github/workflows/source-health-watch.yml`과 `.github/workflows/sync-health-control-plane.yml`도 morning parent 완료를 consumer trigger로 사용한다.

## 7. residual risk

1. **scheduled run 자체 미생성**: `workflow_run` 사건도 없으므로 현재 recovery가 시작되지 않는다. 독립 scheduler/watchdog가 필요하다.
2. **약 10시간급 scheduler 지연**: GitHub-only schedule로 08:00 hard deadline을 보장할 수 없다.
3. **추가 writer contention**: 월 1회 Size Peer writer나 운영자 수동 writer가 겹치면 margin이 줄 수 있다.
4. **원천 장애**: NH/KFCC/CU/Data.go transport·empty response·volume gate 실패는 schedule 최적화로 제거되지 않는다.
5. **Production runtime 검증**: PR CI 성공은 새 14:50 reservation→20:45+ chain의 실제 다음 cycle 성공을 증명하지 않는다. merge 후 최소 3개 영업일 cycle의 `created_at`, collector 시작/종료, publish 완료를 별도 확인한다.

## 8. 스케줄 변경 관리 규칙

1. workflow cron, 이 문서, `web/api/health.js`, schedule 회귀테스트를 **같은 PR**에서 수정한다.
2. UTC↔KST와 예약일→business-cycle 귀속을 테스트한다.
3. UI/문서/API에서 Action 예약 시각과 실제 수집 시각을 분리한다.
4. DB/R2를 쓰는 모든 child는 `rate-data-writer` 직렬화와 fail-closed gate를 유지한다.
5. 실제 실행시간을 줄일 때 검증/gate를 삭제해서 시간을 줄이지 않는다. 중복 restore/build/publish 제거처럼 안전계약을 보존하는 최적화만 허용한다.
6. PR 생성·CI 성공을 Production runtime 검증으로 간주하지 않는다.

**GitHub Actions의 cron은 Action 예약 목표 시각이지 실제 수집 시작 보장이 아니다.**
