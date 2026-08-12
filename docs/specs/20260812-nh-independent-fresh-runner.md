# NH 독립 수집 + fresh-runner 복구 계약 (2026-08-12)

## 1. 배경과 확인된 증거

NH 전국 수집은 실측 약 3시간 37분이고, 기존 `Collect rates` 안에서 다른 원천과 함께 실행됐다. 2026-08-12 네트워크 포렌식 실험(PR #92)에서는 fresh GitHub-hosted runner 10개가 모두 같은 NH 목적지 IP를 해석했지만 8개는 HTTP 200, 2개는 TCP connect 단계에서 `Connection refused`였다. 실패 runner의 일반 인터넷 control 요청은 정상이었고 같은 Azure region 안에서도 성공과 실패가 공존했다.

따라서 현재 증거가 지지하는 운영 가설은 **NH 목적지까지의 L4 reachability가 runner/source egress 경로에 따라 선택적으로 달라질 수 있다**는 것이다. 누가 TCP 거절을 발생시켰는지, NH가 특정 클라우드 사업자를 의도적으로 차단하는지는 증명되지 않았다.

## 2. 목표 상태

- NH는 일반 core 수집 및 KFCC 수집과 **독립 workflow**로 실행한다.
- 정기 시작 시각은 평일 **00:37 KST**(`37 15 * * 0-4` UTC)로 한다.
- NH 실행은 **최초 1회 + fresh runner 재시도 2회 = 최대 3개 runner**로 제한한다.
- 재시도 사이에 `sleep 2m`, `sleep 5m` 같은 명시적 backoff를 두지 않는다.
- 각 attempt는 별도 GitHub-hosted job/reusable workflow call로 실행해 fresh runner를 받는다.
- 모든 attempt는 같은 `cycle_date_kst`를 공유하고, 2·3차 attempt는 `resume auto`를 사용한다.
- 다른 collector와 동일한 `rate-data-writer` concurrency 계약을 유지해 canonical DB/R2/rate-data writer를 직렬화한다.
- 관리자 `지금 수집하기`와 수집 상태 API도 독립 NH workflow를 포함하도록 consumer 계약을 같이 변경한다.

## 3. 왜 00:37 / 3회 / 무대기인가

### 00:37 KST

기존 core 수집은 00:17 KST에 시작한다. NH를 core에서 분리하면 core는 기존보다 짧아지고, NH는 00:37에 시작한다. 같은 writer concurrency 때문에 core가 예상보다 늦으면 NH는 취소되지 않고 대기한다. NH 전국 수집의 기존 실측 3시간 37분을 적용하면 정상적으로 바로 시작했을 때 약 04:14에 끝나며, KFCC 정기 실행은 04:17 KST다. NH가 늦어질 경우 KFCC 역시 writer concurrency에 의해 동시에 canonical state를 쓰지 않는다.

이 시간은 SLA와 기존 schedule을 보존하면서 NH를 독립화하기 위한 운영 배치다. 실제 운영 데이터가 누적되면 재조정할 수 있다.

### 최대 3개 runner

`3`은 장기 통계에서 계산한 확률값이 아니다. 현재 포렌식이 fresh runner 간 reachability 차이를 재현했고, 사용자가 **최초 + 추가 2회**를 초기 운영 상한으로 결정했다. 무한 재시도나 자동 egress allow/deny는 하지 않는다.

### 명시적 대기 없음

포렌식에서 실패는 TCP connect 단계에서 즉시 재현됐고, 같은 시점의 다른 fresh runner는 성공했다. 현재 증거에서는 같은 runner에서 시간을 더 보내는 것보다 runner/egress를 바꾸는 것이 직접적인 복구 행동이다. 따라서 attempt 간 인위적인 2분/5분 sleep은 넣지 않는다. GitHub의 runner provisioning 시간은 존재하지만 이를 특정 최소 대기시간 계약으로 간주하지 않는다.

## 4. Production preflight / forensic contract

각 attempt는 실제 NH collector 전에 가벼운 network preflight를 실행한다.

판정에 사용하는 NH 경로 증거:

1. `wmall.nonghyup.com` DNS A/AAAA
2. 해석된 endpoint의 TCP 443 연결
3. SNI를 사용한 TLS handshake

보조 포렌식 증거(판정에는 사용하지 않음):

- Azure IMDS location
- `api.ipify.org`로 관측한 public egress IP
- `https://example.com/` control HTTPS

보조 서비스가 실패해도 NH TLS 경로가 정상이면 collector는 실행한다. egress IP 조회를 수집 성공의 외부 의존성으로 만들지 않는다.

Preflight는 **NH HTTP GET을 보내지 않는다.** 정상 runner에서 3 MiB 수준의 outlet-list 화면을 preflight와 collector가 이중으로 받지 않도록 DNS/TCP/TLS까지만 검사한다.

checkpoint context는 cycle date를 다음 runner에 넘기기 위해 preflight 전에 로컬에서 계산한다. 반면 R2/DB restore와 migration은 preflight 뒤에 둔다. Attempt 1/2가 `DNS_FAIL`/`TCP_CONNECT_FAIL`/`TLS_FAIL`이면 canonical state를 복원하는 시간도 쓰지 않고 다음 fresh runner로 넘어간다.

분류:

- `READY`: TLS handshake 성공 → collector 진입
- `DNS_FAIL`: DNS 실패
- `TCP_CONNECT_FAIL`: TCP 연결 실패/거절/timeout
- `TLS_FAIL`: TCP는 연결됐으나 TLS 실패

## 5. Retry state machine

### Attempt 1 / 2

- preflight `READY` → DB/checkpoint state 복원 후 실제 NH collect
- preflight 실패 → 실제 NH HTTP 수집과 DB 복원을 시작하지 않고 `retry` → 다음 fresh runner
- collect 성공 → terminal success + canonical publish
- collect 실패 후 checkpoint recovery가 가능하거나, 기존 zero-progress network 판정(`NETWORK_CONNECT`/`NETWORK_TIMEOUT`, raw=0, durable progress 없음)이 fresh-runner 대상이면 → 다음 attempt를 `resume auto`
- 그 외 오류(파서/계약/비네트워크 terminal failure 등)는 무조건 fresh-runner로 숨기지 않고 terminal failure로 처리한다.

### Attempt 3

마지막 runner에서는 preflight가 실패하더라도 DB를 복원하고 실제 collector를 한 번 실행한다. 이유는 최종 네트워크 실패를 `CollectionRun`으로 canonical DB에 기록해 관리자 상태/마지막 실패가 실제 운영 데이터에 남도록 하기 위해서다. 이후 더 이상의 자동 fresh-runner retry는 없다.

## 6. Publication / persistence

중간 `retry` attempt는 canonical R2 또는 `rate-data`를 publish하지 않는다. durable checkpoint progress가 있는 경우 다음 fresh runner는 object-store checkpoint를 기준으로 같은 cycle을 `resume auto`한다.

terminal success 또는 terminal failure에서만 기존 publish/gate 경로를 수행한다. zero-progress network terminal failure는 원본이 없는 것이 기대 상태이므로 기존 `--no-collection` gate 계약을 사용한다.

DB schema/migration은 추가하지 않는다.

## 7. Forensic retention

각 attempt의 Actions artifact를 기존 수집 증거 보관 상한에 맞춰 90일 보관한다. 최소 포함 대상:

- `nh-network-forensics.json`
- checkpoint context / recovery decision
- zero-progress fresh-runner decision(생성된 경우)
- 해당 attempt에서 생성된 raw evidence(있는 경우)
- terminal attempt의 manifest/summary(있는 경우)

public egress IP는 ephemeral GitHub-hosted runner의 관측값이며 비밀값으로 사용하지 않는다. egress IP를 자동 allowlist/denylist 또는 성공 확률 계산에 사용하지 않는다.

## 8. 관리자/API consumer 계약

NH를 workflow 파일만 분리하면 기존 관리 화면이 오작동한다. 기존 `/api/collect`와 `/api/health`가 `collect.yml` 하나만 Source of Truth로 보았기 때문이다.

따라서 다음을 같은 변경에 포함한다.

- `/api/collect`: 관리자 버튼 한 번에 `collect.yml`과 `collect-nh.yml`을 각각 dispatch한다. 두 요청 중 하나만 GitHub에서 받아들여진 partial 상태를 정상으로 숨기지 않는다.
- `/api/collect` 남용 방지: active 판단은 core/NH 두 workflow를 모두 보고, 암호 추측 횟수는 core dispatch만 세어 한 번의 사용자 입력이 두 번으로 계산되지 않게 한다.
- `/api/health`: core/KFCC schedule history와 독립 NH schedule history를 같은 KST cycle로 합쳐 source 상태를 계산한다.
- 독립 NH가 실행 중이면 `active_collection`에도 포함한다.
- KFCC 최종 publish가 성공했더라도 같은 cycle의 NH 실패는 `failed/degraded` 상태로 남긴다.

## 9. 이전 #91 workflow 처리

기존 `Retry NH on fresh runner` workflow는 `Collect rates` 완료 후 별도 1회 retry를 수행했다. NH가 독립 workflow 안에서 최대 3개의 fresh-runner attempt를 자체 관리하므로 이 workflow는 제거한다. 두 recovery 체인을 동시에 유지해 중복 수집/중복 publish가 발생하는 상태를 허용하지 않는다.

## 10. 검증 경계

PR 단계에서 검증할 항목:

- YAML/코드 lint
- unit/workflow-contract tests
- Node 기반 관리자 collect/health consumer tests
- migration/model/schema 기존 CI
- core workflow에서 NH 제거 여부
- 독립 schedule, 최대 3회, 무대기, fresh-job chain, publish guard, forensic artifact 계약
- 관리 버튼 dual dispatch와 health cycle aggregation

PR/CI 통과는 실제 NH production run 성공을 의미하지 않는다. 새 schedule의 실제 runner 교체, 실제 `/api/collect` dual dispatch, production state publish는 main 반영 후 자연 정기 실행 또는 명시적으로 승인된 운영 실행에서 별도로 확인해야 한다.
