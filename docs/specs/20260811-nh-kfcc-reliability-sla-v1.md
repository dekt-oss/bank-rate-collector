# 금리수집기 NH/KFCC 수집 신뢰성·08:00 SLA 개선 작업명세서 v1.0

- status: `planned / implementation-hold`
- date: `2026-08-11`
- base: `main @ a850560647b4c1e3e0b739979a5cddba5c1fd874`
- trigger: 2026-08-11 `nh_local` connection failure + KFCC 08:00 이후 완료 확인
- purpose: 평일 정기수집을 08:00 KST 이전에 완료하도록 스케줄을 재설계하고, NH의 일시적 네트워크 오류 1회가 하루치 전국 수집 실패로 직결되지 않도록 bounded retry/진단성을 추가한다.
- implementation policy: 기존 collector / canonical DB / R2 / rate-data / static publish 구조를 유지한다. 신규 DB나 병렬 writer를 만들지 않는다.
- execution state: **문서만 준비한다. 현재 진행 중인 다른 작업이 끝난 뒤 최신 `main`을 다시 확인하고 구현을 시작한다.**

---

## 0. 작업 성격과 결론

별도 기획서는 만들지 않는다.

이 작업은 신규 제품 기능이 아니라 **이미 운영 중인 수집 파이프라인의 장애 내성과 마감시간(SLA) 보강**이다. 제품 방향을 새로 정할 필요가 없고, 요구사항도 다음 두 가지로 명확하다.

1. 모든 평일 정기 수집과 검증·저장·발행은 **08:00 KST 이전**에 끝나야 한다.
2. NH처럼 장시간 걸리는 핵심 수집원이 일시적인 `ConnectError` 1회 때문에 하루 전체 수집을 포기해서는 안 된다.

따라서 이 문서를 구현 기준 작업명세서로 사용한다.

기존 `docs/roadmap.md`의 **O4 수집 runtime / reliability 최적화** 트랙을 구체화하는 후속 명세다. Stabilization v1에서 이미 완료된 기능을 다시 만들지 않는다.

---

## 1. Source of Truth / 현재 확인된 증거

### 1.1 현재 정기 실행 구조

현재 `.github/workflows/collect.yml`은 평일 수집을 두 번으로 나눈다.

```text
02:00 KST  core run
            KFCC 제외 전부
            finlife_savings_bank
            finlife_bank
            bok_ecos
            fsb
            cu
            nh_local

06:00 KST  KFCC-only run
```

두 실행은 동일한 `concurrency: rate-data-writer`를 사용하며 `cancel-in-progress: false`다. 기존 목적은 GitHub Actions 단일 job 6시간 한도를 피하면서 R2 canonical DB에 **single writer**로 직렬 반영하는 것이다.

이 구조 자체는 유지한다.

### 1.2 2026-08-11 NH 장애

8/11 core run에서 NH는 다음과 같이 실패했다.

```text
started_at  2026-08-11 03:03:55 KST
finished_at 2026-08-11 03:03:56 KST
status      failed
raw         0
parsed      0
valid       0
message     All connection attempts failed
```

직전 8/10 전국 수집은 정상이다.

```text
started_at  2026-08-10 02:41:53 KST
finished_at 2026-08-10 06:10:16 KST
parsed      198,670
valid       198,670
status      success
```

따라서 현재 증거가 지지하는 범위는 다음과 같다.

- 파서가 깨진 증거 없음
- 원천 HTML 구조 변경 증거 없음
- DB 저장 오류 증거 없음
- 명시적 403/429 차단 증거 없음
- **첫 HTTP 연결 단계에서 응답 자체를 받지 못한 transient/network-class failure**

현재 `NhLocalAdapter._get()`은 `client.get()` 실패에 대한 재시도 계층이 없다. 첫 명부 요청이 실패하면 전국 수집 전체가 즉시 끝난다.

### 1.3 2026-08-11 KFCC 상태

8/11 KFCC-only run은 정상 완료했다.

```text
started_at  2026-08-11 06:36:00 KST
finished_at 2026-08-11 08:51:50 KST
raw         2,477
parsed      93,382
valid       93,382
warning     0
error       0
status      success
```

후속 단계도 정상이다.

```text
stored validation   PASS 12/12
P1-A gate            PASS 27/27
R2 upload            PASS
size gate            PASS
volume gate          PASS
rate-data publish    PASS
```

