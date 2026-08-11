# 대규모 수집 Resumable Acquisition 작업명세서 v1

```yaml
document_type: implementation_spec
status: reviewed_for_merge
implementation_hold: true
date: 2026-08-11
target_repository: dekt-oss/bank-rate-collector
base_evidence_main: eca49e97f193964eca279be49618394b7367acaa
applies_to:
  - nh_local
  - kfcc
related:
  plan: docs/plans/20260811-resumable-acquisition-plan-v1.md
  merged_prs:
    - 79
    - 80
prerequisite_before_pr_a:
  - kfcc_bounded_transient_retry
```

> **Implementation hold.** 이 문서는 구현 전 기준을 확정하기 위한 문서다. 이 docs PR을 머지해도 코드·workflow·DB·R2 object는 바뀌지 않는다. 실제 구현 시작 직전에 최신 `main`, workflow, adapters, storage contract를 다시 확인한다.

---

# 0. Task Boundary

## 0.1 해결할 문제

NH와 KFCC는 장시간 전국 수집 중 후반부에 transport/server 장애 또는 workflow-level 중단이 발생하면 이미 받은 원본을 다음 시도에서 이어서 사용할 수 없다.

현재 실행 경계:

```text
adapter.fetch()
  └─ 모든 RawArtifactData를 메모리에 누적
       ↓
fetch 전체 성공 또는 기존 partial terminal
       ↓
collection_service._process()
       ↓
raw save / parse / canonical observation
```

v1은 fetch/acquisition 단계에 R2 durable staging을 넣는다.

## 0.2 비목표

- 수집원 병렬화
- request interval 단축
- multi-runner distributed execution
- canonical DB schema migration
- partial transport-failure data의 canonical 승격
- 전날 checkpoint 자동 재사용
- source block 우회
- 무한 자동 recovery
- peak memory 감소 보장
- `fetch() -> list[RawArtifactData]` 외부 계약 변경
- RepeatGuard 내부 자료구조 최적화

메모리 절감은 명시적 비목표다. v1은 durability/resume 기능이며 peak RSS는 별도 검증한다.

---

# 1. Current State Evidence

## 1.1 Storage

`config/storage.yaml`의 현재 backend는 `r2`다.

기존 `storage_service.ObjectStore`:

```python
put(key: str, data: bytes) -> None
get(key: str) -> bytes
exists(key: str) -> bool
list(prefix: str) -> list[str]
delete(key: str) -> None
```

구현:

- `R2ObjectStore`
- `LocalObjectStore`

checkpoint는 이 계약을 재사용한다.

## 1.2 Canonical fail-safe

`collect_source()`는 adapter fetch 실패 시 run 상태만 기록하고 observations를 쓰지 않는다. 직전 정상값은 유지된다.

fetch가 artifacts를 반환하면 `_process()`가 raw save / parse / persist를 수행한다.

이 경계를 v1에서도 유지한다.

## 1.3 NH

전국 기본 workload:

```text
명부 1 + 약 4,871점포 × 화면 2 = 약 9,743 HTTP 요청
```

현재 source-native work identity:

```text
brc + screen
```

PR #79의 bounded retry는 유지한다. retry 대상/금지 대상은 checkpoint layer가 재정의하지 않는다.

## 1.4 KFCC

전국 기본 workload:

```text
지역 목록 약 17 + 약 1,260금고 × 상품군 2 = 약 2,537 HTTP 요청
```

source-native work identity:

```text
gmgoCd + gubuncode
```

금리 페이지만으로 institution/address를 복원할 수 없으므로 list-derived metadata 전체를 artifact metadata에 포함한다.

## 1.5 Workflow

현재 `Collect NH local`, `Collect KFCC` step은 모두 `continue-on-error: true`다.

따라서 source command 실패 후 pipeline은 계속되지만 별도 recovery run은 자동으로 생성되지 않는다. v1은 source별 workflow recovery path를 명시적으로 추가해야 한다.

## 1.6 Current CLI failure ambiguity

현재 `rate-monitor collect`는 `success/partial/no_change`만 exit 0이고, `failed/blocked/schema_changed`는 모두 exit 1이다.

따라서 **step outcome failure만으로 recovery eligibility를 판단할 수 없다.**

source block/schema failure까지 자동 재호출하지 않으려면 checkpoint/session state 또는 별도 result artifact를 읽는 machine-readable recovery decision이 필요하다.

## 1.7 R2 credential wiring

