# P1 Observability + Collection Health 준비안 — 2026-08-10

## 목표

수집을 실행한 뒤 운영자가 한 화면에서 다음을 확인할 수 있게 한다.

1. 방금/마지막으로 실행된 `Collect rates` 작업의 현재 상태
2. 각 수집원별 마지막 시도와 마지막 정상 수집 시각
3. 각 수집원의 raw / parsed / valid / warning / error 결과
4. 데이터가 예정 주기보다 오래됐는지 여부
5. 문제가 있으면 한 줄 이유와 GitHub Actions 실행 링크

현재 아키텍처를 유지하며 `collection_runs`, `collection_run_stats`, 기존 Vercel `/api/collect`와 GitHub Actions를 재사용한다.

## Current State

- `collection_runs`에는 source별 `started_at`, `finished_at`, `status`, `raw_count`, `parsed_count`, `valid_count`, `warning_count`, `error_count`, `message`, `query_context_json`이 이미 있다.
- `collection_run_stats`에는 fetched/parsed/unchanged/changed/new_variant/error가 있다.
- dashboard `sources` 카드는 현재 `observation_count > 0`이면 초록색 `수집됨`으로 표시한다. 따라서 마지막 실행이 실패해도 과거 관측이 있으면 초록색일 수 있다.
- `_stale_sources()`는 최근 실행 실패 시 직전 정상 데이터를 계속 보여주는 기능이지만, 수집 시각이 오래된 freshness와는 다른 개념이다.
- `/api/collect`는 이미 서버 쪽 GitHub token으로 `Collect rates` workflow 실행 목록을 조회하고 dispatch한다.
- 정적 사이트에는 `latest_run`, `runs`, `sources`, `stale_sources`가 이미 inline된다.

## Target State

### A. 관리자 수집 상태 패널

기존 수집 영역에 `수집 상태 확인`을 둔다. 읽기 전용 상태 조회에는 암호를 요구하지 않는다. 수집 실행 자체만 기존 암호 계약을 유지한다.

상단 요약:

```text
전체 상태       🟢 정상 / 🟡 확인 필요 / 🔴 실패·지연
마지막 작업     수동 전국 수집 #123 · 성공 · 2026-08-10 18:42 KST
현재 작업       실행중이면 진행중 / 없으면 없음
마지막 발행     2026-08-10 18:45 KST
수집원          정상 7 / 확인필요 0 / 실패 0
```

수집원 카드:

```text
🟢 농·축협
마지막 시도      2026-08-10 05:57 KST · success
마지막 정상      2026-08-10 05:57 KST
결과             raw 9,743 / valid 198,670 / warning 0 / error 0
데이터 나이      정상

🟡 새마을금고
마지막 시도      2026-08-10 06:00 KST · partial
마지막 정상      2026-08-09 08:11 KST
현재 표시값      2026-08-09 정상 수집분
이유             ...
```

### B. 두 종류의 상태를 분리

`run_health`와 `freshness`를 섞지 않는다.

- `run_health`: 마지막 실행 자체가 성공했는가
- `freshness`: 마지막 정상 수집이 예정 주기 대비 오래됐는가

최종 신호등은 둘 중 더 심각한 상태를 사용한다.

### C. 신호등 기본 계약

- GREEN
  - 마지막 attempt가 `success` 또는 `no_change`
  - actionable error 0
  - freshness 정상
- YELLOW
  - `partial`
  - fallback 사용
  - actionable warning 존재
  - 예정 주기를 넘겨 freshness 지연
- RED
  - `failed`, `blocked`, `schema_changed`
  - 마지막 정상 수집 자체가 없음
  - workflow/job 자체 실패
- GREY
  - disabled / 해당 실행에서 의도적으로 skip / publish-only

`warning_count > 0` 자체만으로 노랑으로 만들지 않는다. Warning Taxonomy에서 informational warning과 actionable warning을 먼저 분리한다.

## Warning Taxonomy와 함께 하는 이유

### 운영 R2 실측으로 확정한 INFO 패턴

