# 대규모 수집 Resumable Acquisition 작업명세서 v1

```yaml
document_type: implementation_spec
status: proposal_for_review
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
```

> **이 문서는 구현 전 리뷰용이다.**
>
> 이 branch/PR에서는 코드, workflow, DB schema를 변경하지 않는다. 사용자 리뷰 후 승인 시 최신 `main`을 다시 확인하고 구현 PR을 별도로 연다.

---

# 0. Task Boundary

## 0.1 이번 기능이 해결하는 문제

NH와 KFCC는 장시간 전국 수집 중 후반부에 장애가 발생하면 그 실행에서 이미 받아 둔 원본을 다음 실행에 이어서 사용할 수 없다.

현재 공통 실행 경로는:

```text
adapter.fetch()
  └─ 모든 RawArtifactData를 메모리에 누적
       ↓
fetch 전체 성공
       ↓
collection_service._process()
       ↓
raw save / parse / canonical observation
```

이다.

따라서 `fetch()`가 마지막 구간에서 실패하면 `_process()` 자체에 들어가지 못한다.

v1 목표는 이 acquisition 단계에 **R2 durable staging + resume**를 넣는 것이다.

## 0.2 이번 기능이 하지 않는 것

- 수집원 병렬화
- request interval 단축
- multi-runner distributed locking
- canonical DB schema migration
- 새 queue/database 도입
- partial publish
- 전날 checkpoint 자동 재사용
- source block 우회
- 무한 자동 복구

---

# 1. Current State Evidence

## 1.1 저장소

현재 `config/storage.yaml`은:

```yaml
backend: r2
```

이며 R2가 authoritative state store다.

기존 `storage_service.ObjectStore` 계약:

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

따라서 checkpoint를 위해 새 저장 시스템을 추가할 필요는 없다.

## 1.2 Canonical DB 계약

`collection_service.collect_source()`는 먼저 `CollectionRun`을 만든 뒤 `adapter.fetch()`를 호출한다.

`fetch()` 실패 시:

- run status만 failed/blocked/schema_changed로 기록
- observations는 쓰지 않음
- 직전 정상값 유지

`fetch()`가 완전한 `RawArtifactData[]`를 반환한 뒤에만 `_process()`가 raw 저장·parse·관측 저장을 수행한다.

이 fail-safe 경계를 v1에서도 유지한다.

## 1.3 NH

현재 acquisition key로 사용할 수 있는 source-native identity가 있다.

```text
outlet.brc + parser screen
```

현재 대상 product는 term deposit / installment savings이며 상세 screen은 product에 따라 결정된다.

PR #79의 bounded retry는 유지한다.

## 1.4 KFCC

현재 source-native identity:

```text
gmgoCd + gubuncode
```

금리 페이지에는 이름/주소 정보가 충분하지 않아 region list에서 만든 `row`와 `outlet_directory` metadata가 parsing에 필요하다.

따라서 checkpoint는 raw body만 저장하면 안 되고 **artifact request metadata 전체를 보존**해야 한다.

---

# 2. Target Architecture

```text
                     ┌───────────────────────┐
                     │  Acquisition Adapter  │
                     │ NH / KFCC             │
                     └───────────┬───────────┘
                                 │ work item
                                 ▼
                     ┌───────────────────────┐
                     │ ResumableAcquisition  │
                     │ Service               │
                     ├───────────────────────┤
                     │ plan/session identity │
                     │ completed key set     │
                     │ chunk flush           │
                     │ manifest pointer      │
                     │ resume validation     │
                     └───────────┬───────────┘
                                 │
                                 ▼
                         R2 checkpoint/*
                                 │
                     acquisition complete
                                 │
                                 ▼
                     RawArtifactData[] rebuild
                                 │
                                 ▼
                     existing _process()
                                 │
               parse / DB / validate / R2 state
```

### 핵심 invariant

```text
checkpoint_complete != canonical_commit
```

checkpoint는 acquisition evidence이고 사용자-visible state가 아니다.

---

# 3. 제안 파일 구조

구현 시 기본 파일 경계를 다음으로 제안한다.