현재 NH/KFCC collection step의 env에는 `SCOPE`만 있고 R2 credential이 없다. R2 credential은 restore/upload 단계에만 있다.

따라서 checkpoint common layer가 source step에서 R2를 사용하려면 **source integration보다 먼저 workflow env wiring을 추가**해야 한다.

---

# 2. Core Invariants

## I1. Checkpoint는 canonical data가 아니다

```text
checkpoint progress != published latest data
```

checkpoint는 acquisition staging/evidence다.

## I2. Recoverable interruption은 full acquisition 전 canonical 승격 금지

transport/server interruption으로 work plan이 미완료이면 `_process()`를 호출하지 않는다.

예:

```text
expected=9,742
completed=9,741
recoverable_failed=true
```

이면 canonical commit 금지다.

## I3. RepeatGuard terminal은 I2와 다른 계약이다

`RepeatGuard.tripped`는 기존 시스템에서 예외가 아니라 의도된 partial terminal이다. 그 시점까지 받은 artifacts를 반환하고 `_process()`가 `PARTIAL`로 기록한다.

따라서 guard trip은 resume 대상이 아니다.

## I4. 다른 KST cycle 자동 혼합 금지

어제 incomplete checkpoint를 오늘 scheduled collection에 자동 합치지 않는다.

## I5. Canonical R2 commit 전 cleanup 금지

acquisition complete 뒤 `_process()`와 최종 state snapshot/R2 commit이 끝나기 전에 checkpoint를 삭제하지 않는다.

## I6. Request pacing 유지

checkpoint 도입 때문에 원천 요청 간격을 줄이거나 concurrency를 늘리지 않는다.

## I7. Recovery는 bounded + fail-closed

같은 workflow에서 source failure당 자동 recovery는 최대 1회다.

`unknown`, `blocked`, `guard_tripped`, `schema/contract failure`, `corrupt checkpoint`는 자동 recovery 대상이 아니다.

---

# 3. Target Architecture

```text
Adapter-specific planner / fetcher
             │
             ▼
ResumableAcquisitionService
             │
             ├─ session identity
             ├─ work plan
             ├─ completed work set
             ├─ chunk buffer
             ├─ manifest commit
             ├─ resume validation
             └─ terminal classification
             │
             ▼
R2 checkpoints/v1/...
             │
             ├─ complete
             │    └─ materialize_all() ─► existing _process()
             │
             ├─ guard_tripped
             │    └─ materialize_partial() ─► existing PARTIAL path
             │
             └─ command failure
                  ↓
             RecoveryDecision
                  │
                  ├─ eligible=false ─► no retry
                  └─ eligible=true  ─► workflow recovery step once
                                        └─ same-cycle resume
```

---

# 4. Proposed Module Boundary

구현 시 기본 경계:

```text
src/rate_monitor/services/resumable_acquisition.py
src/rate_monitor/collectors/nh_local/adapter.py
src/rate_monitor/collectors/kfcc/adapter.py
src/rate_monitor/cli.py
.github/workflows/collect.yml

tests/test_resumable_acquisition.py
tests/test_nh_local_resume.py
tests/test_kfcc_resume.py
tests/test_checkpoint_storage.py
tests/test_collection_recovery_workflow_contract.py
```

원칙:

- common service는 NH `brc`나 KFCC `gmgoCd` 의미를 모른다.
- adapter는 R2 manifest revision protocol을 모른다.
- workflow는 artifact 내부 구조를 모른다.
- `_process()` canonical contract는 최대한 그대로 둔다.

---

# 5. Domain Types

실제 이름은 구현 시 조정할 수 있으나 역할 분리는 유지한다.

```python
@dataclass(frozen=True)
class AcquisitionSessionIdentity:
    source_id: str
    cycle_date_kst: str
    request_fingerprint: str
    checkpoint_contract_version: int
    acquisition_contract_version: int


@dataclass(frozen=True)
class AcquisitionWorkItem:
    key: str
    phase: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class CheckpointChunkRef:
    sequence: int
    object_key: str
    sha256: str
    item_count: int
    bytes: int
    created_at: str


@dataclass(frozen=True)
class AcquisitionManifest:
    schema_version: int
    source_id: str
    session_id: str
    cycle_date_kst: str
    request_fingerprint: str
    acquisition_contract_version: int
    status: str
    work_plan_hash: str | None
    expected_work_count: int | None
    completed_work_count: int
    completed_work_keys: list[str]
    chunks: list[CheckpointChunkRef]
    guard_state: dict[str, Any] | None
    terminal_reason: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class RecoveryDecision:
    eligible: bool
    reason_code: str
    source_id: str
    cycle_date_kst: str
    session_id: str | None
    manifest_status: str | None
    completed_work_count: int
```

