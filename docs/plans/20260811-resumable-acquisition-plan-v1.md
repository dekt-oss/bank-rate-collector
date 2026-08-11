# 대규모 수집 Resumable Acquisition 기획안 v1 — 2026-08-11

```yaml
document_type: architecture_plan
status: reviewed_for_merge
implementation_hold: true
date: 2026-08-11
target_repository: dekt-oss/bank-rate-collector
base_evidence_main: eca49e97f193964eca279be49618394b7367acaa
scope:
  - nh_local
  - kfcc
related_prs:
  - 79  # NH transient retry
  - 80  # 08:00 KST collection SLA
review_resolution:
  - automatic_resume_trigger_defined
  - recovery_eligibility_is_machine_readable_and_fail_closed
  - repeat_guard_terminal_semantics_defined
  - memory_reduction_explicitly_out_of_scope
  - workflow_r2_credentials_moved_before_source_integration
  - cycle_date_aligned_with_health_contract
  - fresh_and_gc_contract_defined
  - kfcc_retry_made_prerequisite
```

> **구현 보류.** 이 문서는 리뷰 결과를 반영한 설계 기준이다. 이 문서를 머지해도 수집 동작은 바뀌지 않는다. 실제 구현은 별도 PR에서 최신 `main`을 다시 확인한 뒤 시작한다.

---

## 0. 결론

농·축협(NH local)과 새마을금고(KFCC) 전국 수집은 모두 수천 번의 HTTP 요청을 장시간 순차 실행한다. 현재는 `adapter.fetch()`가 모든 `RawArtifactData`를 메모리에 모은 뒤에야 `collection_service._process()`로 넘기므로, 후반부 장애가 발생하면 이미 받은 원본을 다음 시도에서 이어 쓸 수 없다.

Resumable Acquisition v1의 목표는 이 acquisition 단계에 **R2 durable checkpoint**를 두고, 같은 수집 cycle에서 실패한 source를 **자동으로 한 번 즉시 재시도**하여 마지막 durable checkpoint부터 이어받게 하는 것이다.

핵심은 다음 네 가지다.

1. checkpoint는 **staging evidence**이며 canonical 금리 데이터가 아니다.
2. 일반적인 transport/server 실패는 같은 workflow 안에서 **즉시 1회 자동 recovery**한다. 단, 단순 `step failure`만 보고 재시도하지 않고 checkpoint의 machine-readable terminal state가 recovery 가능함을 증명해야 한다.
3. `RepeatGuard` trip은 transport 실패가 아니라 기존 계약상 **의도된 partial terminal**이므로 resume하지 않는다.
4. v1은 durability 기능이다. `fetch() -> list[RawArtifactData]` 외부 계약을 유지하므로 **peak memory 감소는 목표가 아니다.**

NH에서 문제가 먼저 드러났지만 KFCC도 같은 all-or-nothing acquisition 구조를 갖고 있으므로 공통 계층으로 설계한다.

---

## 1. 현재 상태와 근거

### 1.1 저장소

현재 `config/storage.yaml`은 `backend: r2`이며 R2가 authoritative state store다.

기존 `storage_service.ObjectStore` 계약은 다음 다섯 연산을 제공한다.

```text
put / get / exists / list / delete
```

구현도 이미 `R2ObjectStore`, `LocalObjectStore` 두 종류가 있어 checkpoint를 위해 새로운 저장 시스템을 도입할 필요가 없다.

### 1.2 Canonical 경계

현재 `collect_source()`는 `CollectionRun`을 만든 뒤 `adapter.fetch()`를 호출한다. fetch가 실패하면 run 상태만 실패로 남기고 observation은 쓰지 않는다. fetch가 완전한 `RawArtifactData[]`를 반환한 뒤에야 `_process()`가 raw 저장, parse, canonical observation 저장을 수행한다.

이 경계는 v1에서도 유지한다.

### 1.3 NH

전국 수집은 명부 1회 + 약 4,871점포 × 화면 2개로 약 9,743 요청이다. PR #79의 bounded retry는 이미 request-level 순간 장애를 방어한다.

