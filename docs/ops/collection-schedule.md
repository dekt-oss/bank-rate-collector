# Production collection schedule

> 상태: **운영 기준표 (maintained operational reference)**  
> 기준일: **2026-09-16**  
> 실행 계약의 Source of Truth는 `.github/workflows/*.yml`이다. cron·business-cycle·SLA 판정을 바꾸는 PR은 **이 문서, `web/api/health.js`, 관련 회귀테스트를 같은 PR에서 함께 수정**한다.

## 1. 최종 운영 스케줄

모든 표기 시각은 KST(Asia/Seoul) 기준이다. GitHub Actions cron은 UTC다.

| Action 예약 시각 | 실제 수집 시각 | 귀속 cycle | UTC cron | Workflow | 대상/역할 |
|---|---|---|---|---|---|
| **전날 14:50** | **20:30 KST 이후**. 예약 run이 늦게 생성되면 생성 즉시 | 일~목 예약 → 다음 영업일 월~금 morning cycle | `50 5 * * 0-4` | `.github/workflows/collect-morning-cycle.yml` | morning control plane: NH → 기관별 수신잔액 → 일반+KFCC |
| **10:00** | 가변 | 월~금 당일 refresh | `0 1 * * 1-5` | `.github/workflows/collect-savings-fast.yml` | FINLIFE/저축은행중앙회 fast refresh |
| **15:00** | 가변 | 월~금 당일 refresh | `0 6 * * 1-5` | `.github/workflows/collect-savings-fast.yml` | 오후 fast refresh |
| **매월 2일 01:17** | 가변 | 월 1회 | `17 16 1 * *` | `.github/workflows/collect-size-peer-total-assets.yml` | Size Peer 총자산 evidence |

Morning child workflow인 `.github/workflows/collect-nh.yml`, `.github/workflows/collect-institution-funding.yml`, `.github/workflows/collect.yml`은 더 이상 각각의 정기 cron을 갖지 않는다. 이들은 `workflow_call`/수동 실행용 canonical writer로 남고, morning parent가 순서를 고정한다.

### 시간 정의

- **Action 예약 시각**: YAML cron이 의도한 scheduler target.
- **Action run 생성 시각**: GitHub가 run 객체를 실제 생성한 `created_at`.
- **Job 실제 시작 시각**: runner가 job을 시작한 `run_started_at` / job `started_at`.
- **실제 수집 시작 시각**: collector가 원천기관/API/웹 요청을 시작한 시각.
- **실제 수집 종료 시각**: 해당 source 수집·파싱 완료 시각.
- **canonical 반영 완료 시각**: validation/gate를 통과하고 R2/current snapshot/rate-data 반영을 끝낸 시각.

**예약 시각 ≠ 실제 수집 시각**이다. 특히 `전날 14:50`은 데이터를 14:50에 읽는다는 뜻이 아니다. Morning parent는 정상적으로 일찍 생성되면 기다렸다가 **실제 수집 시작 하한 20:30 KST** 이후에만 NH 원천 요청을 시작한다.

## 2. Morning cycle 실행 순서

