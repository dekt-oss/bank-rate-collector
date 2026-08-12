# NH zero-progress fresh-runner retry v1

```yaml
document_type: implementation_spec
status: current
date: 2026-08-12
target_repository: dekt-oss/bank-rate-collector
base_main: 47758812940e4bf84b1621681faf5e3b6efc0f80
applies_to:
  - nh_local
related:
  resumable_acquisition: docs/specs/20260811-resumable-acquisition-v1.md
  transient_retry_pr: 79
```

## 0. 목적과 근거

운영 NH 수집은 `SFDPW0161R` preflight에서 `NETWORK_CONNECT`/`NETWORK_TIMEOUT`으로
실패한 사례가 있고, 같은 어댑터가 다른 GitHub-hosted runner 경로에서는 성공했다. 현재 확인된
증거는 파서 문제가 아니라 runner egress 경로별 연결 계층 차이다. NH 측 ACL/WAF인지
Azure↔NH 라우팅인지까지는 확정하지 않는다.

기존 한 job 안의 HTTP retry와 checkpoint recovery는 같은 runner를 계속 쓴다. 따라서 **아무
원본도 받지 못한 연결 실패**에 한해 `Collect rates` 종료 후 별도 GitHub Actions workflow/job을
한 번 실행하여 새 GitHub-hosted runner에서 NH를 다시 시도한다.

이 문서는 `20260811-resumable-acquisition-v1.md`의 `multi-runner distributed execution` 비목표에
대한 **NH zero-progress network failure 전용의 좁은 예외**다. 일반적인 multi-runner 분산 수집,
checkpoint work 분배, 무한 recovery는 여전히 비목표다.

## 1. Current state

- NH는 source 내부 bounded retry를 수행한다.
- durable checkpoint 진행이 있으면 기존 같은-workflow recovery가 `--resume auto`로 1회 이어받는다.
- preflight 연결 실패처럼 checkpoint `completed_work_count=0`이면 기존 recovery decision은
  `eligible=false`, `reason_code=NO_DURABLE_PROGRESS`다.
- `CollectionRun` 실패는 canonical 관측을 덮지 않으며 `raw_count=0`, `status=failed`, 실패 메시지를
  남긴다.
- 전체/경량 수집은 `rate-data-writer` concurrency group으로 단일 writer를 유지한다.

## 2. Target state

`Collect rates`의 **scheduled run이 정상적으로 workflow 자체를 완료한 뒤** 별도
`workflow_run: completed` workflow가 판단한다.

자동 fresh-runner retry는 아래 조건을 모두 만족할 때만 1회 실행한다.

1. 부모 workflow 이름이 `Collect rates`다.
2. 부모 event가 `schedule`이고 workflow conclusion이 `success`다.
3. 부모 workflow의 `run_started_at..updated_at` 사이에 생성된 NH `CollectionRun`이 정확히 1개다.
4. 그 run의 `status=failed`다.
5. 그 run의 `raw_count=0`이다.
6. DB failure message의 **terminal code**가 정확히 `NETWORK_CONNECT` 또는 `NETWORK_TIMEOUT`이다.
7. 같은 KST cycle/default scheduled scope의 checkpoint recovery decision이
   `eligible=false` + `reason_code=NO_DURABLE_PROGRESS`다.

하나라도 불명확하면 fail-closed로 retry하지 않는다.

## 3. 명시적 비대상

다음은 fresh-runner retry 대상이 아니다.

- `SOURCE_BLOCKED`, 400/403/429 차단 신호
- `schema_changed`, parser/contract failure
- `HTTP_SERVER_ERROR`, `NETWORK_IO`, `NETWORK_PROTOCOL`, `NETWORK_UNKNOWN`
- retry budget 자체가 terminal code인 경우
- `raw_count > 0`
- durable checkpoint 진행이 있어 기존 resume 대상인 경우
- 부모 run 안에 NH 시도가 0개 또는 2개 이상인 경우
- `workflow_dispatch` 수동 수집 및 custom scope
- KFCC/CU/FINLIFE/FSB 등 다른 source
- retry workflow 자신의 실패에 대한 재귀 retry

메시지 전체에서 `NETWORK_CONNECT`라는 단어가 발견됐다는 이유만으로 재시도하지 않는다.
예를 들어 terminal code가 `RETRY_BUDGET_EXHAUSTED`인데 내부 failure history에
`NETWORK_CONNECT`가 들어 있는 경우는 제외한다.

## 4. 실행/상태 계약

```text
Collect rates (runner A)
  └─ NH first attempt
       ├─ durable progress > 0 -> 기존 same-workflow checkpoint recovery
       └─ CONNECT/TIMEOUT + raw=0 + NO_DURABLE_PROGRESS
             ↓ parent workflow completed
NH fresh runner retry workflow (runner B)
  ├─ authoritative state restore
  ├─ parent-window + DB + checkpoint decision
  ├─ eligible일 때 NH만 --resume auto로 1회
  ├─ snapshot / validation / gates
  ├─ authoritative R2 upload
  └─ rate-data publish
```

- 새 workflow도 `rate-data-writer`를 사용하여 다른 DB writer와 직렬화한다.
- 새 workflow는 `queue: max`를 사용한다. 새 retry가 늦게 생성됐다는 이유로 이미 pending인
  KFCC/다른 writer를 교체 취소하지 않는다.
- retry는 parent의 `run_started_at`을 KST로 변환한 cycle date를 그대로 사용한다.
- retry workflow는 NH 이외 source를 호출하지 않는다.
- NH retry가 또 network failure로 끝나도 세 번째 자동 시도는 없다.
- retry 실패도 DB/summary에 남기기 위해 collection step은 evidence publish까지 진행시키고, 최종
  workflow status는 실패로 표면화한다.
- retry가 다시 preflight zero-raw로 실패한 경우 P1-A의 current-run raw 검사는
  `--no-collection` 계약을 사용한다. 원본이 0건인 것이 기대 상태인 이 경로에서도 실패
  `CollectionRun`과 summary는 canonical state에 남기되 historical integrity 검사는 계속 수행한다.
- authoritative R2 upload는 validation/volume/size gate를 모두 통과한 뒤 수행한다.

## 5. Acceptance

정적/단위 검증:

- CONNECT + raw=0 + `NO_DURABLE_PROGRESS`만 eligible
- TIMEOUT + raw=0 + `NO_DURABLE_PROGRESS`만 eligible
- raw>0, blocked/schema/다른 network code, multiple attempts, durable progress는 ineligible
- workflow trigger는 `Collect rates` completed이고 scheduled parent만 job 실행
- workflow가 `rate-data-writer`를 공유하고 `queue: max`로 pending writer를 보존
- retry workflow의 collector는 NH 정확히 1개
- retry 이후 snapshot/validate/gates/R2/publish 순서 고정
- zero-raw retry 재실패도 failure evidence를 publish한 뒤 workflow failure로 표면화
- 재귀 `workflow_run` 체인 없음

Runtime acceptance:

1. 실제 scheduled NH zero-progress 연결 실패가 발생하면 fresh-runner workflow가 정확히 1회 실행된다.
2. 새 runner의 NH 성공 시 latest NH run이 success/partial 계약에 맞게 갱신되고 public summary가
   새 state를 반영한다.
3. 새 runner도 실패하면 추가 자동 retry 없이 workflow가 실패로 종료되고 두 번째 실패 evidence가
   남는다.
4. 정상 NH 수집일에는 retry workflow가 NH 요청을 보내지 않는다.

PR/CI 성공만으로 runtime acceptance를 충족했다고 보지 않는다.
