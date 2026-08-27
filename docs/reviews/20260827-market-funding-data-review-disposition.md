# 수신시장 데이터 수집·정리 Claude 리뷰 반영 기록

- Date: 2026-08-27
- Reviewer verdict: **APPROVE WITH CHANGES**
- Reviewed branch: `docs/market-funding-data-v1-20260827`
- Reviewed drafts:
  - `docs/plans/20260827-market-funding-data-plan-v1.md`
  - `docs/specs/20260827-market-funding-data-acquisition-v1.md`
- Reviewed revisions:
  - `docs/plans/20260827-market-funding-data-plan-v1.1.md`
  - `docs/specs/20260827-market-funding-data-acquisition-v1.1.md`

## 결론

원 설계의 evidence gate, Layer 분리, 미검증 code placeholder, UI/인과모델 후순위 원칙은 유지한다. 구현 착수 전에 저장능력·revision provenance·기관 mapping·fail-closed·backfill contract를 보강한다.

## Must-fix disposition

| Review | 판정 | v1.1 반영 |
|---|---|---|
| M1 `market_indicators.value=Rate` 999.9999 상한 | 수용 | Stage 0 `Quantity` 계열 fixed-decimal 타입 + migration |
| M2 SQLite `Numeric` 부적합 | 수용 | Layer B도 SQLite-safe fixed-decimal TypeDecorator |
| M3 기관 mapping 중복 | 수용 | 기존 `source_entity_links`를 유일한 canonical mapping source로 사용 |
| M4 revision overwrite provenance 소실 | 수용 | overwrite 전 `review_items` revision audit |
| M5 warning + partial row-drop | 수용 | 구조적 drift는 contract artifact 단위 all-or-nothing |
| M6 backfill 100-row silent truncation | 수용 | `list_total_count`, pagination/chunk, TIME/count 검증 |
| M7 no-data RESULT 처리 | 수용 | D0 실제 response evidence 후 code 분기 |
| M8 sector vocabulary mismatch | 수용 | `source_sector`와 기존 canonical `Sector`의 mapping 분리 |
| M9 말잔/평잔 semantics 부재 | 수용 | `value_semantics` / `balance_basis` 명시 |

## Should-fix disposition

- S1: 금리 level ↔ 잔액 level 단순상관 금지. 잔액 증감 기준.
- S2: publication date 미제공 시 추정하지 않음. Layer A는 monthly-only v1.
- S3: ECOS macro의 `source_effective_at`은 parser contract상 필수.
- S4: content hash는 실제 저장 normalized value 기준.
- S5: 평일 48개월 재수집 구조는 신규 series 확대 전 schedule 재설계.
- S6: warning/error 원문은 `review_items`에 감사 가능하게 보존.
- S7: Layer B에 source value, semantics, basis, run, first/last seen 추가. frequency를 unique key에 포함.
- S8: ECOS 수신과 FISIS 예수금 정의가 검증되기 전 임의 허용오차 비교 금지.
- S9: 기존 macro CLI module entrypoint를 기본으로 유지.
- S10: 개별 MG 예수금은 원천 부재를 가정하지 않고 D0에서 존재 여부부터 확인.

## 구현 순서 확정

1. Stage 0 — storage/provenance hardening
2. D0 — read-only source recon
3. D1a — verified nonbank rate series
4. D1b — verified bank balance series
5. D1c — pagination-safe backfill
6. D2a — savings-bank institution funding
7. D2b — CU/NH only when the contract is proven compatible
8. D3 — audit/report

## 아직 미검증

다음은 Claude 리뷰에서도 API 실조회 없이 결론내리지 않았다.

- 비은행 업권 대표 수신금리 ECOS series 존재/exact code
- 은행 종별 수신잔액 ECOS series 존재/exact code
- `111Y008` 평잔 item code 체계
- ECOS no-data RESULT code
- ECOS publication date metadata
- FISIS/금융공공데이터의 저축은행 예수금 exact metric/unit/frequency/history
- external institution code의 exact mapping ratio
- 개별 새마을금고 예수금 공개원천 존재 여부

이 항목은 D0에서 read-only evidence로 확인하기 전 persistence contract에 포함하지 않는다.
