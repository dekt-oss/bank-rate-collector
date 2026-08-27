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

## R2 publication gate

1. authoritative R2 DB restore
2. migration
3. ECOS refresh
4. Data.go source/month checkpoint collection
5. SQL readback / source coverage / reconciliation
6. 동일 모드 재실행 idempotency
7. snapshot validation
8. R2 upload
9. R2 restore 및 byte-for-byte / integrity / FK 검증

저축은행 또는 농·축협 필수 source/month가 끝까지 실패하면 8번에 도달하지 않는다.

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

PR #225 branch에서 `[funding-backfill]` writer를 실행해 실제 원천 보유기간, 신협 exact contract, DB/R2 readback을 확인한다. 실행 결과가 확인되기 전에는 이 문서의 6년은 **요청 목표**이지 확보 완료 선언이 아니다.