가능한 manifest status:

```text
collecting
recoverable_failed
complete
guard_tripped
blocked
contract_failed
abandoned
canonical_committed
```

---

# 6. Cycle Identity

## 6.1 정의

`cycle_date_kst`는 PR #80의 health contract와 동일하게 **GitHub workflow `run_started_at`을 KST로 변환한 달력일**이다.

CLI/service가 독자적으로 wall-clock 날짜를 재정의하지 않는다.

workflow에서 가능한 한 명시적 cycle metadata를 source command에 전달한다.

## 6.2 Resume compatibility

자동 resume는 다음이 모두 같을 때만 허용한다.

```text
source_id
cycle_date_kst
scope
product/group set
request_fingerprint
checkpoint_contract_version
acquisition_contract_version
frozen directory/work-plan identity
```

불일치하면 기존 session을 자동 사용하지 않는다.

## 6.3 날짜 경계

다음 KST 날짜의 scheduled run은 전날 incomplete session을 자동 resume하지 않는다.

전날 session은 retention/감사 대상으로만 남는다.

---

# 7. Namespace Contract

canonical state prefix와 분리한다.

```text
checkpoints/v1/{source_id}/{cycle_date_kst}/
```

권장 구조:

```text
checkpoints/v1/nh_local/2026-08-12/
  active.json
  sessions/
    {session_id}/
      manifest-000001.json
      manifest-000002.json
      chunks/
        000001.tar.gz
        000002.tar.gz

checkpoints/v1/kfcc/2026-08-12/
  active.json
  sessions/{session_id}/...
```

### `active.json`

source/day에서 자동 resume 대상으로 인정할 session 하나를 가리킨다.

예:

```json
{
  "schema_version": 1,
  "source_id": "nh_local",
  "cycle_date_kst": "2026-08-12",
  "session_id": "...",
  "manifest_key": ".../manifest-000012.json",
  "manifest_sha256": "...",
  "updated_at": "..."
}
```

각 historical session 내부에 예전 manifest pointer가 남아 있어도 GC 보호 여부는 `active.json`과 terminal state로 판단한다.

---

# 8. Chunk Format

v1 기본 포맷은 `tar.gz`를 사용한다.

이유:

- Python 표준 라이브러리 지원
- raw bytes를 base64로 팽창시키지 않음
- metadata JSON과 body 파일을 한 immutable object로 묶기 쉬움
- R2 object 수를 work item 수만큼 늘리지 않음

chunk 내부 예:

```text
manifest.json
items/
  000001/meta.json
  000001/body.bin
  000002/meta.json
  000002/body.bin
```

각 item meta에는 최소 다음을 저장한다.

```text
work_key
filename
artifact_type
encoding
request_meta_json
captured_at
schema_fingerprint
body_sha256
```

secret/query credential이 있다면 기존 raw artifact masking 규칙을 그대로 적용한다.

---

# 9. Manifest Commit Protocol

chunk와 manifest는 immutable revision으로 저장한다.

flush 순서:

```text
1. chunk bytes 생성
2. chunk sha256 계산
3. R2 put(chunk)
4. 필요 시 get/hash로 검증
5. 새 manifest revision 생성
6. put(manifest revision)
7. manifest hash 계산/검증
8. active.json을 새 manifest로 교체
```

`active.json` 교체가 마지막 commit point다.

중간 실패 시:

- active pointer가 이전 revision을 계속 가리키면 이전 durable checkpoint가 유효
- 새 chunk가 orphan으로 남을 수 있음
- orphan은 GC가 정리

---

# 10. Flush Policy

## 10.1 기본값

시간 기준 손실 상한을 두 source에서 비슷하게 맞춘다.

```text
NH    : 200 items 또는 5분 중 먼저 도달
KFCC  : 100 items 또는 5분 중 먼저 도달
```

초기 실측 기준 약 4~5분마다 durable checkpoint를 기대한다.

## 10.2 강제 flush 시점

- 정상 acquisition 완료 직전
- recoverable exception 전달 직전
- graceful cancellation 처리 직전
- RepeatGuard trip 직후 terminal partial seal

## 10.3 보장하지 못하는 경우

SIGKILL/OOM/runner hard termination에서는 finally가 보장되지 않는다. 이 경우 마지막 durable revision 이후 batch만 손실될 수 있다.

---