즉 현재 KFCC 수집기 자체는 정상이다. 문제는 **06:00 예정 스케줄이 08:00 SLA를 만족시키지 못한다는 것**이다.

### 1.4 과거 KFCC partial gate 장애는 이미 해결됨

8/10에는 KFCC 수집 자체는 성공했지만 KFCC-only workflow가 현재 run에 존재하지 않는 Finlife raw까지 요구하면서 final gate에서 막힌 적이 있다.

이 문제는 이미 기존 PR에서 Current Run Gate / Historical Integrity Gate를 분리해 수정됐고, 8/11 KFCC-only 실제 실행에서 27/27 gate 통과까지 확인됐다.

**이 명세에서 해당 검증 로직을 다시 구현하거나 완화하지 않는다.**

다만 KFCC-only에서 Finlife current-run raw가 없어도 정상 통과하는 회귀 테스트는 계속 보존한다.

### 1.5 운영 상태판은 이미 존재

현재 main에는 이미 다음이 있다.

- source별 latest attempt / latest success / freshness
- warning taxonomy
- `/api/health`
- 공개 화면 수집 상태 신호등
- failed run 후 직전 정상 데이터를 유지하면서 RED/stale로 표현

따라서 새 health DB나 별도 상태 저장소를 만들지 않는다.

이번 작업은 **기존 상태판이 새 SLA와 retry 결과를 정확히 표현하도록 계약을 조정**하는 범위다.

---

## 2. Target State

### 2.1 운영 SLA

평일 정기 수집의 목표는 다음과 같이 고정한다.

```text
정상 목표      모든 scheduled source publish 완료 ≤ 07:30 KST
경고 구간      07:30 < 완료 < 08:00 KST
Hard Deadline  08:00 KST
SLA 실패       08:00 KST까지 완료하지 못함
```

여기서 `완료`는 collector만 끝난 시각이 아니다.

```text
수집
→ snapshot
→ stored-data validation
→ dashboard/export/public-site build
→ P1-A gate
→ R2 canonical state upload
→ size/volume gate
→ rate-data publish
```

까지 끝난 시점을 의미한다.

### 2.2 scheduled source 범위

평일 schedule에 포함된 모든 실제 수집원을 대상으로 한다.

- `finlife_savings_bank`
- `finlife_bank`
- `bok_ecos`
- `fsb`
- `cu`
- `nh_local`
- `kfcc`

명시적으로 skip된 수동 실행은 SLA 대상에서 `N/A`로 처리한다.

### 2.3 실패 시 데이터 정책

원천 실패가 발생해도 직전 confirmed 데이터는 유지한다.

```text
오늘 수집 실패
→ 이전 정상 observation 보존
→ 최신 attempt = failed
→ latest success = 이전 날짜
→ stale 표시
→ aggregate health = degraded / red 포함
```

금리 표를 0건으로 덮어쓰지 않는다.

반대로 과거 데이터가 남아 있다는 이유로 오늘 실패를 정상으로 표현하지 않는다.

### 2.4 GitHub workflow 전체 success와 source success 분리

한 원천 실패 때문에 다른 정상 원천의 발행까지 버리는 정책으로 바꾸지 않는다.

따라서 `continue-on-error` 성격은 유지할 수 있다. 다만 운영 판정은 반드시 source별 상태를 기준으로 한다.

```text
workflow publish 성공 + NH failed
= 전체 정상 아님
= published-but-degraded
```

새 DB 상태값이 꼭 필요한 것은 아니다. 기존 source health 집계에서 위 의미를 일관되게 표현하면 된다.

---

## 3. P0-1 — 08:00 SLA 기준 스케줄 재설계

### 3.1 Current

```text
02:00 core
06:00 KFCC-only
```

현재 workflow 주석의 실측 예산:

```text
core(KFCC 제외)  약 3시간 57분
KFCC 전국         과거 약 2시간 06분
```

8/11 KFCC 실제 소요는 약 2시간 16분이었다.

따라서 06:00에 KFCC를 시작하면 GitHub queue 지연이 전혀 없어도 08:00 직전/이후가 된다. 실제 8/11에는 06:36에 시작해 08:51에 수집이 끝났다.

### 3.2 Target schedule

1차 구현 후보는 다음으로 고정한다.

```text
00:17 KST  core scheduled event
04:17 KST  KFCC-only scheduled event
```