- `PREFERENCE_RATE_ROW`: NH e-joy 우대금리 carrier row
- `TERM_NOT_PROVIDED`: NH 계약기간 `-` (기간은 추정하지 않음)
- `EMPTY_QUERY_RESULT`: CU 지역/상품 조회 조각의 0건 응답
- `RATELESS_SOURCE_ROW`: FSB 상품 행에 금리 필드가 없는 경우
- `OPTIONAL_FIELD_MISSING`: parser가 optional로 선언한 필드 부재

이 패턴은 INFO로 보이되 source 신호를 노랑으로 만들지 않는다. 다만 실행 전체 `parsed_count=0`은 RED로 별도 차단한다.


현재 NH `e-joy 인터넷예금 우대금리`처럼 의도된 행도 warning으로 집계된다. 단순 `warning_count`를 신호등에 쓰면 정상 수집이 항상 노란불이 된다.

다음 PR에서 최소한 다음을 구분한다.

- INFO / expected
  - preference/bonus-rate carrier row 등 정상적으로 존재하는 특수 행
- WARNING / actionable
  - 일부 페이지 schema mismatch
  - 부분 파싱/기간 불명확 등 확인 필요
- ERROR
  - parse error
  - repeated-response integrity issue
  - blocked/schema_changed/failed

가능하면 기존 `ReviewItem.issue_type`/`severity`를 재사용하고, 새로운 범용 warning-event 테이블은 만들지 않는다.

## Live workflow 상태

정적 published DB만 보면 publish 이전 실패는 사이트에 반영되지 않는다. 따라서 `/api/collect`의 기존 GitHub Actions 조회 기능을 read-only status endpoint로 확장한다.

반환 정보는 최소화한다.

- latest workflow run: run number / event / status / conclusion / started_at / html_url
- active workflow run
- latest workflow job의 source collection step별 conclusion
  - finlife_savings_bank
  - finlife_bank
  - bok_ecos
  - fsb
  - cu
  - kfcc
  - nh_local
- snapshot / validation / gate / publish 주요 단계 상태

로그·secret·token·GitHub raw response는 브라우저에 전달하지 않는다.

## Batch identity

원천별 `CollectionRun`을 한 번의 GitHub workflow 실행과 묶을 수 있게 기존 `query_context_json`에 다음 메타데이터를 저장한다. DB schema migration은 필요 없다.

- `github_run_id`
- `github_run_number`
- `github_event_name`
- `collection_batch`
  - `scheduled-core`
  - `scheduled-kfcc`
  - `manual`
- scope / skip 정보는 기존 request context와 함께 유지

이 값은 GitHub Actions env에서 collection CLI까지 전달한다.

## Freshness

`generated_at`, `last_attempt_at`, `last_success_at`, `source_effective_at`을 구분한다.

초기 freshness 판정은 source schedule을 기준으로 하고, 임의의 24시간 magic number를 UI에 박지 않는다. 평일 수집과 split schedule을 고려한다.

## 구현 경계

- implementation branch: `agent/p1-collection-health`
- DB schema migration: 없음
- live status: read-only `/api/health`
- batch identity metadata: deferred — 이번 PR은 GitHub workflow 상태와 DB source 상태를 읽기 전용으로 병렬 표시하며 CLI/수집 계약은 바꾸지 않음


P1 PR 1 — `Collection Health + Warning Taxonomy`

- source별 latest attempt / latest success summary
- warning reason/severity 정리
- health 계산 함수
- `/api/collect` read-only live status
- 관리자 상태 패널/신호등
- workflow batch metadata를 `query_context_json`에 기록
- dashboard/site UI tests
- endpoint tests
- 실제 실패/partial/success fixture 검증

P1 PR 2 — UI polish

- `권역` → `업권`
- 필요 시 문구/레이아웃 보정

## 검증

1. unit tests: success / no_change / partial / failed / blocked / schema_changed / no-success / stale
2. endpoint tests: GitHub API success/failure/active/no-run, response sanitization
3. dashboard build + site build
4. existing P1-A gate 유지
5. production R2 copy에서 source별 health 결과 대조
6. 가능하면 manual 부산 수집으로 `running → completed → published` 전환 확인
7. adversarial review

## 비목표

- 새 관리자 인증체계 도입
- 별도 상태 DB/Redis 도입
- GitHub Actions 로그 전체 노출
- scheduler 구조 변경
- 자동 재시도/자동 장애복구