```text
src/rate_monitor/services/
  resumable_acquisition.py

src/rate_monitor/collectors/nh_local/
  adapter.py

src/rate_monitor/collectors/kfcc/
  adapter.py

tests/
  test_resumable_acquisition.py
  test_nh_local_resume.py
  test_kfcc_resume.py
  test_checkpoint_storage.py
```

기존 `storage_service.py`의 ObjectStore/R2ObjectStore/LocalObjectStore를 재사용한다.

### 원칙

`resumable_acquisition.py`는 NH/KFCC의 URL·brc·gmgoCd 의미를 알지 않는다.

adapter는 R2 key layout이나 manifest revision 규칙을 알지 않는다.

---

# 4. Domain Types

구현 시 아래 수준의 명시적 타입을 권장한다. 실제 이름은 리뷰 후 조정 가능하나 역할 분리는 유지한다.

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
class CheckpointArtifact:
    work_key: str
    artifact: RawArtifactData


@dataclass(frozen=True)
class CheckpointChunkRef:
    sequence: int
    object_key: str
    sha256: str
    item_count: int


@dataclass(frozen=True)
class AcquisitionManifest:
    schema_version: int
    source_id: str
    session_id: str
    cycle_date_kst: str
    request_fingerprint: str
    status: str
    work_plan_hash: str | None
    expected_work_count: int | None
    completed_work_keys: list[str]
    chunks: list[CheckpointChunkRef]
    created_at: str
    updated_at: str
```

`completed_work_keys`가 지나치게 커질 경우 chunk manifest의 item key에서 계산할 수 있으므로 저장 중복 여부는 구현 전에 benchmark한다. v1의 1만 key 수준은 JSON으로도 관리 가능한 크기다.

---

# 5. Checkpoint Namespace Contract

R2 canonical state와 절대 섞이지 않는 별도 prefix를 사용한다.

```text
checkpoints/v1/{source_id}/{cycle_date_kst}/{session_id}/
```

예:

```text
checkpoints/v1/nh_local/2026-08-12/abc123/
checkpoints/v1/kfcc/2026-08-12/def456/
```

하위 구조:

```text
current.json
manifests/
  000001-<sha256>.json
  000002-<sha256>.json
chunks/
  000001-<sha256>.tar.gz
  000002-<sha256>.tar.gz
