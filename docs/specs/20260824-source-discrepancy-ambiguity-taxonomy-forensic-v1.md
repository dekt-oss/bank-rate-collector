# Source discrepancy ambiguity taxonomy forensic v1

기준일: 2026-08-24

## 1. 목적

B1 payment-method ambiguity census에서 counterpart가 없었던 10건의 taxonomy를 fresh raw로 확인한다.

대상:

- 아산저축은행 `SB톡톡-정기예금` — 6/12m × simple/compound 4건
- 진주저축은행 `정기예금(진주)` — 6/12/24m × simple/compound 6건

Current report상 이 10건은 모두:

- source side: FINLIFE secondary
- product_type: `installment_savings`
- raw provenance: `savingProductsSearch_030300_*.json`
- payment_method: F/S
- counterpart: 없음

상품명은 `정기예금` 계열인데 source service/product_type은 적금 계열이라 B2 7D 결정 전에 source 원문을 직접 확인한다.

## 2. 핵심 질문

1. fresh FINLIFE `savingProductsSearch` raw가 실제로 해당 `fin_prdt_nm`을 제공하는가.
2. 같은 base product code의 option에 실제 `rsrv_type=S/F`와 한글 `정액적립식/자유적립식`이 존재하는가.
3. fresh FSB raw에는 같은 기관/동일 상품명 counterpart가 존재하는가.
4. 이 현상이 내부 parser의 product-name 변형 없이 source raw에서 이미 존재하는가.

## 3. Evidence

같은 isolated workflow에서 fresh FINLIFE savings-bank와 FSB를 수집한다.

FINLIFE target record에 보존:

- service = `savingProductsSearch`
- raw path + SHA-256
- `kor_co_nm`
- `fin_co_no`
- `fin_prdt_cd`
- `fin_prdt_nm`
- `join_way`
- `dcls_month`
- `dcls_strt_day`
- `dcls_end_day`
- `spcl_cnd`
- `etc_note`
- matching option 전체의 `save_trm`, `intr_rate_type(_nm)`, `rsrv_type(_nm)`, rate

FSB에는 대상 기관의 전체 fresh 상품명/product code 목록과 exact target-name record를 보존한다.

## 4. 판정 원칙

- FINLIFE fresh raw 자체가 `savingProductsSearch`에서 `정기예금` 계열 이름 + F/S 적립유형을 제공하면 내부 parser taxonomy 오류로 단정하지 않는다.
- FSB exact name이 없다는 사실만으로 FINLIFE record를 무효화하지 않는다.
- 이름만 보고 deposit/savings identity를 자동 교정하지 않는다.
- upstream source anomaly/semantic anomaly는 별도 source-quality finding으로 남긴다.
- 이 forensic은 payment_method 7D 승격 결정을 하지 않는다.

## 5. Safety

- production DB canonical write 없음
- source precedence/authority 변경 없음
- product/product_type/payment_method identity 변경 없음
- parser/collector 수정 없음
- rate-data/R2 upload 없음
- Strategy / Production Strategy Release Gate 변경 없음

Machine scope:

- `production_state_mutated=false`
- `canonical_mutated=false`
- `source_precedence_changed=false`
- `authority_selected=false`
- `identity_changed=false`

## 6. Acceptance

- General CI SUCCESS
- extractor unit test SUCCESS
- isolated fresh FINLIFE SUCCESS
- isolated fresh FSB SUCCESS
- 두 target 모두 fresh FINLIFE saving service base record 확보
- 두 target 모두 payment methods `F/S`를 raw option에서 직접 확인
- `rsrv_type_nm`에 정액적립식/자유적립식 존재
- FSB fresh 상품 목록과 exact counterpart 여부를 artifact에 보존
- artifact raw files와 forensic JSON 보존

## 7. B2 gate

이 결과가 source raw taxonomy anomaly를 확인하면 해당 10건은 7D 영향도 산정의 일반 ambiguity 표본과 분리해 해석한다.

B2는 그 뒤 다음을 계산한 별도 decision spec으로만 진행한다.

- FSB payment_method coverage
- FINLIFE coverage
- 정상 상품에서 payment_method가 실질 의미를 가르는 비율
- 7D 전환 시 source-only 증가량
- exact comparable universe 감소량