resume work identity는 다음 source-native key를 사용한다.

```text
brc + screen
```

### 1.4 KFCC

전국 수집은 지역 목록 약 17회 + 약 1,260개 금고 × 상품군 2개로 약 2,537 요청이다.

resume work identity는 다음 key를 사용한다.

```text
gmgoCd + gubuncode
```

금리 응답만으로 기관명·주소를 복원할 수 없으므로 list 단계에서 만든 `outlet` / `outlet_directory` metadata까지 checkpoint 계약에 포함해야 한다.

### 1.5 현재 workflow의 중요한 제약

`Collect NH local`, `Collect KFCC`는 모두 `continue-on-error: true`다. 따라서 source step 실패만으로 별도 workflow가 자동 생성되지 않는다. 또한 core scheduled run 다음의 KFCC-only scheduled run은 NH를 실행하지 않는다.

따라서 checkpoint만 추가하고 recovery caller를 만들지 않으면 NH checkpoint는 다음 날 자동으로 사용되지 못한다. v1은 이 결함을 workflow-level recovery step으로 해결한다.

### 1.6 단순 failure 조건만으로도 부족하다

현재 CLI는 `blocked`, `schema_changed`, 일반 failed를 모두 exit code 1로 표현한다. 따라서 workflow가 단순히 `steps.collect.outcome == 'failure'`만 보고 recovery하면 **차단/계약 오류까지 다시 요청하는 오동작**이 생긴다.

v1은 checkpoint/session 상태를 읽는 machine-readable recovery decision을 별도로 만들고, `failure && recovery_eligible`일 때만 두 번째 source command를 실행한다.

---

## 2. 목표 구조

```text
NH / KFCC source
      │
      ▼
source adapter work plan
      │
      ▼
ResumableAcquisition service
      │
      ├─ request pacing / source retry
      ├─ durable chunk flush
      ├─ manifest pointer commit
      └─ resume compatibility check
      │
      ▼
R2 checkpoints/v1/...
      │
      ▼
acquisition terminal result
      │
      ├─ complete ───────► materialize artifacts ─► existing _process()
      ├─ guard_tripped ──► materialize partial artifacts ─► existing PARTIAL path
      └─ recoverable_fail ► recovery decision=eligible
                               └─ workflow recovery step 1회
                                    └─ same-cycle resume
```

canonical DB에는 acquisition이 정상 완료되거나 기존 `RepeatGuard` 계약에 따라 partial terminal로 종료된 뒤에만 들어간다.

---

## 3. 자동 resume의 호출 주체

### 3.1 결정

v1은 **같은 workflow 안에서 source별 즉시 recovery step을 최대 1회** 둔다.

다만 trigger는 단순 step failure가 아니다.

```text
Collect NH local
  │
  ├─ success/partial ─────────────────────► 다음 단계
  │
  └─ failure
       ↓
  Inspect NH checkpoint/recovery state
       │
       ├─ eligible=false ─────────────────► recovery 금지
       │     blocked / guard / schema / corrupt / incompatible / no checkpoint
       │
       └─ eligible=true
             ↓
        Recover NH local once
             └─ same cycle checkpoint auto resume
```

KFCC도 동일하다.

recovery eligibility는 stdout 문구 parsing이 아니라 JSON 또는 명시적 CLI output처럼 **테스트 가능한 machine-readable contract**로 제공한다.

첫 시도와 recovery 모두 실패하면 기존 stale canonical data를 유지하고 pipeline은 degraded로 남는다. 무한 recovery는 하지 않는다.

### 3.2 fail-closed 원칙

recovery decision을 읽지 못하거나 checkpoint가 손상됐거나 상태가 모호하면 자동 재시도하지 않는다.

```text
unknown != recoverable
```

특히 source block을 일반 network error로 추정해 다시 요청하지 않는다.

### 3.3 왜 고정 06:00 recovery cron을 v1에 넣지 않는가

