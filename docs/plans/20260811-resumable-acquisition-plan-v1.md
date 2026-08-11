# 대규모 수집 Resumable Acquisition 기획안 v1 — 2026-08-11

```yaml
document_type: architecture_plan
status: proposal_for_review
date: 2026-08-11
target_repository: dekt-oss/bank-rate-collector
scope:
  - nh_local
  - kfcc
related_prs:
  - 79  # NH transient retry
  - 80  # 08:00 KST collection SLA
```

## 0. 결론

농·축협과 새마을금고 전국 수집은 모두 **수천 번의 HTTP 요청을 몇 시간 동안 순차 수행한 뒤, 마지막에야 원본과 관측값을 영구 저장하는 구조**다.

현재 NH에는 request-level bounded retry가 들어가 있어 순간적인 연결 오류는 상당 부분 흡수하지만, 다음 상황은 여전히 해결하지 못한다.

- 원천 서버가 수분 이상 장시간 불안정
- GitHub Actions runner 종료/취소/프로세스 crash
- 수집 후반부의 네트워크 장애
- 전체 요청의 대부분을 끝낸 뒤 마지막 구간에서 실패

이 경우 이미 수 시간 동안 받아 둔 응답을 다음 실행에서 재사용할 수 없고, 다시 처음부터 수집해야 한다.

새마을금고도 구조가 동일하다. NH에서 장애가 먼저 드러났을 뿐, **대규모 장시간 수집의 durability 문제는 두 수집원 공통 문제**다.

권장 방향은 NH 전용 패치가 아니라 다음 공통 계층이다.

```text
NH / KFCC adapter
      ↓
Resumable Acquisition Layer
      ↓
R2 checkpoint staging
      ↓
전체 work plan 완료
      ↓
기존 collection_service._process()
      ↓
parse / validate / canonical DB / R2 state / rate-data publish
```

핵심 원칙은 하나다.

> **checkpoint는 미완료 수집의 원본 staging일 뿐이다. 전체 수집이 완료되기 전에는 canonical 금리 데이터로 승격하지 않는다.**

따라서 중간 저장을 도입하더라도 기존의 "실패한 수집이 이전 정상 데이터를 훼손하지 않는다"는 fail-safe 계약을 유지한다.

---

## 1. 배경과 문제 정의

### 1.1 현재 NH

현재 `NhLocalAdapter.fetch()`는:

1. 전국 명부 1회 조회
2. 명부에서 대상 점포 결정
3. 점포 × 상품분류별 상세 금리 조회
4. 모든 응답을 메모리의 `artifacts` 리스트에 누적
5. 모든 fetch가 끝난 뒤 `collection_service._process()`에 한 번에 반환

한다.

전국 수집은 코드 계약상 약 9,743 요청 규모이고, 최근 운영 실측은 약 3시간 30분~4시간대다.

PR #79에서 다음은 해결됐다.

- ConnectError / timeout / ReadError / WriteError / 5xx bounded retry
- 403/429/block no-retry
- retry budget
- 실패 telemetry

하지만 retry는 **요청 단위 장애**만 흡수한다.

예를 들어 8,000번째 상세 요청에서 장시간 장애가 발생하면:

```text
1 ~ 7,999 성공
8,000 실패
bounded retry 실패
↓
fetch() exception
↓
_process() 미진입
↓
다음 실행은 다시 1부터
```

가 된다.

### 1.2 현재 KFCC

`KfccAdapter.fetch()`도 같은 all-or-nothing acquisition 구조다.

1. 지역별 `/map/list.do` 목록 조회
2. `gmgoCd` 기준 금고 dedupe + 점포 directory 구성
3. 금고 × 상품군별 `/map/goods_19.do` 조회
4. 모든 응답을 메모리 `artifacts`에 누적
5. fetch 전체 성공 뒤 한 번에 저장/파싱

코드상 전국 요청 계획은 대략:

```text
지역 목록 약 17회
+
금고 약 1,260 × 상품군 2
=
약 2,537회
```

최근 실제 전국 실행은 약 2시간대다.

즉 KFCC도 후반부에서 프로세스가 중단되면 이미 받은 수천 응답을 다음 실행에서 이어 쓸 수 없다.

### 1.3 08:00 SLA와의 관계

PR #80으로 스케줄은 다음으로 앞당겨졌다.

```text
core        00:17 KST
KFCC-only   04:17 KST
normal      07:30 이전 publish 목표
hard SLA    08:00 이전 publish 완료
```