# 11. Automatic Recovery Trigger

## 11.1 단순 outcome-only 재시도 금지

다음처럼 구현하면 안 된다.

```yaml
if: ${{ steps.collect_nh_local.outcome == 'failure' }}
```

이 조건만 쓰면 `blocked`, `schema_changed`, generic fatal도 모두 다시 요청될 수 있다.

## 11.2 Machine-readable recovery decision

first source command가 failure로 끝난 경우 workflow는 checkpoint/session 상태를 읽어 `RecoveryDecision`을 만든다.

권장 인터페이스 예:

```text
rate-monitor checkpoint recovery-decision \
  --source nh_local \
  --cycle-date 2026-08-12 \
  --json work/nh-recovery-decision.json
```

실제 command 이름은 구현 시 조정 가능하나 다음 계약은 고정한다.

```json
{
  "eligible": true,
  "reason_code": "RECOVERABLE_NETWORK",
  "session_id": "...",
  "manifest_status": "recoverable_failed",
  "completed_work_count": 7800
}
```

stdout 자연어 parsing으로 판단하지 않는다.

## 11.3 Workflow contract

개념:

```yaml
- name: Collect NH local
  id: collect_nh_local
  continue-on-error: true
  ...

- name: Decide NH recovery
  id: decide_nh_recovery
  if: ${{ steps.collect_nh_local.outcome == 'failure' }}
  ...

- name: Recover NH local
  if: ${{ steps.collect_nh_local.outcome == 'failure' &&
           steps.decide_nh_recovery.outputs.eligible == 'true' }}
  continue-on-error: true
  ... --resume auto
```

KFCC도 동일한 패턴을 사용한다.

## 11.4 Recovery eligibility

`eligible=true` 가능:

```text
recoverable_failed + valid compatible checkpoint
collecting + valid compatible durable checkpoint after child-process abnormal termination
complete + canonical process not confirmed, and re-materialization is proven idempotent/safe
```

`eligible=false` 고정:

```text
blocked
guard_tripped
contract_failed
checkpoint_corrupt
checkpoint_incompatible
next_cycle
no_valid_checkpoint
unknown_fatal
```

`unknown != recoverable`이다.

## 11.5 Fail-closed

recovery-decision command 자체가 실패하거나 R2 상태를 읽지 못하면 automatic recovery를 실행하지 않는다.

source block을 network error로 추정해서 다시 요청하지 않는다.

## 11.6 Recovery count

source/cycle/workflow당 자동 recovery 1회만 허용한다.

두 번째 실패 후에는 계속 반복하지 않는다.

## 11.7 Whole-runner crash

runner 자체가 죽으면 recovery step도 실행되지 않는다. 이 경우 같은 날짜의 manual `workflow_dispatch`가 `--resume auto`로 이어갈 수 있어야 한다.

v1에는 고정 시각 scheduled watchdog을 넣지 않는다. 필요성은 runtime evidence 후 판단한다.

---

# 12. `auto` / `fresh`

## `auto`

같은 source + cycle에서 compatible `active.json` session이 있으면 resume한다. 없으면 새 session을 만든다.

## `fresh`

기존 active session을 resume하지 않는다.

절차:

```text
기존 session manifest status -> abandoned
source/day active.json -> 새 session으로 교체
새 acquisition 시작
```

abandoned session은 historical manifest pointer를 갖고 있어도 active protection을 받지 않는다.

---

# 13. RepeatGuard Contract

## 13.1 기존 의미 유지

`RepeatGuard`는 한도 초과 시 예외를 던지지 않는다.

현재 의미:

```text
source가 서로 다른 조회 인자에 같은 응답을 비정상적으로 연속 반환
→ 더 요청하지 않음
→ 그때까지 받은 artifacts 반환
→ fetch_alert 기록
→ run PARTIAL
```

v1은 이 동작을 변경하지 않는다.

## 13.2 Resume 금지

`guard_tripped`는 `recoverable_failed`가 아니다.

남은 work item을 다음 recovery에서 요청하지 않는다.

이유:

source가 이미 조회 인자를 무시한다고 판단한 상태에서 같은 query를 계속 보내는 것은 원천 부하만 늘리고 데이터 신뢰성을 높이지 않는다.

## 13.3 Checkpoint terminal 처리

trip 직후:

```text
현재 buffer flush
manifest.status = guard_tripped
terminal_reason 기록
남은 expected work는 intentionally_unrequested로 남김
active resume eligibility 제거
partial artifacts materialize
기존 adapter.fetch_alert / _process() 경로 사용
recovery_eligible=false
```

