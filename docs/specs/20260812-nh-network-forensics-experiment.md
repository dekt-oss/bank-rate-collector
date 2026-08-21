# NH network forensics experiment — 2026-08-12

## 0. 목적

`nh_local`이 어떤 GitHub-hosted runner에서는 성공하고 다른 실행에서는
`NETWORK_CONNECT` / `NETWORK_TIMEOUT` + `raw=0`으로 끝나는 원인을 네트워크 계층별로
분리해서 관측한다.

이 실험은 **진단 전용**이다. production DB/R2/rate-data를 읽거나 쓰지 않으며,
NH 점포 상세 화면을 순회하지 않는다.

## 1. 현재 증거와 가설

이미 관측된 사실:

- 실제 전국 수집 성공 실행은 NH 첫 화면부터 상세 화면까지 9,743개 원본을 받았다.
- 실패 실행은 첫 화면 `SFDPW0161R`에서 HTTP 응답을 한 바이트도 받지 못하고
  `ConnectError` / timeout으로 끝났다.
- 성공·실패 모두 `ubuntu-latest`, Ubuntu 24.04, Python 3.12, httpx 0.28 계열이며
  endpoint/User-Agent/connect timeout은 본질적으로 같다.
- runner Azure region과 worker는 실행마다 달라진다.

이번 실험은 다음 가설을 한 번에 수정하지 않고 **관측으로 분리**한다.

1. DNS 결과 자체가 runner마다 다른가.
2. 같은 destination IP라도 TCP 443 연결 성패가 egress별로 갈리는가.
3. TCP는 되지만 TLS/SNI에서 실패하는가.
4. TCP/TLS는 되지만 실제 HTTP GET에서 실패하는가.
5. NH만 실패하고 일반 인터넷 control 요청은 성공하는가.

## 2. 실험 구조

`agent/nh-network-forensics` 브랜치 push에서만 동작하는 일회성 workflow를 둔다.
GitHub-hosted runner 10개를 matrix job으로 독립 배정한다.

각 runner는 다음 증거를 JSON으로 남긴다.

- GitHub runner name / OS / arch / run id
- Azure IMDS location (읽을 수 있을 때만)
- 외부에서 보이는 public egress IPv4 (`api.ipify.org`)
- `wmall.nonghyup.com` DNS A/AAAA 결과
- 각 resolved address의 TCP 443 연결 결과
- TCP 성공 시 TLS handshake/SNI 결과와 TLS version/cipher
- `https://example.com/` control HTTP GET
- production collector와 같은 NH endpoint/User-Agent/timeout을 사용한 httpx GET
- HTTP status, body bytes, remote IP, 단계별 exception class/message

GitHub job 시작 로그의 `Worker ID`와 `Azure Region`도 결과 해석 때 함께 읽는다.

## 3. 원천 부하 상한

runner 1개당 NH에는 다음만 보낸다.

- resolved IP별 TCP/TLS handshake: 최대 IPv4 4개 + IPv6 2개
- 실제 NH HTTP GET: **1회** (`SFDPW0161R`만)

점포별 `SFDPW0163R` / `SFDPW0164R` 상세 수집은 하지 않는다.
따라서 10-runner 실험의 실제 NH HTTP 화면 요청은 최대 10회다.

## 4. 판정 코드

- `TARGET_HTTP_OK`: 실제 NH GET이 성공했다.
- `HTTP_LAYER_FAIL`: direct TLS까지 성공했지만 NH HTTP GET이 실패했다.
- `TLS_FAIL`: TCP는 성공했지만 TLS가 성공하지 않았다.
- `TCP_CONNECT_FAIL`: DNS는 됐지만 resolved endpoint 모두 TCP 연결에 실패했다.
- `DNS_FAIL`: NH hostname 해석부터 실패했다.
- `CONTROL_HTTP_FAIL`: 일반 인터넷 control도 실패해 NH 특이 장애라고 볼 수 없다.

## 5. 해석 기준

### A. 서로 다른 egress IP에서 NH TCP 성패가 갈림

runner/network egress 또는 중간 routing/ACL이 핵심 변수다. 코드/파서 가설은 후순위로 둔다.

### B. DNS destination IP별로 성패가 갈림

NH DNS/backend/edge 중 특정 destination 경로 문제 가능성이 커진다. egress와 destination의
조합을 같이 본다.

### C. TCP는 모두 성공하지만 TLS가 갈림

TLS/SNI/certificate 또는 중간 보안장비 계층을 다음 실험 대상으로 삼는다.

### D. direct TLS는 성공하지만 httpx GET만 실패

HTTP/WAF/User-Agent/redirect 또는 Python/httpx 경로를 다음 실험 대상으로 삼는다.

### E. 10개 모두 NH HTTP 성공

장애가 일시적이거나 특정 egress pool에 국한됐을 가능성이 있다. 다음 실제 scheduled 실패에서
fresh-runner retry 결과와 egress 정보를 추가로 수집해야 한다.

## 6. Rollout / cleanup

이 branch의 workflow는 production writer concurrency에 참여하지 않고 secrets도 사용하지 않는다.
실험 결과를 확보한 뒤 이 workflow를 main에 merge하지 않는다. 필요한 영구 telemetry만 별도
작은 PR로 다시 설계한다.
