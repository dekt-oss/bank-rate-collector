# 신협중앙회 경영공시 수신잔액 runtime evidence — 2026-08-29

## 결론

기존 신협 금리원천의 공식 기관키 `cuIngno`를 그대로 사용해 신협중앙회 경영공시의 구조화 요약재무현황에서 기관별 `예수부채`를 결정론적으로 수집할 수 있음을 bounded live runtime에서 확인했다.

Data.go 신협 finance operation URL은 여전히 미확정이므로 추측하지 않는다. 이번 collector는 별도 공식 원천 `cu_disclosure_funding`으로 취급한다.

2026-08-29 기준 전국 active CU target은 848개이며, 24개 균등 표본과 durable checkpoint/resume 실측까지 통과했다. 이후 실제 848개 전국 checkpoint 수집을 R2 staging에 시작했다. 아직 canonical `state/current.json`은 갱신하지 않는다.

## 공식 source contract

- 목록: `POST https://www.cu.co.kr/cu/ad/dis/getDisclosureList.do`
- 기관 identity: `usrId=<cuIngno>`
- 구조화 재무표: `GET https://www.cu.co.kr/GSSP020000.do`
- key: `cu_ingno`, `busi_ty=610`, `disclosure_no`, `disclosure_ty`
- 단위: `백만원`
- 계정 원문: `예 수 부 채` → whitespace 제거 후 `예수부채` exact equality
- 기준월: 결산 12월 / 상반기 6월
- PDF/OCR 없음

기관은 DB의 active `cu:<cuIngno>` SourceEntityLink만 seed로 사용한다. 이름 유사도나 전국 검색으로 canonical institution을 새로 만들지 않는다.

## bogoTy gate 실측

광안신협 `02002`, disclosure `24856`은 목록에서:

- `disclosureTy=2`
- `2026년도 상반기 결산공시`
- `bogoTy=N`
- `chkYn3=Y`
- `shortFileName` 존재

하지만 동일 key로 `/GSSP020000.do`를 직접 bounded probe한 결과 HTTP 200이더라도 구조화 재무현황은 유효하지 않았다.

- 단위 `백만원`: 없음
- header: `구분 / 년도 / -1년도 / 증감`
- `예수부채` row: 없음
- table rows: 2개 placeholder

따라서 `bogoTy=Y AND chkYn3=Y AND shortFileName present`를 구조화 요약재무현황 eligibility gate로 유지한다. 단순히 HTTP 200이나 shortFileName 존재만으로 저장하지 않는다.

## 연도 표기 drift

실제 공시명에는 둘 다 존재한다.

- `2024년도 ...`
- `2024년 상반기결산공시`

따라서 year parser는 `년` / `년도`를 모두 허용하되 4자리 20xx 연도만 받는다. 최초 bounded probe에서 `2024년` 표기를 엄격한 `년도` regex가 거부했고, 실측 근거로 수정했다.

잘못된 `regDate` 형식은 임의 추정하지 않고 fail-closed 또는 historical quarantine 정책으로 처리한다.

## bounded persistence proof

Actions run `33228827724`, job `99037738775`에서 production R2와 무관한 임시 SQLite에 두 공식 CU link만 seed하고 동일 수집을 두 번 실행했다.

### 1차 실행

- target: 2 / 2 성공
- raw artifacts: 4
- parsed points: 2
- stored: 2
- revisions: 0
- failures: 0

Active observations:

| cuIngno | 기관 | 기준월 | 예수부채 | 단위 |
|---|---|---|---:|---|
| 02002 | 광안 | 2025-12 | 1,720,194 | 백만원 |
| 02022 | HJ중공업 | 2026-06 | 6,460 | 백만원 |

두 행 모두 `identity_status=mapped_exact_cu_ingno`, revision 1, 공식 `/GSSP020000.do` raw provenance를 가진다.

### 동일 2차 실행

- target: 2 / 2 성공
- stored: 0
- revisions: 0
- unchanged: 2
- failures: 0

즉 동일 source value 재수집은 history row를 증식시키지 않는다.

## 전국 균등 표본 proof

Actions run `33245087161`에서 authoritative R2 snapshot을 runner-local로 복원한 뒤 848개 active CU target에서 24개를 전국 범위로 균등 표본 추출했다. production publish는 하지 않았다.

- nationwide target count: 848
- sample: 24 / 24 완료
- fetched artifacts: 280
- parsed points: 194
- stored: 194
- missing sample targets: 0
- persistence contract violations: 0
- elapsed: 약 310초
- 평균: 약 12.9초 / 기관
- SQLite integrity/FK: PASS

Historical source drift는 3건을 quarantine warning으로 남겼다.

1. `02022`: explicit year가 없는 2021-09-09 상반기결산공시
2. `10154`: disclosure year 2022인데 구조화 표 header가 2021/2020
3. `10154`: disclosure year 2021인데 구조화 표 header가 2020/2019