현재 workflow는 `rate-data-writer` single-writer로 직렬화되고 KFCC-only scheduled run도 04:17 KST에 있다. 별도 06:00 NH recovery run을 추가하면 KFCC와 queue 순서를 공유하게 되고, 실제 queue delay에 따라 08:00 SLA 마진을 오히려 예측하기 어려워진다.

따라서 source/transport 실패는 **실패 직후 같은 workflow에서 즉시** 복구한다.

### 3.4 runner 전체 종료는 별도 실패 모드

GitHub runner 자체가 종료되면 같은 workflow의 recovery step도 실행되지 못한다. v1 checkpoint는 이 경우에도 같은 KST 날짜 안의 `workflow_dispatch --resume auto`로 재작업 시간을 줄인다.

runner-level crash를 위한 별도 scheduled recovery watchdog은 v1 운영 증거가 쌓인 뒤 필요성을 판단한다. 따라서 v1의 자동 복구 보장은 **source command가 실패를 반환하고 workflow가 recovery eligibility를 판정할 수 있는 경우**에 한정한다.

---

## 4. RepeatGuard와 atomicity

### 4.1 기존 계약을 유지한다

`RepeatGuard`는 source가 조회 인자를 무시하는 것으로 보이면 예외를 던지지 않고 `tripped`를 기록한 뒤 그 시점까지 받은 artifacts를 반환한다. 기존 collection path는 이를 `PARTIAL`로 저장한다.

이 동작을 resumable acquisition이 바꾸지 않는다.

### 4.2 terminal 상태를 구분한다

acquisition 상태는 최소 다음을 구분한다.

```text
complete
recoverable_failed
guard_tripped
blocked
schema_or_contract_failed
abandoned
```

`guard_tripped`는 **미완료 work를 나중에 다시 요청하는 resumable 상태가 아니다.** source가 이미 조회 인자를 무시한다고 판단한 상태에서 추가 요청을 보내는 것은 잘못이다.

따라서:

```text
guard trip
→ 즉시 남은 work를 계획에서 중단
→ checkpoint를 terminal partial로 seal
→ 지금까지 받은 artifacts만 materialize
→ 기존 _process()의 fetch_alert / PARTIAL 경로 사용
→ recovery_eligible=false
```

### 4.3 atomicity invariant의 정확한 범위

`100% work plan 완료 전 canonical 승격 금지`는 **recoverable interruption**에 대한 invariant다.

기존 RepeatGuard partial terminal은 이 규칙의 예외가 아니라 별도 terminal contract다. 기존 시스템이 의도적으로 허용하는 partial 수집 의미를 유지한다.

---

## 5. Checkpoint 전략

### 5.1 저장 단위

각 chunk는 immutable하다. manifest가 durable chunk 목록을 가리키고, 마지막에 작은 pointer를 교체해 commit한다.

```text
chunk upload
→ chunk hash 확인
→ 새 manifest upload
→ manifest 확인
→ current pointer 교체
```

pointer가 바뀌기 전 새 chunk는 orphan일 수 있지만, 기존 durable state는 깨지지 않는다.

### 5.2 flush 기준

초기 리뷰안의 `100 items 또는 5분`은 NH에서 거의 항상 item 조건만 먼저 걸린다. 손실 상한을 source 간 비슷한 시간으로 맞추기 위해 v1 기본값을 다음처럼 제안한다.

```text
NH    : 200 work items 또는 5분 중 먼저 도달
KFCC  : 100 work items 또는 5분 중 먼저 도달
```

실측 요청 속도로는 두 source 모두 약 4~5분 간격을 목표로 한다.

추가 flush:

- 정상 acquisition 종료 직전
- recoverable exception을 밖으로 전달하기 직전
- graceful cancellation signal을 처리할 수 있는 경우 종료 직전
- RepeatGuard trip 직후 terminal partial seal

프로세스 kill/OOM처럼 finally가 보장되지 않는 경우에는 마지막 durable chunk 이후 in-memory batch만 손실될 수 있다.

