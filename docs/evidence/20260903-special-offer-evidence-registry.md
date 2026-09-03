# Forward-only 특판 Evidence Registry

기준일: 2026-09-03

## 결론

FSB 공시와 공식 상품 페이지 조사만으로 과거 상품의 특판 여부를 일괄 복원할
수 없었다. 따라서 현재 `products.is_special_sale = false`를 과거 일반상품의
증거로 재사용하지 않는다. 새 `product_special_offer_evidence` 표가 앞으로
수집되는 상품별 snapshot을 3상태로 보존한다.

- `unknown`: 원천 snapshot은 있으나 특판 여부를 명시하지 않음
- `confirmed_special`: 상품 단위의 명시적 공식 근거로 특판 확인
- `confirmed_normal`: 상품 단위의 명시적 공식 근거로 일반상품 확인

## 저장 계약

한 행은 exact-code `SourceEntityLink`로 확인한 원천 상품키에만 귀속된다. FSB
수집 경로는 원본 `RawArtifact`, 행 해시, `PRODUCT_URL`, source locator와 요청
snapshot 날짜를 함께 저장한다. 같은 근거의 재처리는 `evidence_key`로 멱등이며
기존 행은 수정하거나 삭제하지 않는다.

확정 판정은 `explicit_source_field` 또는
`versioned_product_scope_observation`만 허용한다. 다음은 확정 근거가 아니다.

- 상품명·우대조건의 `특판`, `한정` 등 자유문구
- 공유 URL이나 은행 일반 페이지의 탐색 메뉴
- 특판 표시를 찾지 못했다는 사실
- 현재 페이지를 과거에도 같았다고 보는 추정

현재 페이지를 과거 snapshot에 연결하려면 페이지 자체가 밝힌 적용 시작일이
필요하다. 적용기간이 없으면 관측한 snapshot 한 날짜에만 유효하다.

## 조회 계약

조회는 `as_of`와 `known_at`을 분리한다. `known_at` 뒤에 수집된 근거는 과거
의사결정에 보이지 않는다. 같은 최신 관측시각에 상충하는 판정이 있으면
`unknown/conflict`로 닫는다. exact snapshot의 명시적 판정이 적용기간 근거보다
우선하지만, exact `unknown`은 명시적 적용기간 근거를 가리지 않는다.

## 현재 활성화 범위

일상 FSB 수집에서 forward-only `unknown` 근거 적재까지 연결했다. 기존
`Product.is_special_sale`, 금리 identity/dedupe, 순위 모집단과 Strategy 화면은
변경하지 않았다. 확정 근거가 실제로 축적되고 검수되기 전에는 R2 특판 radar와
과거 상대가격 분석을 활성화하지 않는다.