## 13.4 Guard state rehydrate

일반 resume에서는 guard 판단 연속성이 깨지면 안 된다.

v1 구현 선택지는 두 가지다.

1. manifest에 guard state를 명시적으로 저장/복원
2. durable checkpoint artifacts를 순서대로 replay해 guard state 재구성

우선순위는 **정확성 > 속도**다. 기존 guard 의미와 완전히 같음을 테스트할 수 있는 쪽을 선택한다.

단, v1에서 `RepeatGuard._seen`의 bytes 저장 방식을 hash set으로 바꾸는 것은 별도 메모리 최적화 작업으로 분리한다.

---

# 14. Source-specific Planning

## 14.1 NH

### Phase A — directory

명부 응답을 session의 immutable directory artifact로 저장한다.

resume에서는 같은 session의 directory를 사용한다. 재접속할 때마다 새 명부로 work plan을 다시 만들지 않는다.

### Phase B — rate work

work key:

```text
nh:{brc}:{screen}
```

work payload에 parse/build에 필요한 최소 source identity를 포함한다.

### Plan hash

frozen directory + selected product/screens + scope를 canonical JSON으로 만든 뒤 hash한다.

## 14.2 KFCC

### Phase A — regional directory

각 `r1` list 응답을 저장하고 최종 directory를 freeze한다.

### Phase B — rates

work key:

```text
kfcc:{gmgoCd}:{gubuncode}
```

artifact metadata에 반드시 포함:

```text
gmgoCd
gubuncode
r1
r2
outlet
outlet_directory
```

resume에서 이 metadata를 원본과 동일하게 복원할 수 있어야 한다.

---

# 15. CollectionRun / AcquisitionSession Provenance

첫 source command가 실패하고 recovery command가 실행되면 DB에는 서로 다른 `CollectionRun` 두 개가 생길 수 있다.

checkpoint session은 `run_id`에 종속시키지 않는다.

권장 provenance:

```text
CollectionRun attempt 1
  acquisition_session_id = S
  recovery_attempt = 0

CollectionRun attempt 2
  acquisition_session_id = S
  recovery_attempt = 1
  resumed_from_run_id = attempt 1
```

DB schema migration을 피하기 위해 우선 기존 `query_context_json`에 기록할 수 있다. 실제 persistent contract 변경이 필요하면 구현 전에 별도 migration 판단을 한다.

---

# 16. Memory Contract

## 16.1 명시적 비목표

v1은 `fetch() -> list[RawArtifactData]` 계약을 유지하고 완료 시 artifacts 전체를 다시 materialize한다.

따라서 checkpoint가 생겨도 peak RSS가 낮아진다고 주장하지 않는다.

## 16.2 가능한 peak 구성

구현이 잘못되면 동시에 다음이 존재할 수 있다.

```text
chunk staging buffer
materialized full artifact list
RepeatGuard._seen bytes
RepeatGuard._last bytes
```

## 16.3 구현 규칙

- durable flush가 끝난 batch body는 필요하지 않다면 staging buffer에서 해제
- final materialize 직전 불필요한 temporary buffer 해제
- 중복 copy를 피하도록 tar decode/materialize 경로 설계
- 단, 정확성을 위해 RepeatGuard 현재 계약은 임의 변경하지 않음

## 16.4 Runtime verification

반드시 기록:

```text
NH checkpoint OFF peak RSS
NH checkpoint ON peak RSS
KFCC checkpoint OFF peak RSS
KFCC checkpoint ON peak RSS
```

OOM 또는 runner memory pressure가 보이면 rollout을 중단한다.

이 경우 streaming `_process()` 또는 guard hash-state는 별도 후속 설계다.

---

# 17. R2 Credential Wiring

## 17.1 확정된 현재 상태

NH/KFCC collect step에는 R2 env가 없다.

따라서 PR A에서 다음을 먼저 한다.

- `R2_ACCESS_KEY_ID`
- `R2_SECRET_ACCESS_KEY`
- `R2_ACCOUNT_ID`
- `R2_BUCKET`
- `R2_ENDPOINT`
- `R2_REGION`

을 checkpoint를 사용하는 source step, recovery-decision step, recovery source step에 전달한다.

기존 restore/upload 단계와 같은 repository Secret/Variable을 재사용한다.

## 17.2 Fail-closed

checkpoint mode를 켰는데 R2 설정이 일부만 있으면 source를 fresh non-checkpoint mode로 조용히 downgrade하지 않는다.