### 5.3 성능 목표

`전체 overhead < 5%`만으로는 기준이 너무 느슨하므로 직접 저장지표도 남긴다.

초기 acceptance target:

```text
checkpoint PUT p95 <= 3초 목표
checkpoint PUT > 5초 발생 시 warning evidence 기록
전체 checkpoint overhead <= source baseline의 5%
```

실제 R2 runtime에서 값이 다르면 측정값을 근거로 조정하며, 목표를 맞추기 위해 request pacing을 공격적으로 줄이지 않는다.

---

## 6. Cycle identity와 resume compatibility

### 6.1 cycle_date_kst 정의

`cycle_date_kst`는 PR #80의 health 계약과 동일하게 **GitHub workflow `run_started_at`을 KST로 변환한 달력일**을 사용한다.

scheduled/manual recovery에서 임의로 `datetime.now()`를 다시 계산해 다른 날짜 정의를 만들지 않는다.

### 6.2 자동 resume 허용 조건

다음이 모두 같아야 한다.

- source_id
- cycle_date_kst
- scope
- product/group set
- request fingerprint
- acquisition contract version
- checkpoint schema version
- frozen directory/work-plan identity

하나라도 다르면 기존 session을 자동 혼합하지 않는다.

### 6.3 전날 checkpoint

다음 날 scheduled cycle에서는 전날 incomplete session을 자동 resume하지 않는다. 이전 날짜의 raw와 오늘 raw가 섞인 snapshot을 만드는 것을 금지한다.

---

## 7. `auto`와 `fresh`

### `auto`

같은 cycle에서 호환되는 active/incomplete session이 있으면 resume한다. 없으면 새 session을 만든다.

### `fresh`

같은 cycle에 기존 session이 있어도 재사용하지 않는다.

기존 active session은:

```text
status = abandoned
active source-day pointer에서 제거
```

한 뒤 새 session을 만든다.

abandoned session 내부에 historical `current.json` 또는 manifest pointer가 남아 있더라도 **GC 보호 대상이 아니다.** GC 보호는 source/day의 active pointer가 현재 가리키는 session과 canonical commit 대기 중인 terminal session에만 적용한다.

---

## 8. 메모리 사용량

### 8.1 v1 비목표

v1은 durability/resume 기능이며 **peak RSS 감소를 보장하지 않는다.**

외부 `fetch(request) -> list[RawArtifactData]` 계약을 유지하고 최종 단계에서 checkpoint artifacts를 모두 materialize한다. `RepeatGuard`도 현재 `_seen: set[bytes]`를 유지하므로, checkpoint staging을 추가한다고 메모리 사용량이 자동으로 줄지 않는다.

### 8.2 위험

구현 방식에 따라 다음이 동시에 존재할 수 있다.

- 현재 in-memory batch
- materialized `RawArtifactData[]`
- RepeatGuard의 body set / last body state

따라서 staging이 durability를 높이면서 순간 RSS는 증가할 수 있다.

### 8.3 검증

NH/KFCC 실제 전국 수집 또는 production-sized fixture에서 peak RSS를 측정한다.

v1 acceptance는 최소:

```text
checkpoint OFF baseline RSS 기록
checkpoint ON peak RSS 기록
OOM 없음
증가 원인 설명 가능
```

을 요구한다.

peak RSS가 runner 안정성을 위협하면 v1 rollout을 멈추고 `materialize_all()` 대체 streaming/iterator 계약 또는 `RepeatGuard` hash-state 경량화를 별도 설계한다.

---

## 9. R2 credential wiring

현재 source collection step에는 `SCOPE`만 있고 R2 credential이 없다. checkpoint가 adapter/acquisition 중 R2를 사용하려면 source integration보다 먼저 credential wiring이 필요하다.

원칙:

- 기존 repository Secrets/Variables를 재사용
- secret 값 로그 출력 금지
- checkpoint가 켜진 source step, recovery decision step, recovery source step에만 필요한 env 전달
- R2 설정 일부 누락은 fail-closed
- credential을 새 public artifact에 넣지 않음