```

### 금지

- `state/` 아래에 checkpoint를 넣지 않는다.
- `raw/` 장기보관 prefix를 active checkpoint로 재사용하지 않는다.
- `rate-data` branch에 checkpoint를 넣지 않는다.

---

# 6. Manifest Commit Protocol

ObjectStore는 DB transaction이 없으므로 순서 자체가 안전장치다.

## 6.1 Chunk flush

```text
1. local chunk 생성
2. local SHA256 계산
3. store.put(chunk_key, bytes)
4. 필요 시 store.get으로 round-trip 검증
5. 새 immutable manifest 생성
6. store.put(manifest_key, json)
7. store.put(current.json, pointer)
```

### Crash semantics

- 3 이후 5 이전 crash: orphan chunk. resume에서 무시
- 6 이후 7 이전 crash: 새 manifest가 orphan. 이전 current 사용
- 7 성공: 새 checkpoint durable

오래된 orphan은 GC에서 삭제한다.

## 6.2 current.json

예:

```json
{
  "schema_version": 1,
  "manifest_key": "checkpoints/v1/.../manifests/000051-abc.json",
  "manifest_sha256": "...",
  "updated_at": "2026-08-12T03:10:00+09:00"
}
```

Resume는 `current.json`을 신뢰하기 전에:

1. referenced manifest exists
2. manifest hash 일치
3. referenced chunk exists
4. chunk hash 일치

를 확인한다.

하나라도 어긋나면 silently fresh-start하지 않고 **checkpoint corruption으로 fail closed**한다.

---

# 7. Chunk Format

v1 기본 포맷:

```text
tar.gz
```

이유:

- Python 표준 라이브러리 사용 가능
- HTML 압축 효율
- base64 JSON 팽창 회피
- 여러 artifact를 object 하나로 묶어 R2 PUT 수 감소

Chunk 내부:

```text
chunk.json
raw/<safe_name_1>.html
raw/<safe_name_2>.html
...
```

`chunk.json` 예시:

```json
{
  "schema_version": 1,
  "source_id": "nh_local",
  "session_id": "abc123",
  "sequence": 51,
  "items": [
    {
      "work_key": "123456:SFDPW0163R",
      "filename": "rate_123456_SFDPW0163R.html",
      "artifact_type": "html",
      "content_file": "raw/000001.html",
      "content_sha256": "...",
      "content_length": 12345,
      "request_meta": {},
      "schema_fingerprint": "...",
      "source_role": "secondary_official",
      "trust_level": "official_direct"
    }
  ]
}
```

### Path safety

work key를 raw path로 그대로 쓰지 않는다.

- tar path traversal 금지
- `/`, `..`, drive prefix 금지
- chunk 내부 filename은 sequence 기반 safe path 사용
- 실제 source filename은 metadata에 보존

---

# 8. Session Discovery and Compatibility

## 8.1 Request fingerprint

Canonical JSON을 만들어 SHA256한다.

NH 예:

```json
{
  "source_id": "nh_local",
  "cycle_date_kst": "2026-08-12",
  "scope": "전국",
  "products": ["installment_savings", "term_deposit"],
  "checkpoint_contract_version": 1,
  "acquisition_contract_version": 1
}
```

KFCC 예:

```json
{
  "source_id": "kfcc",
  "cycle_date_kst": "2026-08-12",
  "regions": ["..."],
  "groups": ["13", "14"],
  "checkpoint_contract_version": 1,
  "acquisition_contract_version": 1
}
```

정렬 규칙을 고정해 입력 순서 차이 때문에 다른 fingerprint가 생기지 않게 한다.

## 8.2 Auto resume

기본:

```text
same source
+ same cycle_date_kst
+ same request fingerprint
+ compatible schema/version
+ status collecting/acquisition_complete
→ resume candidate
```

여러 candidate가 있으면 임의 선택하지 않는다.

- 하나: 사용
- 0개: 새 session
- 2개 이상: fail closed 또는 명시적 session 선택 요구

## 8.3 Fresh override

운영자가 같은 날에도 새 원천 snapshot을 다시 받고 싶을 수 있으므로:

```text
resume_mode=auto | fresh
```

최소 두 모드를 제공한다.

`fresh`는 이전 session을 삭제하지 않고 `abandoned` 처리 후 새 session을 만든다.

---

# 9. Directory Freeze Contract

## 9.1 NH

첫 source directory:

```text
outlet_list.html
```

session에서 이 명부를 immutable artifact로 보존한다.

명부 parse 결과로 work plan을 만든 뒤:

```text
work_plan_hash = SHA256(canonical sorted work item list)
```

를 manifest에 기록한다.

Resume에서는 새 명부를 다시 받아 섞지 않고 **session에 저장된 명부**로 work plan을 재구성한다.

기본 same-cycle resume 동안 source directory가 바뀌더라도 한 session 안에서 기준 목록을 바꾸지 않는다.

## 9.2 KFCC

directory phase도 checkpoint 대상이다.

Work keys:

```text
list:<region>
```

각 region list artifact를 저장한다.

모든 directory item 완료 후:

- `outlets`
- `directory`
- `gmgoCd` dedupe

를 deterministic하게 재구성하고 rate work plan을 freeze한다.

Rate work keys:

```text
rate:<gmgoCd>:<group>
```

`outlet` 및 `outlet_directory` metadata는 artifact에 보존한다.

---

# 10. Work Item Key Contract

Work key는 session 안에서 유일해야 한다.

## NH

```text
list:all
rate:<brc>:<screen>
```

예:

```text
list:all
rate:123456:SFDPW0163R
rate:123456:SFDPW0164R
```

## KFCC

```text
list:<region>
rate:<gmgoCd>:<group>
```

예:

```text
list:부산
rate:001234:13
rate:001234:14
```

중복 key 생성은 구조 변경 또는 plan bug로 보고 fail closed한다.

---

# 11. Flush Policy

초기 기본값:

```python
CHECKPOINT_MAX_ITEMS = 100
CHECKPOINT_MAX_AGE_SECONDS = 300
```

flush 조건:

```text
pending item >= 100
OR
마지막 durable checkpoint 후 >= 5분
OR
정상 fetch 종료
OR
잡을 수 있는 terminal exception 직전
```

강제 kill에서는 마지막 조건을 실행할 수 없으므로 마지막 durable manifest 이후 응답은 재수집될 수 있다.

### Performance acceptance

정상 수집 시간이 checkpoint I/O 때문에 의미 있게 악화되면 batch를 조정한다.

초기 허용 목표:

```text
checkpoint overhead <= 정상 전체 수집시간의 5%
```

이 값은 구현 후 small-scope + 실제 scheduled run에서 검증하고, 검증 전 보장값으로 주장하지 않는다.

---

# 12. Adapter Integration Contract

기존 `fetch(request) -> list[RawArtifactData]` 외부 프로토콜은 v1에서 유지한다.

Adapter 내부에서 resumable service를 사용해 마지막에는 기존처럼 완전한 artifact list를 반환한다.

즉 `collection_service` 및 parser consumer를 최소 변경한다.

권장 adapter 흐름:

```python
async def fetch(self, request):
    session = resumable.open_or_create(...)
    plan = self._build_or_restore_plan(session, request)

    self._rehydrate_guards(session)

    for item in plan.pending_items:
        artifact = await self._fetch_work_item(item)
        resumable.stage(item.key, artifact)

    resumable.mark_acquisition_complete()
    artifacts = resumable.materialize_all()
    return artifacts
