# 신협중앙회 경영공시 수신잔액 실측 — 2026-08-29

## 결론

Data.go 신협 재무현황의 exact finance operation URL은 아직 확정되지 않았지만, 현재 금리 수집이 사용하는 신협 공식 조합코드 `cuIngno`를 그대로 사용해 **신협중앙회 공식 전자공시의 구조화 요약재무현황**에 접근할 수 있는 결정론적 경로를 실측했다.

- 공시 목록: `POST /cu/ad/dis/getDisclosureList.do`
- 기관 key: `usrId=<cuIngno>`
- 구조화 요약재무현황: `GET /GSSP020000.do`
- 요청 key: `cu_ingno`, `busi_ty=610`, `disclosure_no`, `disclosure_ty`
- 재무표 단위: `백만원`
- 수신잔액 계정 원문: **`예 수 부 채`**

따라서 PDF OCR이나 이름 기반 기관 추정을 사용하지 않고도, 이미 수집 중인 CU 공식 기관 key와 직접 연결되는 수신잔액 원천을 확보할 수 있다.

## Runtime evidence

Actions run `33228130980`, artifact `cu-funding-disclosure-recon` (`9707555683`)에서 repository fixture의 두 실제 기관을 bounded probe했다.

### 광안신협 `02002`

- 공시 목록 HTTP 200
- 반환 `cuIngno` = `02002` only
- listTotalCount = 53
- 2025 결산정기공시 summary: HTTP 200
- title: `재무현황<광안신용협동조합 2025 요약공시`
- 단위: 백만원
- `예 수 부 채`: 2025 **1,720,194**, 2024 **1,313,185**

### HJ중공업신협 `02022`

- 공시 목록 HTTP 200
- 반환 `cuIngno` = `02022` only
- listTotalCount = 32
- 2026 상반기 summary: HTTP 200
- title: `재무현황<HJ중공업신용협동조합 2026 요약공시`
- 단위: 백만원
- `예 수 부 채`: 2026 **6,460**, 2025 **6,452**

## Identity contract

현재 CU 금리 원천과 중앙회 경영공시는 모두 신협중앙회 도메인의 `cuIngno`를 사용한다. 수신잔액 수집은 새 기관을 이름으로 생성하지 않고, DB에 이미 존재하는 active `cu` SourceEntityLink의 `cu:<cuIngno>` key를 입력 모집단으로 사용한다.

- exact active link가 하나 있어야 함
- linked institution sector는 `cu`여야 함
- 공시목록 반환 `cuIngno`는 요청값 하나와 exact equality여야 함
- 불일치/중복/기관 link 부재는 fail-closed 또는 별도 미수집 상태로 남김

## Amount contract

요약재무표 원문 단위가 이미 **백만원**이다. 따라서 Data.go처럼 KRW를 1,000,000으로 나누지 않는다.

- `source_value_text`: 표의 금액 셀 원문(쉼표 제거 전 원문 provenance는 raw HTML에 유지)
- `source_unit`: `million_krw`
- normalized `value`: 동일 숫자를 Quantity precision으로 보존
- metric: `deposit_liabilities_total`
- metric display: `예수부채`

계정 판정은 공백 제거 후 `예수부채`와 exact equality일 때만 허용한다. `부채계`, `자산합계` 등 대체 계정을 추정해 사용하지 않는다.

## Period contract

공시 목록의 `disclosureTy`와 공시 제목을 함께 검증한다.

- 정기결산 `disclosureTy=1`: 해당 연도 12월 reporting period
- 상반기결산 `disclosureTy=2`: 해당 연도 6월 reporting period
- 수시공시 `disclosureTy=3`: 수신잔액 history 대상에서 제외

연도는 `disclosureName`과 summary table header의 연도가 일치해야 한다. 불일치하면 저장하지 않는다.

## Backfill boundary

전국 기관을 전자공시 검색으로 새로 enumerate하지 않는다. 이미 authoritative rate DB에 있는 active CU 기관 key를 seed로 사용한다. 각 기관의 공시 목록을 page 단위로 읽고, 요청된 최근 reporting period 수까지만 type 1/2 summary를 가져온다.

Raw JSON/HTML은 모두 원형 보존하고, active observation 자연키는 `(source_id, cuIngno, metric_code, source_effective_month)`를 사용한다. 값이 같으면 no-op, 달라지면 기존 row를 `valid_to`로 닫고 revision을 추가한다.

## 아직 검증이 필요한 것

이 문서는 **두 기관 bounded runtime contract**를 확정한 것이다. 전국 backfill을 production 완료로 선언하려면 별도 runtime gate가 필요하다.

1. 전국 active CU key coverage / disclosure availability
2. 6년 reporting-period completeness
3. account row exact parse failure population
4. duplicated disclosure period 선택 규칙
5. incremental rerun idempotency
6. ECOS broader-sector reconciliation
7. authoritative R2 upload/restore + integrity/FK