UTC cron:

```yaml
# 월~금 00:17 KST = 전날 일~목 15:17 UTC
- cron: "17 15 * * 0-4"

# 월~금 04:17 KST = 전날 일~목 19:17 UTC
- cron: "17 19 * * 0-4"
```

정각 `:00`을 피한다. 단, GitHub schedule은 hard real-time scheduler가 아니므로 이 변경만으로 절대적 시간 보장을 주장하지 않는다. 실제 SLA 준수 여부는 scheduled runtime evidence로 판정한다.

### 3.3 시간 예산

설계 예산은 보수적으로 다음을 사용한다.

```text
core 정상 예산       4시간 15분
KFCC 정상 예산       2시간 30분
후처리/발행 예산       15분
GitHub queue 지연 흡수  최대 약 45분을 운영 margin으로 관찰
```

`rate-data-writer`가 single writer이므로 core가 늦으면 KFCC는 뒤에서 기다린다. 이 특성을 이용해 **병렬 writer 없이 시작시각만 충분히 앞당긴다.**

### 3.4 금지

이번 P0에서 하지 않는다.

- NH/KFCC를 별도 DB writer로 동시에 실행
- 같은 R2 canonical snapshot에 concurrent write
- 수집시간 단축을 이유로 source request pacing을 무근거하게 올림
- GitHub 6시간 제한을 무시하고 다시 한 job에 전부 합침

### 3.5 Acceptance Criteria

- workflow cron과 `KFCC_ONLY` / `SKIP_KFCC_THIS_RUN` 조건 문자열이 정확히 함께 변경된다.
- 기존 schedule-contract test를 새 cron에 맞게 수정한다.
- core/KFCC는 계속 single writer로 직렬화된다.
- publish-only main push 동작은 변하지 않는다.
- 최소 3개 연속 평일 실제 scheduled run에서 최종 publish가 08:00 이전이다.
- 정상 목표는 07:30 이전으로 평가한다.

---

## 4. P0-2 — NH bounded retry

### 4.1 Current

NH의 logical GET은 사실상 한 번 실행된다.

```python
response = await client.get(...)
```

`ConnectError`, `ConnectTimeout`, `ReadTimeout` 같은 transient failure가 발생해도 즉시 source 전체가 실패한다.

### 4.2 Target

retry는 **idempotent GET + transient failure**에만 제한적으로 적용한다.

#### A. 전국 명부 preflight

첫 명부는 전국 수집 전체의 전제조건이므로 별도 preflight로 취급한다.

권고 정책:

```text
attempt 1  즉시
attempt 2  + 5초
attempt 3  +20초
attempt 4  +60초
```

jitter는 작은 범위에서 추가할 수 있다. 정확한 값은 test가 가능하도록 상수/주입 가능한 정책으로 둔다.

#### B. 점포 상세 요청

점포별 금리 GET은 다음 정도로 제한한다.

```text
attempt 1  즉시
attempt 2  + 3초
attempt 3  +12초
```

#### C. 전체 retry budget

전국 NH는 약 9천 회 이상 요청한다. 원천 장애가 길게 이어질 때 모든 요청을 3배로 보내면 안 된다.

따라서 한 collection run의 **추가 retry request 총량에 상한**을 둔다.

초기 구현 기준:

```text
MAX_TOTAL_RETRIES = 50
```

상한을 넘으면 source를 실패 처리하고 더 이상 원천을 두드리지 않는다.

### 4.3 Retry 대상

초기 계약:

```text
RETRY
- httpx.ConnectError
- httpx.ConnectTimeout
- httpx.ReadTimeout
- httpx.RemoteProtocolError
- HTTP 500 / 502 / 503 / 504
```

구현 시 현재 httpx exception hierarchy를 확인하고 테스트로 고정한다.

### 4.4 Retry 금지

다음은 자동 재시도하지 않는다.

```text
NO RETRY
- 400
- 401
- 403
- 404
- 429
- BLOCK_MARKERS 감지
- SourceBlockedError
- SchemaChangedError
- parse/normalization error
- 명백한 요청 파라미터 오류
```

특히 차단 징후를 retry로 우회하지 않는다.

### 4.5 기존 pacing 보존

현재 source-friendly request pacing을 유지한다.

```text
REQUEST_INTERVAL_SECONDS = 1.0
```

