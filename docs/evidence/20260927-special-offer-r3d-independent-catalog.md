# Special-offer Radar R3-D — independent bank-direct evidence catalog

기준일: 2026-09-27
Issue: #352

## 결론

R3-C production-copy audit에서 웰컴 LIKIT, 웰컴 디지로카, IBK 청룡비상,
대신 기업자유예금은 해당 금융사의 current FSB exact-code 상품 목록과 모두
binding 0건이었다.

이는 단순 alias 누락이 아니다. 같은 기관의 FSB 상품들은 다수 존재하지만
위 특판 상품 자체가 current FSB universe에 없다.

따라서 과거/별도 특판을 Radar에 보이게 만들기 위해 canonical Product를
강제로 생성하거나 이름 유사도로 FSB Product에 붙이지 않는다.

## 저장 경계

새 table: official_special_offer_catalog_evidence

이 table은 bank-direct 공식 근거 자체를 identity로 사용한다.

- source namespace: HTTPS 공식 source hostname
- institution name / normalized name
- official product key
- product name
- confirmed classification
- availability status
- snapshot/effective period
- observed_at
- source locator
- content hash
- structured evidence JSON
- optional canonical_product_id
- binding_status

canonical_product_id는 nullable cross-reference다. null이어도 official evidence
identity는 완전하다.

## 기존 ProductSpecialOfferEvidence와의 차이

product_special_offer_evidence:
- canonical Product에 귀속
- same-source active exact_code link 필수
- 현재 FSB snapshot과 canonical product 중심

official_special_offer_catalog_evidence:
- current FSB universe 밖의 공식 특판도 보존
- canonical Product 생성 불필요
- Radar benchmark 전용
- 일반 금리 universe의 identity가 아님

기존 registry 제약을 완화하지 않고 별도 catalog를 둔다.

## Contamination invariants

catalog append 전후 다음은 동일해야 한다.

- products count
- product_variants count
- rate_observations count
- Dashboard summary/table
- Strategy payload에서 special_offer_radar를 제외한 모든 값
- source precedence / ranking / Relative Pricing

변할 수 있는 것은 Radar catalog payload뿐이다.

## Import gate

R3-C capture 중 다음을 모두 만족하는 행만 import한다.

- classification_candidate = confirmed_special_candidate
- official product identity marker 확인
- explicit special-offer phrase 확인
- HTTPS official locator
- valid SHA-256 provenance

unverified capture 및 fetch failure는 append하지 않는다.

## Availability

classification과 availability는 계속 분리한다.

- confirmed_active: explicit active assertion 필요
- confirmed_ended: explicit end/stop 또는 이미 종료한 명시기간
- unknown: current/history 탭에 넣지 않음

미래 sale_end만으로 active를 만들지 않는다.

## Production boundary

이번 PR에는 production R2 writer를 연결하지 않는다.

먼저:
1. migration upgrade/downgrade
2. runner-local production-copy import
3. canonical contamination proof
4. Radar desktop/mobile browser E2E

를 통과시킨다.

실제 production catalog append/schedule은 별도 승인·작업으로 분리한다.
