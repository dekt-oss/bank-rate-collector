# 신협(CU) 금리 수집 장애 감사 — 2026-09-08 ~ 09-13

작성 2026-09-13. 근거는 GitHub Actions 실행 로그, 각 실행이 남긴 `collection-run-*`
artifact(원본 JSON, `publish/summary.json`, `publish/manifest.json`), `rate-data`
브랜치의 발행본, 그리고 2026-09-13 00시대의 원천 직접 조회다.

## 1. 타임라인 (KST)

`raw`는 원본 응답 장수, `parsed`는 파싱된 금리 행 수다. "정상"은 702장/약 30,500행이다.

| KST 시각 | GitHub run | event | CU collection_run | CU status(DB) | raw | parsed | workflow | 발행 | 화면 신협 행 | 실제 판단 |
|---|---|---|---|---|---|---|---|---|---|---|
| 09-08 01:57→02:17 | 34142171780 | dispatch | 6089978d | success | 702 | 30,511 | success | O | 30,511 | 정상 |
| 09-08 04:14→04:17 | 34154533396 | schedule | 59a4a209 | **success** | 136 | **0** | failure | X (volume gate 급감 30,511→0) | 유지 | **원천 빈 응답 창. 0건이 success로 기록됨** |
| 09-08 08:56→09:16 | 34157596177 | dispatch | 4397111a | success | 702 | 30,502 | failure | X (stale-main writer guard) | 유지 | 수집은 정상, 발행 차단 |
| 09-08 17:02→17:22 | 34194221917 | dispatch | b3652e22 | success | 702 | 30,502 | success | O | 30,502 | 정상 |
| 09-09 03:46→04:01 | 34264537898 | schedule | aff0f58b | **success** | **550** | **22,257** | success | **O** | **22,257** | **04:00 이후 39장 `[]`로 잘림(73%). 게이트 비교 대상 누락으로 통과·발행** |
| 09-10 03:41→04:00 | 34390154613 | schedule | 16f71c11 | success | 702 | 30,495 | success | O | 30,495 | 04:00 직전 완료 |
| 09-10 22:20→22:40 | 34481585806 | dispatch | bcdb3f8b | success | 702 | 30,483 | success | O | 30,483 | 정상 |
| 09-11 04:11→04:14 | 34518603334 | schedule | 90bf4f9c | **success** | 136 | **0** | success | **O** | **0** | **136장 전부 `[]`. 게이트 "비교할 직전 실행 없음"으로 통과. 신협 0건 화면 발행** |
| 09-11 04:57 (UTC 19:57) | 34523472120 | recovery | — | — | — | — | success | — | — | soft-recovery가 CU status=success를 보고 `target_count=0`, 재실행 없음 |
| 09-11 15:30→15:50 | 34570033002 | dispatch | 7b7b466d | success | 702 | 30,482 | success | O | 30,482 | 은행권 경량 수집 실패의 복구 dispatch로 **우연히** 회복 |
| 09-11 16:17 UTC 이후 | — | schedule | — | — | — | — | **미실행** | — | 30,482 (stale) | **정기 실행 자체가 발생하지 않음** (09-11 08:30 NH, 08:40 KFCC, 16:17 일반, 09-12 fast 2회 모두 누락) |

발행본 `table_rows`: 정상 437,997 / 09-09 429,945 / 09-11 04:20 407,515 — 차이가 신협 행 수와 같다.
발행 DB `manifest.json`은 매번 `integrity_check ok`, FK 위반 0이었다. **DB가 깨진 것이 아니라
"성공한 0건"이 화면을 비운 것이다.**

## 2. 원인

### 2.1 원천: 04:00 KST 전후 빈 응답 창

- 요청 계약은 화면과 동일하다. 2026-09-13 00:16 KST 브라우저 실측 POST 본문
  `currPage, listMaxCnt, highLimtAmt=10,000,000, monTy, sido=AA, subSido=AA, tretChlTy=A,
  sortColumn=CU_NM, sortAsc=A, searchTxt=` — 어댑터의 `_rate_body`와 같다. CSRF·토큰·
  추가 쿠키 없음(`JSESSIONID`, `TS0147463f`뿐). endpoint 변경 없음.
- 같은 어댑터 코드로 2026-09-13 00:16~00:42 KST 로컬 조회: 4/4 조합 모두 50행 정상
  (서울 12개월 726건, 부산 280건 등).
- 09-09 실행의 원본 550장을 조회 순서로 보면 `findInrst17` 시도 09부터 끝까지 전부 `[]`다.
  실행 종료 04:01, 요청 간격 1초 → 약 04:00:20부터 빈 응답이 시작됐다. 09-10 실행은
  04:00에 끝나 정상, 09-08·09-11 실행은 04:11~04:17에 통째로 빈 응답이었다.
- 즉 조건 문제가 아니라 원천이 특정 시간대에 조건과 무관하게 `[]`를 준다. 창의 길이는
  미실측이다(`미검증`).

### 2.2 스케줄 지연이 그 창에 실행을 밀어 넣었다

정기 수집 cron은 01:17 KST인데 GitHub가 2시간 51분~4시간 47분 늦게 시작시켰다
(09-10 19:08 UTC, 09-11 05:39·10:47 UTC). 그래서 실행이 04:00 창에 걸렸다.

### 2.3 코드: 0건·잘림을 success로 판정

- `collection_service._process`는 `errors == 0 and not schema_failures and not alert`면
  SUCCESS다. 파싱 0건이어도 예외가 없으면 성공이었다.