오류를 명확히 남기고 실패한다.

---

# 18. Error Classification

common layer는 최소 다음을 구분한다.

```text
RECOVERABLE_NETWORK
RECOVERABLE_HTTP_SERVER
CHECKPOINT_STORAGE_TRANSIENT
SOURCE_BLOCKED
GUARD_TRIPPED
CHECKPOINT_CORRUPT
CHECKPOINT_INCOMPATIBLE
SOURCE_SCHEMA_CHANGED
ACQUISITION_CONTRACT_CHANGED
OPERATOR_FRESH
UNKNOWN_FATAL
```

실제 exception mapping은 source별 기존 retry/block taxonomy를 재사용한다.

checkpoint layer가 `403/429/block`을 generic network failure로 바꾸지 않는다.

---

# 19. Performance Metrics

`전체 overhead <= 5%` 외에 직접 지표를 측정한다.

초기 target:

```text
checkpoint PUT p95 <= 3s
single PUT > 5s -> warning evidence
manifest commit latency 기록
checkpoint bytes 총량 기록
checkpoint flush 횟수 기록
resume skipped request 수 기록
전체 source elapsed overhead <= 5%
```

이 값은 acceptance target이며 runtime evidence에 따라 조정할 수 있다. 근거 없이 request interval을 줄여 target을 맞추지 않는다.

---

# 20. GC / Retention

기본값:

```text
active/incomplete : 72h
abandoned/orphan  : 7d
```

삭제 금지:

- source/day `active.json`이 가리키는 session
- `complete` 후 canonical R2 state commit 전 session
- 현재 recovery가 사용 중인 session을 명시적으로 표시했다면 그 session

삭제 가능:

- `fresh`로 abandoned 처리되어 active pointer에서 빠진 session: 7일 후
- pointer가 참조하지 않는 orphan chunk/manifest: 7일 후
- canonical commit이 확인된 completed session: 운영정책에 따라 즉시 또는 짧은 audit retention 후

중요:

**historical session 내부에 `manifest-current` 성격의 pointer가 남아 있다는 이유만으로 영구 보호하지 않는다.** 보호 여부는 source/day active pointer와 terminal state로 판단한다.

---

# 21. Canonical Commit / Cleanup Ordering

정상 complete:

```text
acquisition complete
→ artifacts materialize
→ existing _process()
→ validations / snapshot / publish pipeline
→ authoritative R2 state upload + verification
→ canonical commit confirmed
→ checkpoint session canonical_committed 표시
→ cleanup eligibility
```

중간 단계가 실패하면 checkpoint를 보존한다.

특히 `_process()`가 성공했더라도 authoritative R2 state upload 전에 checkpoint를 지우지 않는다.

---

# 22. CLI / Operator Contract

최소 제안:

```text
--resume auto    # default for enabled resumable source
--resume fresh   # 같은 cycle checkpoint 무시하고 새 session
```

recovery eligibility는 별도의 machine-readable command/output을 둔다.

운영 로그에는 secret 없이 다음을 남긴다.

```text
source_id
cycle_date_kst
session_id
resume_mode
resumed true/false
completed/expected
checkpoint revision
checkpoint flush count
skipped completed work count
recovery attempt number
recovery eligible/reason
terminal status/reason
```

---

# 23. KFCC Retry Prerequisite

Resumable Acquisition 구현 전에 별도 작은 PR로 KFCC transient retry를 먼저 적용한다.

이유:

- KFCC에는 현재 NH #79와 같은 bounded transient retry가 없음
- KFCC-only 04:17 run은 08:00 deadline에 가까움
- checkpoint framework보다 구현 범위가 작고 SLA 위험을 직접 낮춤

정책 원칙:

```text
GET only
transient connect/read/write/timeout/protocol + selected 5xx only retry
403/429/block marker no retry
bounded attempts/backoff
request pacing 유지
retry telemetry 기록
```

세부 exception tuple은 최신 KFCC adapter/httpx 버전을 다시 확인하고 확정한다.

---

# 24. PR Sequence / Dependency

## PR 0 — KFCC bounded transient retry

Resumable Acquisition 바깥의 선행 작업.

## PR A — Common infrastructure + workflow credential/recovery-decision wiring

- resumable domain types
- LocalObjectStore-based tests
- R2 namespace/manifest/chunk service
- hash/corruption validation
- `auto/fresh` session policy
- `RecoveryDecision` machine-readable contract
- GC primitives
- CLI plumbing
- **NH/KFCC collect/recovery-decision/recovery step용 R2 env wiring**
- 기능 flag/default OFF 가능

