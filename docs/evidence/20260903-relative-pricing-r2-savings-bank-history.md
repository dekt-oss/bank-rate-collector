# Relative Pricing R2 — 저축은행 historical evidence boundary

```yaml
date: 2026-09-03
scope: savings_bank / term_deposit / 12m
production_write: false
current_state_carryback: prohibited
status: blocked_on_historical_special_offer_provenance
```

## 결론

2026-08-31은 저축은행 Relative Pricing R2의 **availability, canonical identity,
product identity, official 12개월 rate**를 point-in-time으로 재현할 수 있는 확인된
날짜다.

그러나 현재 저장소와 FSB 원천에는 상품의 **당시 특판 여부**를 명시적으로
증명하는 versioned 필드/이력이 없다. 따라서 현재 `Product.is_special_sale=false`를
2026-08-31로 소급하거나 상품명/조건의 텍스트 신호를 분류 사실로 승격하지 않는다.
R2 representative rate와 historical analogue는 이 gate가 해결되기 전까지
fail-closed다.

2026-08-31이 가장 이른 가능한 날짜라는 의미는 아니다. 이 문서는 실제로
검증한 날짜만 기록한다.

---

## 1. Historical FSB AREA + canonical institution identity

Evidence workflow run: `33651217860`

### 2026-03-31

- FSB institutions: 79
- FSB products: 391
- `YN_Busan`: 14 institutions
- point-in-time exact canonical identity mapped: **0 / 79**
- result: `insufficient_history`
- reason: `anchor_identity_not_proven_at_as_of`

공식 AREA 과거조회는 가능하지만 canonical identity의 당시 유효기간을 증명할 수
없다. 현재 identity를 3월로 carry-back하지 않는다.

### 2026-08-31

- FSB institutions: 79
- FSB products: 395
- point-in-time exact identity: **79 / 79**
- 고려저축은행 source code: `0010390`
- 고려저축은행 AREA: `YN_Busan`
- 부산 cohort: **14 source institutions / 14 canonical institutions**
- unproven identity: 0
- ambiguous identity: 0
- result: `availability_identity_evidence_ready`

---

## 2. Historical official rate + product identity

Evidence branch: `evidence/relative-pricing-r2-rate-20260903`

Workflow run: `33696640407`
Artifact: `relative-pricing-r2-rate-33696640407`
Artifact id: `9872082453`
Artifact ZIP SHA256:
`6170643068b5c4fc017b83cc3528699acf23833347226decba807adae3353dea`

2026-08-31 official FSB query:

- raw product rows: **395**
- parsed 12m rows: **633**
- 부산 cohort: **14 institutions**
- usable historical rate rows: **113**
- institutions with historical rate evidence: **14 / 14**
- missing-rate institutions: **0**
- future `source_effective_at` rows: **0**
- product exact-link missing rows: **0**
- product exact-link ambiguous rows: **0**
- primary FSB rate coverage: **14 / 14**
- 고려저축은행 raw FSB 12m max rate, historical special-offer filtering 전:
  **3.70%**

`3.70%`는 historical special-offer population gate가 열리기 전의 raw FSB max다.
R2 최종 representative rate라고 부르지 않는다.

### Network evidence harness

이전 run `33652479083`은 FSB `ConnectTimeout` 때문에 evidence 파일을 만들지 못했다.
후속 evidence harness는 timeout/network error만 3회 bounded retry하고, 최종 실패
시에도 `network_unavailable` / `official_source_network_unavailable` JSON을 남긴다.
스키마·identity·source contract 오류를 retry로 숨기지 않는다.

---

## 3. Historical special-offer provenance

Workflow run: `33697008139`
Artifact: `relative-pricing-r2-special-offer-33697008139`
Artifact id: `9872188046`
Artifact ZIP SHA256:
`a3eda7e6e4bc9c4fd477d86cb5425f0709e53d671be8de77004e4d536d04e63d`

2026-08-31 FSB raw census:

- product rows: **395**
- observed raw fields: **51**
- field names containing `SPECIAL`, `SALE`, `EVENT`, `PROMO`: **0**
- public text rows containing diagnostic signals: **7**
  - `한정`: 4 occurrences
  - `소진`: 3 occurrences
- these text matches are **diagnostic only**, not classification evidence

Production snapshot product flags:

- all products: **81,644**
- `is_special_sale=true`: **0**
- `sale_start` populated: **0**
- `sale_end` populated: **0**
- current FSB-linked products: **644**
- FSB special flags / sale dates populated: **0**
- source payload retained on FSB product links: **0**

The same zero-population pattern exists across active product links from the other
sources measured in the evidence run.

Result:

```text
historical_special_offer_gate = blocked
historical_special_offer_gate_reason = no_versioned_explicit_fsb_special_offer_field
current_product_flag_carryback = false
text_heuristic_promotion_allowed = false
```

---

## 4. Implemented R2 foundation contract

`relative_pricing_historical_service.py` is intentionally pure and does not perform
network or DB lookup. It accepts explicit point-in-time evidence and enforces:

1. exact snapshot date
2. exact historical institution/product identity evidence
3. no future source-effective rate
4. exact availability match key
5. current geography is never used
6. historical special-offer `unknown != false`
7. unknown special-offer state blocks representative-rate reduction
8. source precedence is applied only after all product-scope evidence is proven
9. special-only anchor with no core representative fails closed

The official historical query date is retained as the point-in-time rate snapshot.
An individual source disclosure date, when present, is separately checked for future
leakage and is never replaced by collection time.

---

## 5. Not verified / not activated

- historical special-offer classification semantics: **unverified / blocker**
- 2026-08-31 R2 representative rate: **not activated**
- historical funding join for R2: **not started as ready gate**
- historical peer rank / market regime similarity: **not activated**
- historical analogue UI: **not activated**
- causal effect of rate changes: **not claimed**

No production DB write or historical snapshot publish was performed by these evidence
runs.
