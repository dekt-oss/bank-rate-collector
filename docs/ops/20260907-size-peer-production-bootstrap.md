# Size Peer total-assets production bootstrap — 2026-09-07

## 목적

PR #312에서 검증된 Size Peer `total_assets` writer는 `workflow_dispatch`/월간 schedule 경로만 갖고 있어 PR validation 이후 authoritative R2에 최초 seed가 아직 없었다. PR #313 production-copy QA는 이 상태를 `common_financial_month_missing`으로 fail-closed 확인했다.

현재 연결된 개발 도구에는 GitHub `workflow_dispatch` 시작 기능이 없으므로, 기존 승인 workflow 파일 자체가 `main`에 merge되는 순간에만 동작하는 좁은 `push` trigger를 임시로 추가한다.

## 안전 경계

- collector/parser/identity/persistence 코드는 변경하지 않는다.
- 검증된 공통 기준월 `202512`를 그대로 사용한다.
- `rate-data-writer` concurrency와 `queue: max`를 유지한다.
- PR 이벤트에서는 authoritative R2 upload가 계속 skip된다.
- main push에서만 기존 workflow의 기존 validation → snapshot → R2 upload → byte-for-byte restore gate를 그대로 수행한다.
- bootstrap 성공 후 `push` trigger와 전용 bootstrap test는 즉시 제거한다.

## 완료 조건

1. non-PR `수집 — Size Peer 총자산` run 성공.
2. `financial_as_of=2025-12` pair-complete readback 성공.
3. 고려저축은행 `deposit_liabilities_total=1804862`, `total_assets=2059073` million_krw 확인.
4. authoritative R2 upload 후 byte-for-byte restore 성공.
5. R2 재복원 Strategy payload에서 REMOTE/BRANCH_BUSAN Size Peer가 `ready`이고 display rows가 존재.
6. desktop/mobile Strategy browser smoke 성공.
7. 완료 후 temporary `push` trigger 제거.

## 장애 처리

Data.go TLS handshake timeout이면 동일 run을 무한 재시도하지 않는다. source 내부 bounded retry 소진 후 workflow는 실패로 남긴다. fresh GitHub-hosted runner 재시도는 최대 1회만 허용하고, 재실패 시 transport/reliability를 별도 Evidence Gate로 분석한다.