```text
전날 14:50  GitHub Action 예약
      │
      ├─ run이 20:30 전에 생성됨 → gate에서 20:30까지 대기
      └─ run이 20:30 이후 생성됨 → 즉시 release
      │
      ▼
20:30+  NH 전국
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

## 3. 왜 14:50 예약 / 20:30 실제 수집인가

### 3.1 관측된 scheduler 지연

최근 production cycle에서 GitHub scheduled workflow run 생성은 cron보다 대략 **4시간 46분~6시간 41분** 늦게 나타났다. 과거 audit에서는 **약 10시간** 지연 사례도 확인됐다. 따라서 GitHub cron 시각을 실제 collector 시작시각으로 사용하면 안 된다.

20:30은 검증된 “원천기관의 최종 확정 시각”이라는 의미가 아니다. NH/KFCC 원천에서 하루 최종 공시 완료시각을 계약으로 제공한다는 근거는 확인되지 않았다. **20:30은 영업시간 중간의 조기 스냅샷을 피하면서 다음 날 07:30 SLA를 충족하기 위해 선택한 운영상 실제 수집 시작 하한**이다.

### 3.2 역산 계산

최근 production 실행을 보수적으로 올림한 capacity budget은 다음과 같다.

| 단계 | 보수 예산 |
|---|---:|
| NH full writer pass | 266분 |
| 기관별 수신잔액 | 38분 |
| 일반 + KFCC 통합 pass | 230분 |
| **Morning chain 합계** | **534분 = 8시간 54분** |

기존 구조는 NH/KFCC/funding/core가 각자 restore·build·gate·publish를 반복했다. 새 구조는 일반 source와 KFCC를 같은 마지막 writer pass로 묶어 중복 후처리를 제거하지만, 원천 collector의 안전 gate·checkpoint·volume gate·P1-A·R2 검증은 제거하지 않는다.

또한 15:00 fast refresh도 `rate-data-writer`를 사용한다. 최근 production에서 scheduler 지연 때문에 20시대로 밀린 fast run이 약 45~47분 writer를 점유한 사례가 있어 **추가 50분 writer contention reserve**를 계산에 넣는다. Parent 예약을 정확히 15:00이 아니라 **14:50**으로 둔 이유도 같은 minute의 scheduler 경쟁을 피하고 10분 runway를 더 확보하기 위해서다.

보수 역산:

```text
전날 14:50 예약
+ 최근 관측 최대 scheduler delay 6시간 41분
= 21:31 run 생성 가정
+ fast writer contention reserve 50분
+ morning chain 8시간 54분
= 다음 날 약 07:15 완료
```

따라서 최근 관측 범위에서는 **07:15 모델 완료 → 07:30 정상 목표까지 약 15분 margin**이 남는다. 예약 run이 제시간에 생성되어 20:30에 release되면 동일한 50분 contention reserve를 넣어도 약 06:14 모델 완료다.

다만 과거의 **약 10시간 GitHub scheduler 지연**을 적용하면 GitHub Actions cron만으로 08:00 hard deadline을 보장할 수 없다. 이 경우 필요한 통제는 같은 GitHub scheduler에 하나를 더 거는 것이 아니라 **독립 scheduler/watchdog가 GitHub run 부재를 확인하고 bounded fallback dispatch하는 구조**다. 이는 별도 high-risk 작업으로 분리한다.

## 4. Checkpoint / retry 계약

2026-09-16 PR #333에서 확립한 `COMPLETE_REPLAY_UNPROVEN` 방어를 유지한다.

- 새 business cycle의 parent `run_attempt == 1`: NH/KFCC `fresh`.
- 동일 parent의 `rerun-failed-jobs`인 `run_attempt > 1`: NH/KFCC `auto`.
- NH child 내부 attempt 2/3: `auto`.
- KFCC 첫 attempt 실패 뒤 bounded checkpoint recovery: `auto`.
- volume drop, 0건, source minimum, P1-A 등의 fail-closed 안전 gate는 자동 승인하지 않는다.

즉 “다음 날 새 cycle”은 전날 complete checkpoint를 재생하지 않고, **같은 cycle 안의 실패 복구**는 이미 받은 장시간 진척을 버리지 않는다.

## 5. 실패 복구와 health

`.github/workflows/recover-failed-scheduled-collection.yml`은 `수집 — 아침 SLA 체인`의 scheduled attempt 1이 terminal failure일 때 `rerun-failed-jobs`를 한 번 사용한다. GitHub가 실패 job과 그 dependent downstream jobs를 재실행하므로 성공한 선행 단계는 불필요하게 다시 시작하지 않는다. Parent attempt 2는 위 checkpoint 계약에 따라 `auto`다.

`continue-on-error` source의 soft failure는 동일 parent run의 immutable summary artifact를 `scripts/scheduled_soft_failure_recovery.py`가 읽어 최소 recovery target으로 변환한다.

`web/api/health.js`는 다음 계약으로 판정한다.

- scheduled evidence는 morning parent 하나를 기준으로 한다.
- 전날 일~목 14:50 nominal reservation을 다음 날 월~금 morning cycle에 귀속한다.
- GitHub가 자정을 넘겨 run을 생성해도 bounded attribution window 안이면 원래 nominal reservation의 다음 영업일 cycle로 본다.
- 20:30 전 parent 미생성은 `pending`이다.
- 20:30 이후 parent가 없거나 20:30 이후에 처음 생성됐으면 `warning`이다.
- 08:00 hard deadline까지 parent evidence가 없으면 `breached`다.
- 특정 KFCC run을 항상 finisher라고 가정하지 않고, cycle의 성공한 canonical publish 중 가장 늦은 완료를 사용한다.

`.github/workflows/source-health-watch.yml`과 `.github/workflows/sync-health-control-plane.yml`도 morning parent 완료를 consumer trigger로 사용한다.

## 6. 알려진 residual risk

1. **GitHub scheduled run 자체가 생성되지 않는 경우**: `workflow_run` 이벤트도 없으므로 현재 one-shot recovery가 시작될 사건이 없다. 독립 scheduler/watchdog가 필요하다.
2. **약 10시간급 scheduler 지연 재발**: 현재 07:30/08:00 SLA를 GitHub-only cron으로 보장할 수 없다.
3. **추가 writer contention**: 50분 fast reserve 외에 월 1회 Size Peer writer나 운영자 수동 writer가 겹치면 margin이 줄 수 있다. `rate-data-writer`가 데이터 무결성은 보호하지만 SLA 시간까지 보장하지는 않는다.
4. **원천 장애**: NH/KFCC/CU/Data.go 등의 transport·empty response·volume gate 실패는 스케줄 최적화로 제거되지 않는다. 기존 fail-closed/retry 계약을 유지한다.
5. **Production runtime 검증**: PR CI 성공은 실제 다음 정기 cycle이 14:50 예약→20:30+ 수집→07:30 이전 publish되는 것을 증명하지 않는다. merge 후 최소 3개 영업일 cycle의 `created_at`, collector 시작/종료, publish 완료를 별도로 확인한다.

## 7. 스케줄 변경 관리 규칙

앞으로 production schedule을 바꾸는 PR은 다음을 지킨다.

1. workflow cron, 이 문서, `web/api/health.js`, schedule 회귀테스트를 **같은 PR**에서 수정한다.
2. UTC↔KST와 예약일→business-cycle 귀속을 테스트한다.
3. UI/문서/API에서 Action 예약 시각과 실제 수집 시각을 분리한다.
4. DB/R2를 쓰는 모든 child는 `rate-data-writer` 직렬화와 fail-closed gate를 유지한다.
5. 실제 실행시간을 줄일 때 검증/gate를 삭제해서 시간을 줄이지 않는다. 중복 restore/build/publish 제거처럼 안전계약을 보존하는 최적화만 허용한다.
6. PR 생성·CI 성공을 Production runtime 검증으로 간주하지 않는다.

**GitHub Actions의 cron은 Action 예약 목표 시각이지 실제 수집 시작 보장이 아니다.**
