# 신협중앙회 경영공시 수신잔액 runtime evidence — 2026-08-29

## 결론

기존 신협 금리원천의 공식 기관키 `cuIngno`를 그대로 사용해 신협중앙회 경영공시의 구조화 요약재무현황에서 기관별 `예수부채`를 결정론적으로 수집할 수 있음을 bounded live runtime에서 확인했다.

Data.go 신협 finance operation URL은 여전히 미확정이므로 추측하지 않는다. 이번 collector는 별도 공식 원천 `cu_disclosure_funding`으로 취급한다.

## 공식 source contract

- 목록: `POST https://www.cu.co.kr/cu/ad/dis/getDisclosureList.do`
- 기관 identity: `usrId=<cuIngno>`
- 구조화 재무표: `GET https://www.cu.co.kr/GSSP020000.do`
- key: `cu_ingno`, `busi_ty=610`, `disclosure_no`, `disclosure_ty`
- 단위: `백만원`
- 계정 원문: `예 수 부 채` → whitespace 제거 후 `예수부채` exact equality
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

## multi-source double-count guard

현재 Data.go 신협 funding은 0행이지만 향후 exact finance operation이 발견되면 `data_go_credit_union_funding`과 `cu_disclosure_funding`이 같은 기관 모집단을 중복 관측할 수 있다.

이를 조용히 더하면 앞서 저축은행/농·축협에서 확인한 것과 같은 sector-total 중복 오류가 재발할 수 있다. 따라서 reconciliation은 같은 `(sector, reporting month)`에 active `source_id`가 둘 이상이면 합산하지 않고 fail-closed한다. source precedence는 별도 승인된 계약 없이는 임의 선택하지 않는다.

## 아직 production 완료가 아닌 것

이 evidence는 source/parse/identity/persistence/idempotency contract를 검증한 것이다. 전국 historical backfill 및 authoritative R2 완료 판정은 별도 operational integration 후 다음을 확인해야 한다.

1. active CU institution seed 전체 coverage
2. 기관별 정기/반기 disclosure availability와 실패 population
3. historical reporting-month coverage
4. 동일 기간 중복/정정공시 선택 결과
5. ECOS 신협 수신잔액 reconciliation
6. full validation/integrity/FK
7. R2 upload → restore → hash/row-count readback