```

실제 구현은 adapter 공통 protocol을 도입할 수 있으나, 다른 small source까지 강제로 리팩터링하지 않는다.

---

# 13. RepeatGuard Resume Contract

현재 NH/KFCC의 repeated-response 감지는 데이터 무결성 기능이다.

Resume 때문에 guard가 초기화돼서는 안 된다.

## v1 권장 방식

Checkpoint에 저장된 artifact를 source-defined deterministic order로 읽어:

```python
guard = RepeatGuard()
for artifact in completed_artifacts:
    guard.observe(...)
```

로 재생한다.

그 후 새 work item을 이어간다.

### NH order

- list 먼저
- rate는 frozen work plan 순서

### KFCC order

- region list 순서
- rate는 frozen gmgoCd/group work plan 순서

테스트는 uninterrupted run과 interrupted+resume run의 `guard.summary()` 및 `guard.tripped` 결과가 같음을 검증한다.

---

# 14. NH Retry Interaction

PR #79의 request-level retry 계약을 유지한다.

- checkpoint는 `_get()` retry 내부에 들어가지 않는다.
- 하나의 work item이 성공한 뒤에만 stage한다.
- failed HTTP response/body는 completed work로 표시하지 않는다.
- execution attempt의 `MAX_TOTAL_RETRIES=50`은 그대로 유지한다.

Resume가 새 process attempt에서 시작되면 retry budget은 다시 0부터 시작한다.

단, manifest telemetry에는:

```text
attempt_count
last_interruption_at
last_interruption_reason
```

등을 남겨 같은 session에서 반복 장애가 있었는지 확인 가능하게 한다.

---

# 15. Canonical Commit Contract

`mark_acquisition_complete()`는 DB commit이 아니다.

반드시 기존 경로를 거친다.

```text
materialize_all()
↓
collection_service._process()
↓
CollectionRun success/partial/schema_changed
↓
workflow validation/gates
↓
Upload state to R2
↓
R2 snapshot round-trip verification
↓
state/current.json update
```

Checkpoint cleanup은 **authoritative R2 state commit 이후**만 허용한다.

### 왜 필요한가

`_process()`가 local runner DB에는 성공했는데 R2 state upload 전에 job이 죽으면, 다음 실행이 restore하는 DB에는 그 run이 없다.

checkpoint가 남아 있으면 같은 complete acquisition을 다시 materialize해 복구 가능하다.

---

# 16. Workflow Integration

현재 `collect.yml`의 single writer:

```yaml
concurrency:
  group: rate-data-writer
  cancel-in-progress: false