- `RepeatGuard`는 `screen/sido` 축마다 연속을 세는데 기간이 4개뿐이라 최장 연속이 4로
  끝나 136장 동일 응답을 잡지 못했다(한도 40).
- 발행 게이트 `scripts/volume_gate.py`는 `summary.runs`(전체 최근 10개)에서 직전 실행을
  찾는다. 09-11 04:14에는 Data.go 수신잔액 4회가 창을 차지해 신협 직전 실행이 없었고
  "비교할 직전 실행이 없다. 건너뛴다"로 통과했다. 09-09에는 신협이 아예 비교 목록에
  없었다(22,257/30,502 = 73%였으므로 있었다면 막혔다).
- 화면은 원천별 **마지막 성공 실행**의 관측만 보여준다(`latest_run_ids`). 0건 실행이
  success이면 신협 행이 통째로 사라진다.
- soft-recovery(`scripts/scheduled_soft_failure_recovery.py`)도 status가 success면 확인된
  것으로 봐 재실행하지 않았다.

### 2.4 화면의 신협 RED 카드는 다른 원천이었다

09-11 화면의 "신협중앙회 경영공시 요약재무현황 — 실패·지연, 예정 수집 3회 지연"은
`cu_disclosure_funding`(월 단위 공시, 매월 2일 01:17 KST 수집)이 평일 주기로 재어진
것이다. 마지막 정상 09-08 23:44 이후 아무 실패도 없었다.

## 3. 수정 (PR #329 위에 추가)

1. 저장 전 source volume gate (`source_volume_contract`, `collection_service`)
   - parsed=0 → `SOURCE_EMPTY_RESULT` FAILED, 전국 하한 미달 → `SOURCE_VOLUME_BELOW_MINIMUM`
     FAILED (PR #329).
   - 추가: 직전 정상 전국 실행 대비 75% 미만 → `SOURCE_VOLUME_DROP` FAILED. 기준선은 DB의
     같은 원천 마지막 정상 전국 실행(`query_context_json`으로 범위 판정). workflow의
     `accept_volume_drop` 입력(`RATE_MONITOR_ACCEPT_VOLUME_DROP`)은 이 비교만 푼다.
   - FAILED 실행은 원본·실행·검수항목만 남기고 관측을 쓰지 않는다. 이전 정상 관측은 닫히지
     않고 화면에 남는다. preflight 파싱 결과를 저장 단계가 재사용해 두 번 파싱하지 않는다.
2. 신협 어댑터: 1페이지가 비면 카나리(같은 화면, 서울 12개월)로 원천 전체가 비었는지 가르고,
   비었으면 5분 대기 후 세션을 새로 받아 같은 조회를 반복한다(최대 60분). 상한을 넘으면
   빈 응답을 그대로 기록해 게이트가 FAILED로 끝낸다. 우회가 아니라 대기다.
3. 발행 게이트: `summary.source_run_history`(원천별 확인 실행 2개)를 먼저 본다. `runs`에
   `raw_count`를 실어 soft-recovery가 "success인데 raw>0/parsed=0"을 실패로 본다.
4. 재실행 경로 단일화: `recover-failed-scheduled-collection.yml` 하나만 정기 실행 실패를
   1회 재실행한다(재실행은 workflow_dispatch라 다시 재실행되지 않는다). PR #329의
   `source-health-watch.yml`에 있던 별도 "신협만" dispatch는 같은 이벤트에 두 번 재실행하는
   중복이라 제거했다. 감시 workflow는 canonical DB read-only + GitHub Issue 동기화만 하고,
   수동 실행(`workflow_dispatch`)으로 운영 증거를 출력할 수 있다.
5. 상태 화면: 실패 카드에 실행 메시지(`실패 원인 SOURCE_EMPTY_RESULT: cu 전국 파싱 건수
   0건이 …`)와 parsed 수를 표시한다. `cu_disclosure_funding`은 월 주기로 최신성을 잰다.

## 4. 데이터 손상 여부

- 관측 삭제·중복 생성 없음. 0건 실행은 관측을 만들지 않았고 기존 관측의 `valid_to`도
  건드리지 않았다(관측 수: 09-09 7,122,642 → 09-11 04:20 7,990,956 → 09-11 20:02 8,021,798,
  신협 누적 관측 689,849 → 811,811로 정상 실행마다 증가).
- 손상은 **발행본**에 있었다: 09-08 04:17~(발행 차단됨), 09-09 04:01~09-10 04:00 신협 약
  8,200행 누락(22,257 표시), 09-11 04:20~15:50 신협 0행 표시. 현재 발행본(09-11 20:02)은
  30,482행으로 정상이다.
- `cu_disclosure_funding`은 09-08 23:44 이후 변경 없음(월 주기 정상).

## 5. 미검증

- 빈 응답 창의 실제 길이(04:00 시작은 실측, 종료 시각은 미실측).
- 2026-09-11 16:17 UTC 이후 정기 workflow가 GitHub에서 전혀 생성되지 않은 원인.
  workflow는 모두 `active`, Actions 권한 정상, GitHub 장애 공지 없음.
- canonical R2 current pointer 직접 확인(로컬에 R2 자격 없음). 각 실행의 `manifest.json`
  (sha256, integrity_check, row_counts)과 rate-data 발행본으로 대신 확인했다.
- 수정 코드의 Production 실행 결과(merge 전).