retry가 들어가도 정상 요청의 간격을 줄이지 않는다. backoff는 이 간격에 추가되는 지연이다.

### 4.6 Acceptance Criteria

- 첫 `ConnectError` 후 다음 시도에서 성공하면 source run이 정상 계속된다.
- preflight가 4회 모두 transient 실패하면 clean failed run으로 끝난다.
- detail request가 transient failure 후 성공하면 해당 logical request는 1개 artifact만 만든다.
- 403/429/block marker에는 retry하지 않는다.
- retry budget 초과 시 source를 fail-closed한다.
- 재시도로 인해 duplicate observation/raw contract가 깨지지 않는다.
- retry count/reason이 운영 로그 또는 run stats에서 확인 가능하다.

---

## 5. P0-3 — NH 오류 분류와 진단성

### 5.1 문제

현재 `All connection attempts failed`만으로는 다음을 구별하기 어렵다.

- DNS
- TCP connect
- TLS/connect timeout
- read timeout
- HTTP 5xx
- source block

### 5.2 Target taxonomy

적어도 다음 수준으로 구조화한다.

```text
NETWORK_CONNECT
NETWORK_TIMEOUT
NETWORK_PROTOCOL
HTTP_SERVER_ERROR
SOURCE_BLOCKED
SCHEMA_CHANGED
PARSE_FAILED
VALIDATION_FAILED
RETRY_BUDGET_EXHAUSTED
```

DNS를 httpx가 별도 안정적으로 노출하지 않는 환경에서는 억지로 `NETWORK_DNS`로 단정하지 않는다. 실제 exception chain에서 구별 가능한 경우에만 세분화한다.

### 5.3 로그 필드

retry 가능한 실패는 최소 다음을 남긴다.

```text
source_id
phase            # preflight / detail
screen
attempt
max_attempts
error_class
http_status      # 있으면
retry_delay
```

민감정보/쿠키/토큰은 넣지 않는다.

### 5.4 사용자 화면

개발자 exception 문자열을 그대로 공개하지 않는다.

예:

```text
농·축협 — 원천 서버 연결 실패
마지막 정상 수집 08/10 06:10
현재 08/10 데이터 사용 중
```

기존 health panel을 재사용한다.

---

## 6. P0-4 — SLA/freshness 상태 계약 정렬

Stabilization v1의 health UI는 이미 구현돼 있다. 하지만 당시 expected completion은 기존 02:00/06:00 schedule을 기준으로 잡혀 있다.

이번 스케줄 변경과 함께 다음을 정렬한다.

### 6.1 완료시각 기준

source freshness와 별도로 전체 scheduled cycle의 publish 완료시각을 확인할 수 있어야 한다.

권고 derived fields 또는 동등한 계산:

```text
cycle_date_kst
scheduled_sources
latest_publish_completed_at
sla_deadline_at = 08:00 KST
sla_status = normal | warning | breached
```

새 DB column을 만들 필요는 없다. 현재 summary/health 생성 시 계산할 수 있으면 derived 값으로 둔다.

### 6.2 source 상태

각 source는 계속 다음을 분리한다.

```text
latest attempt
latest successful collection
current confirmed data
freshness
```

NH처럼 오늘 failed + 어제 success인 경우 RED/stale가 유지되어야 한다.

### 6.3 Acceptance Criteria

- 07:30 이전 전체 publish → normal
- 07:30~08:00 → warning
- 08:00 이후 또는 미완료 → breached/red
- source 실패가 하나라도 남아 있으면 전체 cycle을 완전 정상으로 표시하지 않는다.
- 사이트 생성시각만 갱신됐다고 source freshness가 새로워지지 않는다.

---

## 7. P0-5 — KFCC partial-run 회귀 보호

현재 동작은 정상이다. 구현 목표는 **보존**이다.

반드시 지킬 테스트:

```text
KFCC_ONLY=true
Finlife current-run raw 없음
historical Finlife observation 있음

→ Finlife current-run semantic check는 명시적 skip
→ historical integrity는 계속 검사
→ KFCC raw/observation 검증은 계속 수행
→ valid run이면 publish gate PASS
```

금지:

- gate 자체 삭제
- historical integrity 완화
- 모든 missing raw를 무조건 skip

---

## 8. P1 — KFCC 사용자 표시명 정리

현재 adapter의 기술적 `source_name`은:

```text
새마을금고 금고위치안내
```

실제 수집은 위치정보만 받는 것이 아니라 `/map/list.do`로 금고 목록을 얻은 뒤 `/map/goods_19.do`의 금고별 예탁금 금리 화면을 수집한다.

사용자-facing label은 기술적 진입 페이지명을 그대로 노출하지 않는다.

권고:

```text
표시명: 새마을금고 예·적금 금리
출처 설명: 새마을금고 공식 홈페이지 금고위치안내/금리조회
```

DB/source_id(`kfcc`)나 provenance/reference는 변경하지 않는다.

이 변경은 저위험이지만 P0 신뢰성 수정과 별도 커밋 또는 별도 작은 PR로 분리해도 된다.

---

## 9. 자동 full recovery는 이번 P0에서 제외

이번 장애를 보고 바로 "농협 전체를 몇 시간 뒤 다시 한 바퀴" 돌리는 cron을 추가하지 않는다.

이유:

1. 전국 NH는 약 3.5시간 이상 걸린다.
2. KFCC도 약 2시간 이상 걸린다.
3. 현재 `rate-data-writer`는 single writer다.
4. recovery run을 별도 schedule로 추가하면 pending concurrency 순서와 08:00 SLA가 다시 복잡해진다.
5. 원천 부하도 증가한다.

우선 **request-level bounded retry + preflight**로 transient failure를 흡수한다.

그 후 실제 장애 통계를 모아 필요할 때 다음 중 하나를 별도 설계한다.

```text
A. resumable NH checkpoint
B. source-only recovery run + deterministic merge
C. independent fetch artifact → single writer merge
```

근거 없이 자동 full rerun을 추가하지 않는다.

---

## 10. 구현 PR 분리 계획

이 문서 PR은 **문서-only Draft PR**이다. 코드 구현은 현재 진행 중인 다른 작업이 끝난 뒤 시작한다.

구현 시 최신 main을 다시 확인하고 아래 순서로 작은 PR을 권고한다.

### PR A — NH Transient Resilience

범위:

```text
P0-2 bounded retry
P0-3 error taxonomy / retry telemetry
unit/fixture tests
```

변경 예상:

- `src/rate_monitor/collectors/nh_local/adapter.py`
- 필요 시 작은 retry helper
- NH collector tests

DB/schema 변경 없음.

### PR B — 08:00 Collection SLA

범위:

```text
P0-1 schedule 변경
P0-4 health/SLA expected time 정렬
P0-5 KFCC partial regression 확인
```

변경 예상:

- `.github/workflows/collect.yml`
- schedule contract tests
- dashboard/health derived status 관련 최소 파일

single writer 구조 유지.

### PR C — Source Label Cleanup

범위:

```text
P1 KFCC 사용자 표시명
```

다른 UI 변경과 섞지 않는다.

---

## 11. Verification Plan

### 11.1 PR A — 코드 테스트

필수 test matrix:

```text
preflight ConnectError → retry → success
preflight ConnectTimeout → final failure
preflight 503 → retry → success
detail ReadTimeout → retry → success
403 → no retry
429 → no retry
block marker → no retry
retry budget exhausted → fail
retry success → duplicate artifact 없음
```

필수 정적 검증:

```text
ruff
full pytest
migration-from-empty (schema 미변경 확인 포함)
git diff --check
```

가능하면 외부 원천에 과도한 요청 없이 **명부 endpoint 1회 수준의 live probe**로 current connectivity도 확인한다. 전국 실수집은 테스트만을 위해 반복하지 않는다.

### 11.2 PR B — schedule/health 테스트

필수:

```text
cron 문자열 ↔ KFCC_ONLY 조건 일치
cron 문자열 ↔ SKIP_KFCC_THIS_RUN 조건 일치
main push = publish-only 유지
manual workflow_dispatch contract 유지
source freshness 계산 회귀
07:30 / 08:00 SLA boundary test
KFCC-only gate regression
```

### 11.3 실제 운영 검증

코드/CI 통과만으로 완료 판정하지 않는다.

merge 후 다음 scheduled cycle에서 확인한다.

```text
core event 실제 시작시각
NH 시작/종료시각
KFCC event 실제 시작시각
KFCC 종료시각
R2 upload 완료시각
rate-data publish 완료시각
production smoke 결과
```

최소 완료 조건:

