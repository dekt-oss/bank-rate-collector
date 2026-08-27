# D1 — 개별기관 예수금 공공 API 정찰 결과

- 날짜: 2026-08-27
- 브랜치: `feat/market-funding-stage0-d0-20260827`
- 실행: GitHub Actions `Diagnostic — Institution funding D1 recon`
- run: `33061285297`
- exact head: `7f2fa348f9837d8aa996c7f2fd34ddba1b4db54a`
- artifact: `market-funding-d1-institution-recon`
- mode: **read-only / production DB write 없음**

## 1. 결론

개별 저축은행·신협·농업협동조합의 예수금/재무 데이터를 얻기 위한 금융위원회 금융통계 OpenAPI 서비스 자체는 공식 공공데이터 계약으로 확인했다.

그러나 현재 GitHub Actions 환경에는 `DATA_GO_KR_SERVICE_KEY`가 설정되어 있지 않아 실제 행(row) 수집은 인증 단계에서 중단됐다.

따라서 D1 판정은 다음과 같다.

| 범위 | 판정 | 근거 |
|---|---|---|
| 저축은행 서비스 base/general endpoint | 확인 | `GetMutuSaviBankInfoService/getMutuSaviBankGeneInfo`가 `SERVICE_KEY_IS_NULL` 반환 |
| 저축은행 재무 endpoint 후보 | **endpoint 존재 확인** | `getMutuSaviBankFinaInfo`가 unknown-operation이 아니라 `SERVICE_KEY_IS_NULL` 반환 |
| 신협 서비스 base/general endpoint | 확인 | `GetCredUnioInfoService/getCredUnioGeneInfo`가 `SERVICE_KEY_IS_NULL` 반환 |
| 신협 재무 endpoint | 미확정 | 현재 finite discovery 후보는 general 외 모두 unknown-operation |
| 농협 서비스 base/general endpoint | 확인 | `GetAgriCoopInfoService/getAgriCoopGeneInfo`가 `SERVICE_KEY_IS_NULL` 반환 |
| 농협 재무 endpoint 후보 | **endpoint 존재 확인** | `getAgriCoopFinaInfo`가 unknown-operation이 아니라 `SERVICE_KEY_IS_NULL` 반환 |
| 개별기관 예수금 값 | **미수집** | GitHub Actions secret 부재 |
| production DB 저장 | 미실행 | D1은 의도적으로 read-only |

`SERVICE_KEY_IS_NULL`은 데이터 값의 성공 증거는 아니지만, 동일 gateway에서 존재하지 않는 operation에는 `NO_OPENAPI_SERVICE_ERROR`가 반환됐다는 대조군이 있다. 따라서 저축은행/농협의 `FinaInfo` path는 실재 endpoint로 볼 수 있다. 다만 필드·타이틀·예수금 항목 계약은 인증 후 실제 row를 받아 다시 검증해야 한다.

## 2. 공식 데이터셋 계약

### 2.1 저축은행

공공데이터포털 `금융위원회_금융통계저축은행정보`는 3개 operation으로 구성된다.

1. 일반현황
2. 재무현황
3. 주요경영지표

공식 설명은 총자산·자본·손익뿐 아니라 **수신·여신 실적**, 예대금리차, BIS 비율, 연체율, 수익성 등을 제공한다고 명시한다.

따라서 개별 저축은행의 수신/예수금 분석 후보로 가장 직접적이다.

### 2.2 신용협동조합

공공데이터포털 `금융위원회_금융통계신용협동조합정보`는 기준년월과 조합명을 기준으로:

1. 일반현황
2. 재무현황
3. 주요경영지표

를 제공한다. 일반현황의 실물 계약에는 `fncoCd`, `fncoNm`, `basYm`이 포함되는 것이 공식 문서로 확인됐다.

D1에서는 인증키가 없고 재무 operation name도 아직 확정하지 못했으므로 예수금 필드 존재 여부는 **미검증**이다.

### 2.3 농업협동조합

공공데이터포털 `금융위원회_금융통계농업협동조합정보`는 농협중앙회 및 단위농협의 일반·재무·주요경영지표를 기준년월과 조합명으로 제공한다고 명시한다.

D1 gateway reconnaissance에서 `getAgriCoopFinaInfo`가 실재 endpoint임을 확인했다.

중요: 중앙회/단위조합이 함께 존재할 수 있으므로 실제 row를 받은 뒤 **기관 유형과 aggregation denominator**를 먼저 정의해야 한다. 단순 합산·순위를 금지한다.

## 3. D1 runtime evidence