PR A는 adapter behavior를 바꾸지 않는다.

## PR B — NH integration

의존: PR A

- frozen NH directory/work plan
- NH work key
- checkpoint flush
- same-workflow recovery decision + immediate recovery 1회
- #79 retry와 통합
- guard terminal semantics 유지
- baseline/resume result equivalence tests

## PR C — KFCC integration

의존: PR A + PR 0

- frozen regional directory
- KFCC work key
- full artifact metadata reconstruction
- same-workflow recovery decision + immediate recovery 1회
- KFCC retry와 통합
- RepeatGuard terminal semantics 유지

## PR D — Observability / GC / rollout

의존: PR B + PR C

- checkpoint progress/operator visibility
- cleanup schedule/path
- runtime metrics
- rollout evidence
- docs status update

의존성:

```text
PR 0 ─────────► PR C
PR A ─► PR B ─┐
   └──► PR C ─┼─► PR D
```

---

# 25. Tests

## 25.1 Common service

- new session create
- chunk immutable upload
- manifest revision commit
- active pointer last-write
- crash before pointer update -> previous manifest valid
- corrupt chunk hash -> fail closed
- corrupt manifest -> fail closed
- incompatible fingerprint -> no auto resume
- next KST date -> no auto resume
- fresh -> previous session abandoned + new active session
- GC never deletes active/canonical-pending session
- abandoned session becomes GC eligible
- recovery decision returns false for unknown/corrupt/blocked/guard/contract failure

## 25.2 NH

- first 400 items checkpoint, process crash, resume -> first 400 not refetched
- resumed final artifact set == fresh full artifact set
- transient request retry from #79 still works
- source recoverable failure after checkpoint -> first command exit 1
- decision command -> eligible=true
- recovery command resumes same session
- second failure -> no third auto recovery
- SourceBlocked -> decision false
- schema_changed -> decision false
- RepeatGuard trip -> partial terminal, no resume

## 25.3 KFCC

- directory freeze survives resume
- `outlet_directory` reconstructs exactly
- resumed artifacts parse identically to fresh run
- transient retry prerequisite works
- blocked -> decision false
- RepeatGuard trip -> partial terminal, no recovery

## 25.4 Workflow contract

static tests should verify:

- source step IDs exist
- recovery-decision step only runs after first step failure
- recovery step requires `eligible == true`
- recovery max 1 step per source
- NH recovery excluded from KFCC-only cycle
- source/decision/recovery steps receive required R2 env
- existing single-writer concurrency unchanged
- schedule cron unchanged by this feature unless separately approved
- naive outcome-only recovery condition does not exist

## 25.5 Memory/performance

- production-sized fixture or real controlled run peak RSS measured
- checkpoint PUT latency recorded
- checkpoint overhead recorded
- no request interval regression

---

# 26. Runtime Verification Matrix

| Scenario | Expected |
|---|---|
| normal NH | checkpoint flushes, complete, canonical same as baseline |
| normal KFCC | same |
| NH transient failure recovered by request retry | source command continues, workflow recovery unnecessary |
| NH terminal recoverable failure after progress | first step failure, decision eligible=true, immediate recovery resumes |
| recovery succeeds | final canonical success |
| recovery also fails | stale prior canonical kept, degraded |
| KFCC same | same semantics |
| RepeatGuard trip | terminal PARTIAL, decision=false, remaining work not requested |
| source blocked | decision=false, no recovery loop |
| schema/contract fail | decision=false |
| corrupt checkpoint | decision=false/fail closed, do not fresh silently |
| next-day scheduled run | previous checkpoint not auto resumed |
| fresh operator run | old session abandoned, new session |
| child Python abnormal exit with valid collecting checkpoint | decision may be true after validation |
| runner hard crash | durable checkpoint remains; same-day manual resume possible |

---

# 27. Rollback

v1은 canonical DB migration이 없으므로 rollback은 checkpoint feature path를 끄고 기존 direct fetch로 돌아가는 것이 기본이다.

rollback 원칙:

- checkpoint objects를 즉시 삭제하지 않음
- canonical state는 기존 R2 snapshot이 authoritative
- partial checkpoint를 canonical로 승격하지 않음
- workflow recovery path를 제거/disable해도 기존 source command는 기존 방식으로 실행 가능해야 함

feature flag를 도입할 경우 default/rollback path는 명시적으로 테스트한다.

---

# 28. Adversarial Self-Review Checklist