- 실제 평일 scheduled cycle 1회에서 08:00 이전 publish PASS
- 이후 3개 연속 평일에 08:00 위반 0회
- source별 unexpected failure 0 또는 원인이 구조화되어 확인 가능
- production smoke PASS

3일 관찰 전에는 "장기 안정화 완료"라고 과장하지 않는다.

---

## 12. Adversarial Self-Review Checklist

구현자가 반드시 반대로 가정하고 확인한다.

### Retry

- retry가 장애를 숨기고 있지 않은가?
- 403/429/차단을 transient로 오인하지 않았는가?
- 전국 장애 때 원천을 수십 배 두드리게 만들지 않았는가?
- retry 후 duplicate raw/observation이 생기지 않는가?

### Schedule

- KST↔UTC 요일 계산을 하루 틀리지 않았는가?
- cron 값과 `github.event.schedule` 비교문을 한쪽만 바꾸지 않았는가?
- core가 늦을 때 KFCC가 취소되지 않고 single writer 규칙을 지키는가?
- 08:00을 collector 종료로 잘못 판정하고 publish 시간을 놓치지 않았는가?

### Health

- workflow 전체 success만 보고 source failure를 숨기지 않는가?
- stale 데이터를 최신처럼 표시하지 않는가?
- main publish-only가 source freshness를 갱신하지 않는가?

### KFCC

- 이미 해결된 partial gate를 다시 건드려 검증 강도를 낮추지 않았는가?
- 사용자 표시명 변경이 `source_id=kfcc` identity를 바꾸지 않는가?

---

## 13. Rollback

### NH retry

문제 발생 시 retry helper/정책만 revert해 기존 단발 요청으로 복귀할 수 있어야 한다. DB migration이 없으므로 data rollback은 필요하지 않아야 한다.

### Schedule

새 cron이 예상치 못한 운영 문제를 만들면 이전 02:00/06:00 값으로 되돌릴 수 있다. 단, 이전 schedule은 08:00 SLA를 만족하지 못하는 상태임을 명시한다.

### Health/UI

derived SLA 표시 변경은 기존 source health 데이터 계약을 깨지 않는 범위에서 revert 가능해야 한다.

---

## 14. 최종 Acceptance Criteria

작업 완료 판정은 아래 전부가 충족될 때만 한다.

### NH 신뢰성

- [ ] transient network failure에 bounded retry가 적용됨
- [ ] block/4xx는 무근거 retry하지 않음
- [ ] retry budget/circuit protection 존재
- [ ] retry/error reason이 구조화되어 확인 가능
- [ ] 기존 1 req/s source-friendly pacing 보존
- [ ] duplicate raw/observation 없음

### 08:00 SLA

- [ ] core schedule이 자정 직후로 이동
- [ ] KFCC schedule이 04시대로 이동
- [ ] cron/조건문 contract test PASS
- [ ] 07:30 normal / 08:00 hard deadline이 health에 반영
- [ ] 수집+검증+R2+rate-data publish까지 완료시각으로 판정
- [ ] 실제 scheduled run이 08:00 이전 완료

### 기존 계약 보존

- [ ] R2 canonical state 유지
- [ ] rate-data publish 유지
- [ ] single writer 유지
- [ ] RawArtifact/provenance 유지
- [ ] failed run observation 미반영 유지
- [ ] stale fallback 유지
- [ ] KFCC partial gate 회귀 없음
- [ ] main push publish-only 유지

### 운영 확인

- [ ] production smoke PASS
- [ ] source health가 실패를 숨기지 않음
- [ ] 최소 3개 연속 평일 SLA 위반 0회 확인
- [ ] 미검증 사항을 최종 보고에 명시

---

## 15. 구현 대기 규칙

이 Draft PR에서는 **코드를 수정하지 않는다.**

실제 구현을 시작하기 직전에 반드시 다시 수행한다.

1. 최신 `main` 확인
2. 현재 진행 중인 작업/PR/Issue 확인
3. `.github/workflows/collect.yml` 최신 schedule/concurrency 확인
4. `nh_local` adapter 최신 retry/timeout 상태 확인
5. health/dashboard 최신 계약 확인
6. 이 문서와 충돌하는 새 결정이 있으면 문서를 먼저 갱신
7. 그 뒤 PR A부터 구현

현재 작업이 끝나기 전에 이 branch에서 기능 코드를 선행 구현하지 않는다.