이 작업은 공통 인프라 PR에 포함하고 NH/KFCC integration보다 앞선다.

---

## 10. KFCC transient retry 선행

KFCC `_get`은 현재 NH #79와 같은 transient retry가 없다. 04:17 KST KFCC-only run은 08:00 hard deadline에 가장 가까운 장시간 source이므로 checkpoint framework보다 작은 범위의 retry 보강이 SLA 위험을 더 직접적으로 줄인다.

따라서 실제 구현 순서는 다음으로 고정한다.

```text
PR 0  KFCC bounded transient retry  ← Resumable Acquisition 바깥의 선행 작업
PR A  Common checkpoint infrastructure + R2 env/recovery-decision wiring
PR B  NH integration + immediate one-shot recovery
PR C  KFCC integration + immediate one-shot recovery
PR D  observability / GC / runtime rollout evidence
```

PR 0은 #79의 정책을 그대로 복사하는 것이 아니라 KFCC의 block contract와 timeout을 다시 확인하고 최소 범위로 이식한다.

---

## 11. 보관과 GC

초기 기본값:

```text
incomplete active session  : 72시간
abandoned/orphan session   : 7일
completed + canonical 대기 : canonical commit 확인 전 삭제 금지
```

금요일 실패가 월요일 운영 점검까지 남도록 incomplete 72시간을 유지한다.

GC는 다음을 지우지 않는다.

- source/day active pointer가 가리키는 session
- acquisition complete 후 canonical R2 state commit 확인 전 session
- current recovery가 사용 중이라고 명시적으로 lease/lock된 session(구현 시 필요하면 추가)

반대로 `fresh`로 abandoned된 session은 active pointer 보호를 받지 않고 7일 retention 후 제거 가능하다.

---

## 12. 운영 의미

checkpoint는 관리자 화면의 `last_success`를 바꾸지 않는다.

중간 상태는 별도의 acquisition telemetry다.

예:

```text
NH
canonical data       : 2026-08-10 success
오늘 attempt         : failed
checkpoint progress  : 7,800 / 9,743
recovery eligible    : true
recovery             : pending / running / failed / success
```

checkpoint 7,800건이 있다는 이유로 오늘 금리가 7,800건 갱신된 것으로 표시해서는 안 된다.

---

## 13. 구현 완료 판정

다음이 모두 검증되어야 기능 완료다.

- NH 정상 full run 결과가 checkpoint OFF와 의미상 동일
- KFCC 정상 full run 결과가 checkpoint OFF와 의미상 동일
- 중간 transport failure 후 recovery decision이 eligible=true이고 즉시 recovery step이 same-cycle checkpoint부터 이어감
- blocked/schema/guard/corrupt/incompatible 상태는 recovery_eligible=false
- recovery 성공 시 최종 canonical 결과가 fresh full run과 동일
- first attempt + recovery 모두 실패하면 기존 canonical data 유지
- RepeatGuard trip은 recovery하지 않고 기존 PARTIAL 의미 유지
- corrupted chunk/manifest는 fail-closed
- 다음 KST 날짜 checkpoint 자동 혼합 금지
- `fresh`가 기존 session을 abandoned 처리하고 새 session 생성
- checkpoint PUT p95/overhead 측정
- peak RSS baseline/with-checkpoint 측정
- request interval 및 source block 정책 변화 없음
- canonical R2 state commit 전 checkpoint cleanup 금지

---

## 14. 이번 docs PR의 범위

이 PR은 기획/작업명세 문서만 변경한다.

- adapter 코드 변경 없음
- workflow 변경 없음
- DB schema/migration 없음
- R2 object 생성 없음
- scheduler 변경 없음
- production runtime 변경 없음

문서 머지 후에도 `implementation_hold`는 유지한다. 실제 첫 구현 작업은 **KFCC bounded transient retry**이며, 그 다음에 Resumable Acquisition PR A를 시작한다.
