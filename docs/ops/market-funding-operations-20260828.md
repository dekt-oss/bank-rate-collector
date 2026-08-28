# Market Funding 운영 수집 계획 — 2026-08-28

## 목적

기관별 예수부채와 ECOS 수신시장 데이터를 일회성 정찰이 아니라 장기 시계열로 운영한다.

원칙:

- 최신값만 저장하지 않는다. Data.go `basYm`과 ECOS 월별 시계열을 과거월까지 backfill한다.
- 원천값을 overwrite하지 않고 revision을 보존한다.
- `잔액 증감 != 신규 순유입`, correlation != causal effect 계약을 유지한다.
- 필수 source/month 실패 시 authoritative R2 publish를 막는다.

## 최초 backfill

기본 목표는 6년이다.

| 업권 | 공표 cadence 계약 | backfill 요청 | 목표 길이 |
|---|---|---:|---:|
| 저축은행 | 분기 3/6/9/12 | 24개 보고기간 | 약 6년 |
| 신협 | 분기 3/6/9/12 | 24개 보고기간 | 약 6년 |
| 농·축협 | 반기 6/12 | 12개 보고기간 | 약 6년 |

실제 원천 보유기간이 더 짧으면 빈 응답을 임의 보간하지 않는다. DB coverage evidence의 `earliest_month` / `latest_month` / `reporting_months`를 실제 확보범위로 사용한다.

## 반복 운영

GitHub Actions는 평일 00:52 KST에 실행한다.

정기 실행은 전체 history를 다시 받지 않고 최근 약 1년 revision-watch만 수행한다.

- 저축은행: 최근 4개 분기
- 신협: 최근 4개 분기
- 농·축협: 최근 2개 반기
- ECOS: 기존 macro collector에서 신규 발표월 및 revision을 갱신

새 값 또는 과거 revision은 기존 observation을 삭제하지 않고 revision chain으로 보존한다.

## Transport fail-fast

Data.go gateway 또는 제공기관 upstream 연결이 불안정할 때 기준월별 timeout을 수십 번 반복하지 않는다.

1. source fan-out 전에 `numOfRows=1` bounded preflight를 수행한다.
2. timeout/network/5xx는 fresh client로 최대 3회만 재시도한다. 지연은 1초, 3초로 제한한다.
3. 4xx처럼 재시도로 해결되지 않는 거절은 즉시 fail-closed 처리한다.
4. 최대 3회 뒤에도 연결되지 않으면 해당 source를 fail-closed 처리한다.
5. 필수 source인 저축은행·농축협 preflight 실패는 전체 writer를 실패시켜 R2 upload를 막는다.
6. exact finance endpoint가 아직 검증되지 않은 신협은 fan-out하지 않고 partial evidence로 남긴다.
7. workflow 전체는 90분 hard timeout을 둔다.

이 gate는 원천 장애를 데이터 부재로 오판하지 않기 위한 것이다. preflight timeout을 `0건 데이터`로 저장하지 않는다.

## Data.go finance pagination 계약

2026-08-28 실패 artifact를 직접 확인한 결과 finance endpoint JSON은 단일 `body.items.item` 구조가 아니다.

- 실제 구조: `response.body.tableList[]`
- 각 재무표가 독립적으로 `title`, `totalCount`, `items.item`을 가진다.
- 계정코드 filter를 넣어도 응답에는 관계없는 다른 재무표들이 함께 남는다.
- 따라서 응답 전체의 모든 `item` 수 또는 재귀적으로 찾은 모든 `totalCount`를 pagination 기준으로 사용하면 안 된다.

수집기는 첫 page에서 검증된 예수부채 total account code가 실제로 포함된 table을 하나 찾고, 이후에는 그 table의 `title`을 고정하여 **그 table의 `totalCount`만** pagination 근거로 사용한다.

2025-06 live filter probe 근거:

- 저축은행 `dpsdbtDcd=A11`: target rows 80, target `totalCount=80`; 같은 응답의 다른 table에는 최대 `totalCount=15,840` 존재
- 농·축협 `astDebtSmryBlnshDcd=A1`: page 1 target rows 500, target `totalCount=1,126`; 같은 응답의 다른 table에는 최대 `totalCount=74,316` 존재

즉 과거 `len(_flatten_items(payload)) < PAGE_SIZE` 방식은 서로 다른 재무표를 섞어 잘못된 다음 page를 요청할 수 있었다.

## R2 publication gate