이 3건은 임의 보정하지 않았고, 나머지 유효 공시 관측은 유지했다.

## durable checkpoint/resume proof

장시간 전국 수집 중 runner timeout/network failure가 발생해도 처음부터 다시 긁지 않도록 공통 resumable acquisition 계층 위에 CU 전용 checkpoint bundle을 구현했다.

Checkpoint는 canonical DB가 아니라 staging/evidence다.

- namespace: `checkpoints/v1/cu_disclosure_funding/<cycle_date>/...`
- work key: `cuIngno`
- bundle: 해당 기관의 공식 list/summary exact response bytes + identity + warnings
- immutable content-addressed chunks
- immutable manifest revisions
- mutable pointer는 checkpoint namespace의 `active.json`만 사용
- canonical `state/current.json`과 별개

Actions run `33245593236`에서 실제 공식 원천 4개 기관(`02002`, `02022`, `03087`, `10154`)으로 의도적 중단과 재개를 검증했다.

### 1차 acquire

- expected targets: 4
- completed: 2
- status: `collecting`
- checkpoint flush 후 종료

### resume

- 동일 session ID 유지
- completed: 4 / 4
- status: `complete`
- 신규 완료: 2

### complete reopen

- same session
- completed: 4 / 4
- newly completed: 0

### checkpoint replay

1차 replay:

- raw artifacts: 48
- parsed points: 28
- stored: 28
- revisions: 0

2차 동일 replay:

- parsed points: 28
- stored: 0
- revisions: 0
- unchanged: 28

SQLite integrity/FK도 PASS했다.

Replay 전에는 current DB의 exact `cu:<cuIngno>` SourceEntityLink와 checkpoint의 canonical institution_id가 여전히 동일한지 재검증한다. 또한 checkpoint 생성 당시 parse 결과를 그대로 신뢰하지 않고 exact raw response를 current parser로 다시 해석한다.

## multi-source double-count guard

현재 Data.go 신협 funding은 0행이지만 향후 exact finance operation이 발견되면 `data_go_credit_union_funding`과 `cu_disclosure_funding`이 같은 기관 모집단을 중복 관측할 수 있다.

이를 조용히 더하면 앞서 저축은행/농·축협에서 확인한 것과 같은 sector-total 중복 오류가 재발할 수 있다. 따라서 reconciliation은 같은 `(sector, reporting month)`에 active `source_id`가 둘 이상이면 합산하지 않고 fail-closed한다. source precedence는 별도 승인된 계약 없이는 임의 선택하지 않는다.

## 전국 실제 checkpoint 수집 — 진행 중

사용자 요청에 따라 2026-08-29 cycle로 848개 전체 신협의 최근 12개 정기/반기 공시를 R2 checkpoint staging에 수집하기 시작했다.

### 1차 acquire

Actions run `33246447753`

- 현재 상태: 진행 중
- R2 authoritative snapshot은 identity baseline으로만 runner-local restore
- 300개씩 checkpoint slice
- 최대 5 slice를 동일 session에서 `resume_mode=auto`로 연속 처리
- request interval: 1.0초
- source raw와 checkpoint staging만 기록
- `rate-monitor storage upload` 없음
- canonical `state/current.json` 변경 없음

### 후속 validation queue

Actions run `33246480321`을 동일 `cu-funding-checkpoint` concurrency group에 대기시켰다. 1차 acquire가 끝난 뒤 complete checkpoint를 재사용한다.

후속 run의 검증 범위:

1. 남은 target 자동 resume
2. ECOS 신협 업권 합계 refresh
3. complete checkpoint replay 2회
4. replay idempotency
5. CU sector reconciliation
6. snapshot + `rate-monitor validate`
7. SQLite integrity/FK

이 후속 run 역시 storage upload가 없으므로 candidate DB는 runner-local에서만 검증된다.

## CI evidence

Checkpoint 구현 head `e2fd5db7994d517b883c8845aab3f62eba0bcdee`, CI run `33245593174`:

- Ruff PASS
- pytest: 1,589 passed
- Alembic empty DB → head PASS
- 16 tables == model metadata

운영 checkpoint workflow 추가 head `7a4a0770a763d3e8be50789d4f7b2c62ff5c096d`의 push/PR checks도 SUCCESS했다.

## 아직 production 완료가 아닌 것

전국 checkpoint 수집과 후속 validation이 끝나기 전에는 이 source를 authoritative R2 DB publish 경로에 편입하지 않는다.

완료 판정에는 최소 아래가 필요하다.

1. 848 target completion과 실패 population
2. 기관별 reporting-month coverage
3. quarantine/warning 분포
4. 동일 기간 중복/정정공시 선택 결과
5. complete checkpoint replay idempotency
6. ECOS 신협 수신잔액 reconciliation
7. source collision 없음
8. full validation/integrity/FK
9. canonical publish 전 별도 검토
10. 임시 push-trigger workflow 제거