```

를 유지한다.

v1은 이 직렬 실행을 concurrency safety 전제로 사용한다.

## 16.1 Environment

NH/KFCC checkpoint가 R2를 쓰기 위해 collection step에도 기존 R2 credential env가 필요할 수 있다.

현재 credential 전달 범위를 확인하고 최소 단계에만 추가한다.

시크릿을 manifest/request metadata/log에 기록하지 않는다.

## 16.2 Commit cleanup step

권장:

R2 state upload가 성공한 뒤 source collection이 checkpoint session을 사용했다면:

```text
checkpoint mark-committed / cleanup
```

을 수행한다.

cleanup 실패는 canonical state를 rollback하지 않는다.

대신 warning/후속 GC 대상으로 남긴다.

## 16.3 Manual recovery

초기 UI를 늘리지 않고 workflow_dispatch input을 필요 최소로 추가하는 방안을 검토한다.

후보:

```yaml
resume_mode:
  auto
  fresh
```

기본 `auto`.

실제 input 추가는 implementation PR에서 기존 workflow UX와 함께 다시 확인한다.

---

# 17. CollectionRun / Observability

v1에서 DB migration은 하지 않는다.

가능하면 기존 fields를 사용한다.

### Failed run message

예:

```text
NhRequestFailure: ...
checkpoint_session=abc123
checkpoint_progress=5100/9742
checkpoint_resume=available
```

### Successful resumed run message

예:

```text
9743개 원본에서 ...
checkpoint resumed 5100/9742, newly fetched 4642
```

`query_context_json`에 비민감 checkpoint metadata를 추가할 수 있다.

후보:

```json
{
  "checkpoint_session_id": "abc123",
  "checkpoint_resume_mode": "auto",
  "checkpoint_resumed": true
}
```

다만 session id를 DB에 반드시 넣어야 하는지 구현 전 consumer를 다시 확인한다.

---

# 18. Corruption / Incompatibility Policy

### Fail closed 대상

- current pointer가 없는 manifest를 가리킴
- manifest hash mismatch
- chunk 없음
- chunk hash mismatch
- chunk 내부 content hash mismatch
- duplicate work key
- expected count와 work plan 불일치
- source mismatch
- cycle date mismatch
- checkpoint/acquisition version mismatch
- directory/work-plan hash mismatch

이 경우:

```text
checkpoint를 조용히 버리고 처음부터 시작하지 않는다.
```

운영자가 `fresh`를 명시적으로 선택해야 새 acquisition을 시작한다.

이유는 corrupted checkpoint를 자동 무시하면 실제 저장소 장애를 숨길 수 있기 때문이다.

---

# 19. Retention / GC

초기 제안:

```text
collecting/incomplete   72시간
acquisition_complete    R2 state commit까지 유지
committed               즉시 chunk 삭제 가능
abandoned               7일
orphan chunk/manifest   7일
```

GC는 source active session을 삭제하지 않는다.

`current.json`이 가리키는 manifest/chunk는 절대 GC하지 않는다.

Retention 수치는 리뷰 후 확정한다.

---

# 20. Security / Privacy

현재 NH/KFCC는 인증키 없이 공개 endpoint를 사용하지만 framework는 일반 raw staging 계층이므로 안전 규칙을 둔다.

- Authorization/Cookie/token 저장 금지
- request metadata는 기존 masking 규율 준수
- R2 credential을 log/manifest에 기록 금지
- checkpoint object는 public site/rate-data에 publish 금지
- tar extraction path traversal 방어
- source response를 실행 가능한 파일로 취급하지 않음

---

# 21. Test Matrix

## 21.1 Common service

| Case | 기대 결과 |
|---|---|
| 100개 plan, 40개 완료 후 process crash | resume 시 41~100만 pending |
| chunk put 후 manifest 전 crash | chunk orphan, completed 증가 안 함 |
| manifest put 후 current 전 crash | 이전 current 기준 resume |
| current pointer 정상 | latest durable manifest 사용 |
| missing chunk | fail closed |
| bad chunk hash | fail closed |
| bad body hash | fail closed |
| duplicate work key | fail closed |
| scope 변경 | incompatible, auto resume 안 함 |
| version 변경 | incompatible |
| same date / same plan | resume |
| 다음 날짜 | 자동 resume 안 함 |
| fresh mode | 새 session |

## 21.2 NH

- list checkpoint 생성
- detail 100번째에서 synthetic interruption
- resume 후 이전 99개 HTTP call 재실행 없음
- retry 후 성공한 item만 completed 처리
- terminal retry failure item은 incomplete
- uninterrupted vs resume final artifact set 동일
- RepeatGuard 결과 동일
- parser/observation 결과 동일

## 21.3 KFCC

- region list 17개 중 중간 interruption
- directory phase resume
- rate phase interruption/resume
- gmgoCd dedupe 결과 동일
- outlet_directory metadata 동일
- already completed gmgoCd/group HTTP 재실행 없음
- RepeatGuard 동일
- final parsed rows 동일

## 21.4 Workflow / Storage

- LocalObjectStore round trip
- R2 synthetic checkpoint prefix round trip
- cleanup 후 current/checkpoint object 없음 확인
- cleanup 실패가 canonical R2 state commit을 실패로 되돌리지 않음
- secret/log sanitization

---

# 22. Runtime Verification Plan

대규모 원천을 고의로 장애 내지 않는다.

## Stage 1 — offline

- fixture
- MockTransport
- LocalObjectStore
- process restart simulation
- corrupted checkpoint fixtures

## Stage 2 — R2 synthetic

실제 R2 `checkpoints/_check/` 또는 isolated test prefix에서 작은 synthetic chunk로:

```text
put → list → get → hash verify → delete
```

확인.

## Stage 3 — small-scope live

가능하면 부산 범위로:

1. 일부 work item 완료
2. 테스트용 controlled interruption
3. 동일 cycle resume
4. 이미 완료된 request가 재호출되지 않는지 로그 대조
5. final canonical 결과를 fresh uninterrupted baseline과 대조

원천에 불필요한 반복 부하를 만들지 않는 범위에서만 수행한다.

## Stage 4 — production scheduled observation

merge 후 실제 전국 수집에서:

- checkpoint chunk 수
- overhead
- cleanup
- 08:00 SLA 영향
- R2 object leak

을 관찰한다.

실제 장애가 없었다면 **resume production path는 아직 실장애 미검증**으로 명시한다.

---

# 23. PR 분리 계획

## PR A — Common Resumable Acquisition Foundation

변경 예상:

```text
src/rate_monitor/services/resumable_acquisition.py
tests/test_resumable_acquisition.py
tests/test_checkpoint_storage.py
```

범위:

- manifest/chunk
- pointer commit protocol
- compatibility
- LocalObjectStore tests
- GC primitive

Adapter 적용 없음.

## PR B — NH integration

변경 예상:

```text
src/rate_monitor/collectors/nh_local/adapter.py
tests/test_nh_local_resume.py
existing NH tests as needed
```

범위:

- directory freeze
- work plan
- resumable fetch
- RepeatGuard rehydrate
- #79 retry interaction

## PR C — KFCC integration

변경 예상:

```text
src/rate_monitor/collectors/kfcc/adapter.py
tests/test_kfcc_resume.py
existing KFCC tests as needed
```

범위:

- region directory resumable phase
- gmgoCd/group work plan
- outlet metadata freeze
- RepeatGuard rehydrate

## PR D — Workflow + Cleanup + Operations

변경 예상:

```text
.github/workflows/collect.yml
CLI/request options if required
operational docs/tests
```

범위:

- R2 checkpoint env wiring
- auto/fresh control
- authoritative state commit 이후 cleanup
- stale checkpoint GC
- operator runbook

### Dependency

```text
A → B
A → C
B + C → D
```

B/C는 가능하면 A merge 후 main에서 각각 분기한다.

---

# 24. CI / Verification Gate

각 구현 PR은 최소:

```text
uv run ruff check src tests scripts
uv run pytest -q
uv run alembic upgrade head
DB tables ↔ model match
```

를 통과한다.

DB migration이 없는 것이 목표지만, accidental model/schema 변경을 CI로 계속 감지한다.

추가 targeted gate:

```text
pytest tests/test_resumable_acquisition.py
pytest tests/test_nh_local_resume.py
pytest tests/test_kfcc_resume.py
```

실제 구현 파일명은 PR A에서 확정한다.

---

# 25. Adversarial Review Checklist

구현자는 "내 resume 구현이 데이터를 섞는다"고 가정하고 다음을 확인한다.

- 어제 checkpoint를 오늘 자동으로 읽지 않는가
- 전국 checkpoint를 부산 run에 섞지 않는가
- 상품군 변경 후 예전 chunk를 쓰지 않는가
- parser metadata가 누락되지 않는가
- KFCC outlet_directory가 이전/새 session에서 섞이지 않는가
- resumed work item이 이중 요청/이중 artifact가 되지 않는가
- RepeatGuard가 interruption 경계에서 초기화되지 않는가
- checkpoint complete를 canonical success로 오해하지 않는가
- local DB 반영 후 R2 commit 실패 시 checkpoint를 너무 일찍 지우지 않는가
- corrupted checkpoint를 조용히 fresh-start하지 않는가
- cleanup이 active session을 지우지 않는가
- R2 checkpoint I/O가 source request pacing을 공격적으로 바꾸지 않는가
- checkpoint metadata에 secret이 들어가지 않는가

P0/P1 발견 시 수정 후 전체 검증을 다시 수행한다.

---

# 26. Rollback

Rollback은 canonical DB migration이 없으므로 단순해야 한다.

### 코드 rollback

- adapter checkpoint integration revert
- 기존 all-or-nothing `fetch()` 경로로 복귀

### 데이터 rollback

Checkpoint는 canonical state와 분리되어 있으므로 삭제해도 기존 운영 DB는 영향이 없어야 한다.

```text
checkpoints/v1/<source>/...
```

만 정리한다.

### 금지

문제가 있다고 `state/current.json` 또는 정상 canonical snapshot을 지우지 않는다.

---

# 27. Acceptance Criteria

구현 완료 판정은 다음을 모두 요구한다.

1. NH/KFCC 모두 공통 framework를 사용한다.
2. synthetic interruption 후 resume가 완료 item을 재요청하지 않는다.
3. same-cycle/incompatible-cycle 판정이 테스트된다.
4. incomplete checkpoint가 canonical observations를 만들지 않는다.
5. final uninterrupted 결과와 resumed 결과가 artifact/parsed-row 기준으로 동등하다.
6. RepeatGuard 결과가 interruption 유무와 무관하게 동일하다.
7. R2 corrupt/missing object는 fail closed한다.
8. canonical R2 state commit 전 checkpoint를 삭제하지 않는다.
9. 정상 request interval과 single-writer 구조를 유지한다.
10. full CI green.
11. small-scope live resume 검증 또는 불가능한 경우 명확한 미검증 표시.
12. merge 후 전국 scheduled run에서 checkpoint overhead와 cleanup을 확인한다.
13. 08:00 SLA에 유의미한 악영향이 없는지 실측한다.

---

# 28. 리뷰 시 확정할 결정

다음은 현재 **제안값**이며 사용자 리뷰 후 고정한다.

| 항목 | 제안 |
|---|---|
| 대상 source | NH + KFCC |
| checkpoint backend | R2 ObjectStore |
| chunk format | tar.gz |
| flush | 100 items 또는 5분 |
| auto resume 범위 | same KST cycle only |
| default resume mode | auto |
| operator override | fresh |
| incomplete retention | 72시간 |
| abandoned/orphan retention | 7일 |
| canonical DB migration | 없음 |
| concurrency | 기존 single writer 유지 |
| parallel fetch | v1 제외 |
| KFCC retry 추가 | 별도 결정 |

리뷰에서 이 표가 확정된 뒤 구현을 시작한다.