1. authoritative R2 DB restore
2. migration
3. ECOS refresh
4. bounded Data.go transport preflight
5. Data.go source/month checkpoint collection
6. SQL readback / source coverage / reconciliation
7. 최근 revision-watch 범위만 재수집해 idempotency 확인
8. snapshot validation
9. R2 upload
10. R2 restore 및 byte-for-byte / integrity / FK 검증

저축은행 또는 농·축협 필수 source/month가 끝까지 실패하면 9번에 도달하지 않는다.

신협은 공식 데이터셋의 재무현황 operation 존재는 확인됐으나 exact finance endpoint가 아직 live-verified되지 않았다. exact operation/schema가 확정되기 전에는 fail-closed/partial로 유지하고 랭킹 population에 포함하지 않는다.

## 분석 사용 조건

- YoY 성장률: 동일 기관의 전년 동월 observation이 모두 존재할 때만 계산
- 12/24/36개월 분석: 해당 horizon의 실제 관측 history가 존재할 때만 활성화
- 기관 순위: verified identity만 사용
- 농협중앙회: 단위 농·축협 합계/랭킹에서 제외
- 4분면: 금리 포지션과 잔액 성장의 descriptive correlation만 표시

## 후속 deep backfill

6년 backfill 이후 원천에서 더 오래된 데이터가 실제 반환되고 분석 가치가 있으면 `custom` 모드로 기간을 늘린다. 보유기간을 추정해서 채우거나 현재값을 과거에 복제하지 않는다.

## Runtime Evidence Gate

### 1차 6년 backfill — 실패

PR #225 branch의 run `33123943113`은 약 2시간 46분 실행된 뒤 Data.go 단계에서 실패했다.

- 저축은행 24개 분기: completed 0 / artifact 0 / point 0
- 농·축협 12개 반기: completed 0 / artifact 0 / point 0
- 신협 후보 endpoint: transport 실패
- SQL coverage, idempotency, snapshot, R2 upload/readback은 실행되지 않음
- authoritative R2는 변경되지 않음

이 실행은 정상적인 backfill 소요시간 증거가 아니라 per-month timeout/retry storm으로 판정한다.

### Bounded probe

- run `33133449630`: 저축은행 202606 `numOfRows=1` → 15.9초 ReadTimeout. 농축협 202606 `numOfRows=1` → 14.0초 HTTP 200 / NORMAL SERVICE / totalCount=0.
- run `33133676103`: 다른 GitHub-hosted runner에서 저축은행 finance/general, 농축협 finance, 신협 general 모두 `numOfRows=1` 수준에서 약 15초 ConnectTimeout.
- job `98736207501`: 2025-06 account filter live probe 성공. 저축은행 A11 80 rows, 농축협 A1 page1 500 rows / target totalCount 1,126.

따라서 `PAGE_SIZE=9999`만의 문제로 단정하지 않는다. GitHub-hosted runner ↔ Data.go 경로의 간헐적 transport 불안정성이 재현되었다.

### Bounded backfill 재실행 1 — fail-fast 정상 작동, source 접근 실패

run `33137444548`:

- 저축은행 preflight: ConnectTimeout
- 농·축협 preflight: ConnectTimeout
- source/month fan-out을 시작하지 않고 빠르게 fail-closed
- authoritative R2 미변경

이 실행은 과거 수시간 timeout storm을 bounded preflight가 차단한다는 증거다. 데이터 부재 증거가 아니다.

### Bounded backfill 재실행 2 — 저축은행 접근 성공, pagination 계약 버그 발견

run `33137751708`:

- 저축은행 preflight: HTTP 200 성공
- 저축은행 202606: month fetch 완료
- 저축은행 202603: `pagination이 20 page를 초과했다`로 중단
- 농·축협 preflight: ReadTimeout
- R2 publish/readback 미실행, authoritative R2 미변경

실패 artifact의 실제 `tableList` 구조를 확인해 pagination bug를 특정했다. 이후 구현은 target account table의 고유 `totalCount`만 사용하도록 수정하고, transient preflight는 최대 3회의 fresh-client bounded retry로 강화했다.

### 최종 완료 조건

아래가 모두 실제 Actions runtime에서 통과하기 전에는 6년 backfill 완료로 선언하지 않는다.

1. 저축은행 요청기간 수집 완료
2. 농·축협 요청기간 수집 완료
3. source coverage/readback 및 reconciliation
4. bounded incremental rerun idempotency
5. snapshot validation
6. authoritative R2 upload
7. R2 restore byte-for-byte / integrity / FK 검증

이 문서의 6년은 **요청 목표**이며, 실제 확보 완료는 authenticated backfill + coverage + R2 readback이 모두 성공한 이후에만 선언한다.