이 스케줄은 정상 실행 시간에는 충분한 버퍼를 만들지만, 장시간 수집 중간 실패 후 **처음부터 full rerun**해야 하면 같은 날 08:00 복구 가능성이 급격히 낮아진다.

따라서 resumable acquisition은 SLA 자체를 보장하는 기능은 아니지만, 장애 시 **재작업 시간의 상한을 checkpoint 간격 수준으로 줄이는 기능**이다.

---

## 2. 목표

### 2.1 기능 목표

1. NH/KFCC 장시간 수집의 중간 원본을 R2에 durable checkpoint로 저장한다.
2. 같은 수집 cycle의 호환 가능한 checkpoint가 있으면 완료된 work item을 다시 호출하지 않는다.
3. 장애 후 재실행 시 미완료 work item부터 이어간다.
4. 중간 수집분은 canonical DB/사용자 화면에 반영하지 않는다.
5. acquisition이 100% 완료된 뒤 기존 parsing/validation/persistence 경로를 최대한 재사용한다.
6. 기존 request pacing을 줄이거나 병렬 요청을 추가하지 않는다.
7. NH/KFCC가 같은 공통 checkpoint framework를 사용하되 source별 session은 완전히 격리한다.

### 2.2 운영 목표

- 장애가 나도 손실 작업량을 "전체 수 시간"에서 "마지막 checkpoint batch" 수준으로 축소
- 재수집 시 원천에 이미 성공한 요청을 반복하지 않아 source load 감소
- failure message에서 checkpoint 진행률과 resume 가능 여부를 알 수 있게 함
- R2 object가 남아 있어도 canonical state와 혼동되지 않도록 namespace와 상태를 분리

---

## 3. 비목표

v1에서는 다음을 하지 않는다.

- NH/KFCC 병렬 수집
- 여러 GitHub runner가 같은 source session을 동시에 처리
- 새로운 PostgreSQL/Redis/queue 도입
- canonical DB schema migration
- raw_artifacts 테이블을 checkpoint 저장소로 사용
- 미완료 checkpoint를 부분 성공 데이터로 publish
- 이전 날짜 checkpoint를 자동으로 다음 영업일 수집에 혼합
- 자동 무한 recovery loop
- collector별 request interval 단축
- checkpoint를 이유로 차단 우회 또는 공격적 retry

Checkpoint는 **durability** 기능이고, parallelization은 별도 성능 최적화 단계다.

---

## 4. 설계 원칙

### 4.1 Acquisition과 Canonicalization 분리

현재는 논리적으로 다음 두 단계가 `fetch()`와 `_process()` 경계로 이미 분리되어 있다.

```text
Acquisition
HTTP → RawArtifactData[]

Canonicalization
RawArtifactData[] → raw save → parse → validate → observations
```

v1은 이 경계를 유지한다.

변경 후:

```text
HTTP
↓
checkpoint chunk 저장
↓
전체 work plan 완료
↓
checkpoint에서 RawArtifactData[] 재구성
↓
기존 _process()
```

따라서 parser, institution/product identity, variant dedupe, rate observation 계약은 가능한 한 건드리지 않는다.

### 4.2 Atomic visibility

아래 상태에서는 사용자 최신 금리로 승격하지 않는다.

```text
expected_work = 9,742
completed_work = 9,741
```

99.99%를 받았어도 acquisition은 incomplete다.

사용자 화면은 직전 정상 canonical snapshot을 유지한다.

### 4.3 Checkpoint는 R2 전용 staging

운영 backend는 현재 `config/storage.yaml` 기준 `r2`다.

기존 `storage_service.ObjectStore`는 이미:

- put
- get
- exists
- list
- delete

를 제공하며 R2와 LocalObjectStore 구현이 있다.

따라서 새 저장 제품을 도입하지 않고 이 추상화를 재사용한다.

### 4.4 Immutable chunks + manifest pointer

수천 개 응답을 각각 R2 object 하나로 쓰는 대신 batch chunk를 사용한다.

권장 구조:

```text
checkpoints/
  nh_local/
    2026-08-12/
      <session_id>/
        current.json
        manifests/
          000001-<sha>.json
          000002-<sha>.json
        chunks/
          000001-<sha>.tar.gz
          000002-<sha>.tar.gz

  kfcc/
    2026-08-12/
      <session_id>/
        ...
```

순서:

```text
chunk 생성
→ R2 put
→ 필요 최소 검증
→ immutable manifest 생성
→ manifest put
→ 마지막에 current.json pointer 교체
```