구현 완료 전에 다음을 반대로 가정하고 공격한다.

- resume가 완료 item을 다시 요청하고 있지 않은가
- request fingerprint collision/누락으로 다른 scope를 섞지 않는가
- cycle_date 정의가 health와 갈라지지 않는가
- RepeatGuard trip을 recoverable failure로 오분류하지 않는가
- `blocked/schema_changed`가 exit 1이라는 이유만으로 recovery되지 않는가
- recovery decision이 없거나 깨졌을 때 retry하는가 — 그러면 실패
- checkpoint corruption에서 fresh로 조용히 떨어지지 않는가
- R2 credential 일부 누락을 무시하지 않는가
- `fresh` old session이 GC 불가 상태로 영구 잔존하지 않는가
- canonical commit 전에 checkpoint를 지우지 않는가
- memory copy가 비정상적으로 급증하지 않는가
- checkpoint PUT 지연이 08:00 SLA를 갉아먹지 않는가
- runner crash 시 마지막 durable manifest가 실제로 복원 가능한가
- workflow recovery가 무한 loop하지 않는가
- first attempt와 recovery가 서로 다른 checkpoint session을 잘못 만드는가
- acquisition session을 DB `run_id`에 묶어 recovery를 막고 있지 않은가

---

# 29. 결정표

| 항목 | 결정 |
|---|---|
| 적용 source | NH + KFCC |
| checkpoint store | 기존 R2 ObjectStore |
| canonical DB migration | 없음 |
| automatic recovery caller | 같은 workflow의 source별 immediate recovery path |
| recovery gate | step failure + machine-readable `RecoveryDecision.eligible=true` |
| outcome-only recovery | 금지 |
| runner hard-crash recovery | same-day manual resume, scheduled watchdog은 v1 제외 |
| RepeatGuard trip | terminal PARTIAL, resume 금지 |
| memory reduction | v1 비목표, peak RSS 측정 필수 |
| cycle_date_kst | GitHub workflow `run_started_at`의 KST 달력일, PR #80과 동일 |
| flush | NH 200 / KFCC 100 또는 5분 중 먼저 |
| chunk | tar.gz |
| same-day resume | auto |
| next-day auto resume | 금지 |
| fresh | 기존 active session abandoned 후 새 session |
| incomplete retention | 72h |
| abandoned/orphan retention | 7d |
| GC pointer protection | source/day active pointer + canonical-pending terminal만 보호 |
| R2 env wiring | PR A에서 source integration보다 먼저 |
| KFCC retry | Resumable Acquisition 전 별도 PR 0으로 선행 |
| parallel collection | v1 비목표 |
| request pacing | 기존 유지 |
| automatic recovery count | source/workflow당 1회 |
| PUT target | p95 <= 3s 목표, >5s warning evidence |

---

# 30. Acceptance Criteria

구현 완료라고 판정하려면 최소 다음이 필요하다.

1. PR 0 KFCC retry merge 및 회귀검증
2. common checkpoint storage tests green
3. NH/KFCC resume integration tests green
4. corrupted/incompatible checkpoint fail-closed
5. machine-readable recovery decision contract 검증
6. blocked/schema/guard/unknown 상태에서 automatic recovery가 실행되지 않음
7. same-workflow automatic recovery 실제 경로 검증
8. RepeatGuard trip의 기존 PARTIAL 의미 회귀 없음
9. next-day checkpoint 자동 혼합 없음
10. `fresh`/GC 계약 검증
11. source/decision/recovery step R2 env wiring 검증
12. checkpoint OFF/ON result equivalence
13. peak RSS baseline/with-checkpoint 측정
14. checkpoint PUT p95/overhead 측정
15. 08:00 SLA에 미치는 영향 기록
16. request pacing/block policy 변화 없음
17. adversarial self-review 완료
18. production rollout 전 controlled/manual evidence 확보

PR/CI green만으로 runtime 완료라고 판정하지 않는다.

---

# 31. Implementation Start Gate

이 문서를 머지한 뒤 실제 구현에 착수할 때는 다음 순서로 다시 확인한다.

```text
latest main HEAD
→ current AGENTS/CLAUDE/README/CI
→ collect.yml source/recovery execution path
→ latest NH/KFCC adapters
→ storage_service ObjectStore/R2 contract
→ current runtime scheduled evidence
→ PR 0 KFCC retry
→ PR A 시작
```

문서가 머지됐다는 사실은 implementation approval 또는 runtime validation을 뜻하지 않는다.
