# Data.go.kr 기관별 수신잔액 operational contract — 2026-08-27

## 결론

이번 계층은 금융위원회 Data.go.kr 금융통계의 기관별 **예수부채**를
`institution_funding_observations`에 저장한다. 상품금리와 ECOS 업권지표를
섞지 않는다.

### 확정한 원칙

1. `fncoCd`는 공공데이터포털 정의상 **금융감독원 금융회사 금융코드**다.
   기관 source key의 1차 식별자로 사용한다.
2. `crno`는 법인 동일성 보조증거다. 같은 `fncoCd`에 서로 다른 non-empty
   `crno`가 나타나면 자동 재연결하지 않고 fail-closed review로 보낸다.
3. `basYm`은 공식 정의가 **기준년월**이다. source가 월말/분기말이라는 별도
   문구를 주지 않으므로 DB basis는 `reported_period_end`로 기록하고,
   달력상 해당 월의 마지막 날은 비교용 `period_end`로만 계산한다.
4. 원천 예수부채 금액은 actual authenticated row의 정수 KRW 계약을 보존한다.
   DB 비교값은 **million_krw**로 lossless 정규화한다.
   `1 KRW = 0.000001 million KRW`이므로 Quantity 6dp에 원 단위까지 정확히 들어간다.
   원문은 `source_value_text`와 raw artifact에 별도로 남긴다.
5. 같은 자연키의 같은 content hash는 no-op, 값이 바뀌면 기존 행의
   `valid_to`를 닫고 `revision + 1`을 만든다. overwrite하지 않는다.

## Source contract

| 업권 | dataset | financial operation | 총 예수부채 |
|---|---|---|---|
| 저축은행 | 15061316 | `GetMutuSaviBankInfoService/getMutuSaviBankFinaInfo` | `A11 예수부채` |
| 신협 | 15061337 | 공식 catalogue는 재무현황 operation 존재를 확인. exact operational path는 live promotion 필요 | live row가 검증된 naming family와 일치할 때만 promotion |
| 농·축협 | 15061344 | `GetAgriCoopInfoService/getAgriCoopFinaInfo` | `A1 예수부채` |

신협은 endpoint 이름을 추측해서 persistence contract로 고정하지 않는다.
공식 catalogue와 live gateway가 모두 확인된 후보만 runtime에서 승격한다.
모든 후보가 transport 실패한 경우 `unavailable`로 판정하지 않는다.

## Null / sign / placeholder

- `fncoCd`, `fncoNm`, `basYm`은 총 예수부채 point의 필수값.
- 금액 `NULL`, 빈 문자열, `-`, `null`, 비수치 → point 생성 금지.
- 음수 → 계약 오류.
- 명시적 `0` → 유효한 source value로 보존.
- source KRW에 소수점이 나오면 단위 계약 drift로 보고 실패.
- 같은 기관/기준월 총 예수부채가 서로 다른 값으로 중복되면 일부값을 고르지
  않고 전체 source run을 실패시킨다.

## Data.go 예수부채 ↔ ECOS 수신잔액 reconciliation

둘은 같은 개념이라고 가정하지 않는다.

- Data.go: 금융회사 재무상태표의 **예수부채** 계정.
- ECOS: 업권 단위 **수신잔액(말잔)** 통계.

따라서 reconciliation은 source value를 수정하는 도구가 아니라 품질지표다.

### 저축은행 / 신협

동일 기준월에 institution sum과 ECOS 업권합계를 비교한다.

- 차이율 `<= 2%`: `aligned`
- `2% < 차이율 <= 5%`: `review`
- `> 5%`: `contract_mismatch_review`

5%를 넘었다고 Data.go 값을 삭제하지 않는다. 모집단, 보고시점, consolidation,
회계분류, revision을 먼저 조사한다. 이 band는 최초 운영 QC 기준이며 실제
겹치는 기간의 분포가 충분히 쌓이면 재보정한다.

### 농·축협

Data.go dataset 설명은 **농협중앙회 및 단위 농협**을 함께 포함한다.
actual row에서 농협중앙회 `fncoCd=0212450`도 확인됐다.

운영 합계는:

- 농협중앙회 → `agri_coop_central_excluded_from_local_sum`
- 그 외 단위 농·축협 → `agri_coops_local_units_source_reported`

로 분리한다.

ECOS `bok_broad_mutual_finance_deposit_balance`는 농·수·산림계 등을 포함한
광의 상호금융 모집단이므로 단위 농·축협 합계와 **equality tolerance를
적용하지 않는다**. `coverage_ratio = local_agri_sum / ecos_broad_total`만
기록한다.

## Institution lifecycle / source_entity_links

자동 매핑은 같은 sector에서 기존 source link가 **동일한 공식 코드 기반
org key**를 갖고, 정규화 이름도 일치할 때만 수행한다.

이름만 같은 새 `fncoCd`는 합병/개명/조직전환일 수 있으므로 자동 merge하지 않는다.

`source_entity_links.valid_from/valid_to`는 다음 원칙을 쓴다.

- FSS/FSC 공시, 인가/합병/영업양수도/해산 등 **공식 사건의 효력일**이 확인되면
  그 날짜를 사용한다.
- Data.go `basYm` first-seen은 관측 하한일 뿐 법적 효력일이 아니다.
- 공식 사건일을 모르면 `valid_from=NULL`을 유지하고
  `source_payload_json.observed_from_month`에 첫 관측월을 남긴다.
- `crno` 충돌 또는 코드 재사용 의심은 자동으로 link를 닫거나 옮기지 않고
  review item을 만든다.

## R2

운영 상태 저장소는 이미 `backend: r2`다. 새 별도 DB를 만들지 않는다.

Operational workflow는 기존 invariant를 그대로 따른다.

```text
R2 authoritative DB restore
  → alembic upgrade head
  → ECOS sector totals refresh
  → Data.go funding collect
  → SQL readback / FK / integrity
  → 동일 수집 rerun idempotency
  → coverage / reconciliation
  → application snapshot
  → R2 upload
  → R2 restore byte-for-byte + SQL readback
```

feature branch에서는 commit message에 `[funding-r2]`가 있을 때만 실제 R2 write
gate가 실행된다. 일반 PR push는 production state를 바꾸지 않는다.
merge 후에는 동일 workflow가 `rate-data-writer` concurrency에서 평일
00:52 KST에 실행된다.