workflow artifact의 요약:

```text
credential_present=false

savings_bank
  getMutuSaviBankGeneInfo -> HTTP 401 / SERVICE_KEY_IS_NULL
  getMutuSaviBankFinaInfo -> HTTP 401 / SERVICE_KEY_IS_NULL
  다른 탐색 후보       -> HTTP 400 / NO_OPENAPI_SERVICE_ERROR

credit_union
  getCredUnioGeneInfo    -> HTTP 401 / SERVICE_KEY_IS_NULL
  현재 재무 탐색 후보    -> NO_OPENAPI_SERVICE_ERROR

agri_coop
  getAgriCoopGeneInfo    -> HTTP 401 / SERVICE_KEY_IS_NULL
  getAgriCoopFinaInfo    -> HTTP 401 / SERVICE_KEY_IS_NULL
  다른 탐색 후보         -> HTTP 400 / NO_OPENAPI_SERVICE_ERROR
```

이 차이는 endpoint path discovery에 유용하지만, 실제 데이터 row·필드·단위·주기를 대신하지 않는다.

## 4. 현재 blocker

필요 secret:

```text
DATA_GO_KR_SERVICE_KEY
```

기존 `FINLIFE_API_KEY`를 대신 사용하지 않는다. 같은 정부 API gateway라고 가정해서 자격증명을 재사용하는 것은 least-privilege와 source-contract 원칙에 맞지 않는다.

공공데이터포털의 해당 서비스는 개발계정 자동승인/무료로 안내되어 있다. 키를 발급받은 뒤 GitHub repository Actions secret `DATA_GO_KR_SERVICE_KEY`에 등록하면 현재 D1 workflow를 그대로 재실행할 수 있다.

## 5. 인증 후 Evidence Gate

실제 row가 내려오면 저장 구현 전에 아래를 모두 확인한다.

1. **operation contract**
   - 재무/경영지표의 정확한 operation name
   - pagination semantics
   - `resultCode/resultMsg/totalCount`
2. **identity**
   - `fncoCd`
   - `fncoNm`
   - 법인/조합/중앙회/단위조합 구분
   - 현재 canonical institution과의 매핑 가능성
3. **time**
   - `basYm`
   - 월말/분기말/보고월 의미
   - 수정치/revision 발생 여부
4. **deposit metric**
   - `예수금`, `수신`, `예금`의 정확한 source title/field
   - 총액인지 세부계정인지
   - 단위(원/백만원/억원 등)
   - 값의 sign/null/placeholder 규칙
5. **coverage**
   - 기관 수
   - 월별 coverage
   - inactive/merged institution
   - 같은 기관의 중복 row 여부
6. **reconciliation**
   - 개별기관 합계와 ECOS 업권 잔액은 모집단·회계기준이 다를 수 있으므로 처음부터 동일하다고 가정하지 않음
   - 차이를 coverage/reconciliation 지표로 관리

## 6. 저장 계약 후보 — 아직 확정 아님

D1 actual-row 검증 전에는 schema migration을 하지 않는다.

검증 후 권장 raw normalized point:

```text
source_id
institution_source_key
institution_name
source_effective_month
metric_code
metric_name
value
unit
basis
source_locator
raw_artifact_id
observed_at
revision_key / revision metadata
```

큰 금액은 기존 `Rate` 타입에 넣지 않는다. D0에서 예금은행 총예금 2,281조원이 실제로 확인돼 `999.9999` 상한을 초과했으므로 Stage 0의 wide fixed-decimal `Quantity` 계약이 먼저 완료되어야 한다.

## 7. Strategy 사용 조건

개별기관 예수금이 확보돼도 바로 화면에 순위를 만들지 않는다.

다음 조건을 만족할 때만 `당사 조달 위치`를 활성화한다.

- stable institution identity 매핑 통과
- 월/분기 basis 명시
- 최소 coverage gate 통과
- 금액 단위 및 revision semantics 검증
- peer denominator 정의
- own institution mapping 명시

그 전에는 ECOS의 검증된 **업권 단위 수신시장**만 Strategy 공식 지표로 사용한다.

## 8. 다음 실행

1. `DATA_GO_KR_SERVICE_KEY` repository secret 등록
2. D1 workflow 재실행
3. actual rows와 titles/fields/units/coverage 보고
4. 필요한 경우 operation discovery를 exact-contract probe로 축소
5. 임시 SQLite에만 저장하는 integration test
6. 그 결과를 보고 persistence/backfill 범위를 최종 승인

Production DB write와 Strategy UI 연동은 위 검증 이후 별도 단계다.