manifest가 업데이트되기 전에 죽으면 새 chunk는 orphan일 뿐이며 resume 기준에는 포함되지 않는다.

### 4.5 같은 날짜라고 무조건 resume하지 않는다

호환성은 최소 다음이 모두 같아야 한다.

- source_id
- cycle_date_kst
- scope
- 상품/상품군 set
- checkpoint contract version
- request semantics version
- frozen directory/work-plan identity

불일치하면 자동 혼합하지 않고 새 session을 만든다.

---

## 5. Source별 Work Plan

### 5.1 NH

Directory artifact:

```text
GET /servlet/SFDPW0161R.view
```

Directory가 확보되면 해당 session의 작업 목록을 freeze한다.

Work item key:

```text
<brc>:<screen>
```

예:

```text
123456:SFDPW0163R
123456:SFDPW0164R
123457:SFDPW0163R
123457:SFDPW0164R
```

Resume 시:

1. session의 frozen outlet list를 복원
2. expected work plan 재구성/검증
3. completed key 제외
4. 미완료 key만 요청

### 5.2 KFCC

KFCC는 directory phase 자체도 여러 요청이다.

Directory item key:

```text
list:<r1>
```

예:

```text
list:서울
list:부산
list:경남
```

모든 대상 지역 목록을 확보한 뒤:

- `gmgoCd` dedupe
- `outlet_directory` 구성
- rate work plan freeze

Rate item key:

```text
<gmgoCd>:<gubuncode>
```

예:

```text
001234:13
001234:14
001235:13
001235:14
```

KFCC는 금리 응답에 금고 이름/주소가 충분하지 않기 때문에 **frozen directory metadata가 checkpoint artifact와 함께 보존되어야 한다.**

---

## 6. Session Identity

권장 session identity 입력:

```text
source_id
cycle_date_kst
scope / regions
products or groups
checkpoint_contract_version
source_acquisition_contract_version
```

이를 정규화한 request fingerprint를 만든다.

예:

```text
sha256(
  source_id=nh_local
  cycle_date=2026-08-12
  scope=전국
  products=installment_savings,term_deposit
  checkpoint_v=1
  acquisition_v=1
)
```

Directory를 처음 확보한 뒤에는 추가로:

```text
directory artifact hash
work_plan_hash
expected_work_count
```

를 manifest에 고정한다.

### 6.1 날짜 경계

자동 resume는 **같은 KST cycle_date만** 허용한다.

전날의 미완료 session을 다음 날 scheduled run에 자동 혼합하지 않는다.

필요하면 운영자가 명시적인 session id로 forensic/recovery를 수행할 수 있게 설계할 수 있지만, 기본 경로는 새 날짜 = 새 session이다.

---

## 7. Checkpoint Batch 정책

v1 기본 제안:

```text
100 work items
또는
5분
```

중 먼저 도달하면 checkpoint flush한다.

또한 정상적으로 exception을 감지한 경우 마지막 미flush batch도 가능한 범위에서 flush한 뒤 실패를 기록한다.

강제 runner 종료/프로세스 kill에서는 마지막 durable checkpoint 이후 batch는 잃을 수 있다. 이것이 의도한 최대 손실 반경이다.

숫자 100/5분은 초기값이며 실제 R2 put 시간과 chunk 크기를 테스트한 뒤 조정한다.

---

## 8. Chunk 내용

각 chunk는 표준 라이브러리로 처리 가능한 `tar.gz`를 우선 제안한다.

예:

```text
chunk.json
raw/<work_key-safe>.html
raw/<work_key-safe>.html
...
```

`chunk.json`에는 최소 다음을 둔다.

- checkpoint schema version
- source_id
- session_id
- chunk sequence
- item key 목록
- item별 filename
- item별 sha256
- item별 request metadata
- artifact_type / encoding
- captured_at
- chunk 전체 sha256

HTML은 base64 JSON에 넣지 않는다. 대형 HTML에 33% 수준의 base64 팽창을 만들 이유가 없다.

---

## 9. Manifest 상태

예시:

```json
{
  "schema_version": 1,
  "source_id": "nh_local",
  "session_id": "...",
  "cycle_date_kst": "2026-08-12",
  "status": "collecting",
  "request_fingerprint": "...",
  "work_plan_hash": "...",
  "expected_work": 9742,
  "completed_work": 5100,
  "chunk_count": 51,
  "chunks": [
    {"key": ".../chunks/000051-....tar.gz", "sha256": "..."}
  ],
  "created_at": "...",
  "updated_at": "..."
}
```

상태 후보:

- `collecting`
- `acquisition_complete`
- `committed`
- `abandoned`

Hard kill은 `collecting` 상태 그대로 남을 수 있다. 다음 실행이 이를 정상적인 resume 후보로 판단한다.

---

## 10. RepeatGuard / 수집 무결성

NH와 KFCC 모두 `RepeatGuard`를 사용한다.

Resume 시 단순히 새 `RepeatGuard()`를 만들고 남은 요청부터 시작하면 **이전 chunk와 새 응답 사이의 반복 패턴을 놓칠 수 있다.**

따라서 v1 구현은 다음 중 하나를 반드시 해야 한다.

권장:

```text
checkpoint의 완료 artifact를 deterministic order로 재생
→ guard.observe(...)로 상태 복원
→ 남은 요청 수집
```

또는 RepeatGuard의 최소 state를 checkpoint에 직렬화한다.

현재 구현 복잡도를 고려하면 **artifact replay 방식이 더 안전**하다.

이 요구사항을 빼면 resume는 성공해도 기존 repeated-response integrity contract를 약화시킨다.

---

## 11. Retry와 Resume의 관계

둘은 대체관계가 아니다.

```text
요청 실패
↓
bounded retry
↓
성공 → 계속

bounded retry도 실패
↓
마지막 checkpoint 보존
↓
run 실패
↓
후속 실행이 resume
```

- retry: 초~분 단위 transient failure 방어
- checkpoint/resume: run/process 단위 durability

NH의 `MAX_TOTAL_RETRIES=50`은 execution attempt 단위로 유지한다.

Resume는 새로운 실행 attempt이므로 retry budget은 새로 시작하되, checkpoint manifest에는 누적 attempt/중단 이력을 별도로 남겨 사후 분석이 가능하게 한다.

---

## 12. 완료와 Commit

`acquisition_complete`는 아직 운영 반영 완료가 아니다.

전체 흐름:

```text
R2 checkpoint acquisition_complete
↓
RawArtifactData[] reconstruction
↓
collection_service._process()
↓
local SQLite 업데이트
↓
validation / gates
↓
R2 authoritative state snapshot upload + verify
↓
state/current.json 교체 성공
↓
checkpoint committed / cleanup 가능
```

특히 `_process()`는 성공했지만 이후 R2 state upload가 실패하면 checkpoint를 즉시 지우면 안 된다.

다음 실행이 이전 authoritative DB를 복원한 뒤 같은 completed acquisition을 다시 처리할 수 있어야 하기 때문이다.

### 12.1 Cleanup 제안

- canonical R2 commit 성공: checkpoint raw/chunk 삭제 가능
- 실패/미완료: 72시간 보존
- abandoned/incompatible: 최대 7일 후 GC
- manifest에는 cleanup 결과를 남기거나 삭제 전에 마지막 로그 기록

정확한 retention은 R2 실제 용량/비용을 본 뒤 확정한다.

---

## 13. Failure Semantics

### 13.1 수집 중 요청 실패

```text
status = failed
canonical observations = 변경 없음
checkpoint = retained
message = session_id + completed/expected + failure reason
```

예:

```text
NH acquisition interrupted
session=abc...
completed=5100/9742
resume=yes
NETWORK_TIMEOUT ...
```

### 13.2 GitHub runner hard failure

DB에 failure run 기록 자체가 남지 않을 수도 있다.

그래도 R2 checkpoint는 마지막 durable manifest까지 살아 있어 다음 실행에서 감지할 수 있다.

### 13.3 acquisition complete 후 parser/schema 실패

이때는 더 fetch할 것이 없으므로 resume 대상이 아니다.

checkpoint는 forensic/reprocess용으로 유지하고 기존 `schema_changed`/`partial` 계약을 따른다.

---

## 14. 운영 제어

기본 정책:

```text
same-cycle compatible checkpoint 존재
→ auto resume

없음
→ new session
```

운영자를 위해 최소한 다음 두 제어는 필요하다.

- `auto` — 기본. 호환 checkpoint가 있으면 이어서 수행
- `fresh` — checkpoint를 무시하고 새 session 생성

추후 필요하면:

- `require:<session_id>` — 특정 checkpoint만 resume

를 추가할 수 있다.

v1에서 UI를 복잡하게 만들 필요는 없고 CLI/request option으로 먼저 제공하는 편이 안전하다.

---

## 15. 공통화 범위

공통 layer가 소유할 것:

- session 생성/조회
- request fingerprint
- chunk pack/unpack
- manifest revision/current pointer
- completed key 계산
- R2 put/get/list/delete
- resume compatibility 판정
- retention/GC
- progress telemetry

Source adapter가 소유할 것:

- directory 획득 방식
- work item key
- HTTP request 생성
- RawArtifactData metadata 구성
- RepeatGuard stream/where 의미
- parsing

Adapter가 R2 경로/manifest JSON 구조까지 직접 알게 만들지 않는다.

---

## 16. 단계별 도입 제안

### Phase A — Common checkpoint foundation

- `resumable_acquisition` 공통 service
- manifest/chunk codec
- LocalObjectStore 기반 unit tests
- crash boundary tests
- canonical DB 변경 없음

### Phase B — NH integration

- outlet-list freeze
- `brc:screen` work key
- checkpoint batch
- resume
- RepeatGuard replay
- 기존 bounded retry와 결합
- 실제 전국 full crawl 대신 fixture/controlled source-safe 검증

### Phase C — KFCC integration

- region directory checkpoint
- `gmgoCd:gubuncode` work key
- outlet_directory freeze
- RepeatGuard replay
- resume

### Phase D — Workflow/operations

- auto/fresh option
- progress log
- canonical R2 commit 이후 cleanup
- stale checkpoint GC
- manual recovery runbook

각 phase는 독립 PR로 쪼개는 것이 안전하다.

---

## 17. 검증 전략

### Unit

- 100개 중 40개 후 crash → resume가 41부터 수행
- checkpoint chunk put 후 manifest 전 crash → orphan chunk 무시
- manifest pointer 업데이트 전 crash → 이전 manifest 사용
- 동일 source/date라도 scope 다르면 resume 금지
- product/group set 다르면 resume 금지
- contract version 다르면 resume 금지
- chunk hash mismatch → fail closed
- missing chunk → fail closed
- duplicate work key → fail closed
- completed count와 manifest key set 불일치 → fail closed
- previous artifact replay 후 RepeatGuard 상태 동일성

### Adapter integration

NH:

- directory freeze
- mid-detail interruption
- same-cycle resume
- fresh override
- retry + checkpoint 상호작용

KFCC:

- directory phase interruption
- directory complete / rate phase interruption
- `outlet_directory` 복원 정확성
- repeated-response guard 회귀

### Storage

- LocalObjectStore full round trip
- R2 test prefix에 small synthetic checkpoint put/get/list/delete
- production state prefix와 namespace 격리

### Runtime

대규모 원천에 장애를 일부러 유발하지 않는다.

가능한 검증:

1. synthetic/fixture로 강제 interruption
2. 작은 범위(부산 등)에서 checkpoint 후 resume
3. 다음 실제 전국 scheduled run에서는 정상 경로가 checkpoint를 만들고 cleanup되는지 관찰
4. 실제 장애가 나면 completed/expected와 resume 동작을 증거로 확인

---

## 18. Acceptance Criteria

다음이 모두 충족돼야 v1 완료로 본다.

1. NH와 KFCC가 공통 checkpoint framework를 사용한다.
2. 같은 cycle의 호환 checkpoint에서 이미 완료된 work item을 다시 요청하지 않는다.
3. 미완료 checkpoint는 canonical DB에 부분 반영되지 않는다.
4. full acquisition 완료 후 기존 `_process()` 계약으로 canonicalization된다.
5. R2 authoritative state commit 전에는 checkpoint를 삭제하지 않는다.
6. RepeatGuard integrity가 resume 전후 동일하게 유지된다.
7. crash/incompatible/corrupt checkpoint 테스트가 fail-closed한다.
8. request pacing과 동시성이 기존보다 공격적으로 변하지 않는다.
9. NH/KFCC 기존 parser/data identity/gate 테스트가 모두 통과한다.
10. 실제 scheduled run에서 normal path 성능 저하가 운영상 허용 범위인지 확인한다.

---

## 19. 의사결정이 필요한 항목

구현 전 리뷰에서 다음을 확정한다.

1. checkpoint batch 기본값: `100 items / 5분`이 적절한가
2. incomplete checkpoint 보존: 72시간이 적절한가
3. `fresh` override를 CLI에만 둘지 workflow_dispatch에도 노출할지
4. completed acquisition을 R2 state commit 실패 후 자동 재처리할지 수동 recovery만 허용할지
5. v1에서 KFCC transient retry까지 같이 넣을지, checkpoint 범위와 분리할지

이 문서는 위 결정을 위한 기획안이며, 승인 전 구현 계약으로 간주하지 않는다.
