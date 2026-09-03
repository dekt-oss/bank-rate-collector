# Relative Pricing R2 — FSB `PRODUCT_URL` provenance evidence

```yaml
date: 2026-09-03
as_of: 2026-08-31
scope: savings_bank / term_deposit / 12m / FSB YN_Busan
workflow_run: 33715854914
workflow_job: 100524773073
artifact: relative-pricing-r2-product-url-33715854914
artifact_id: 9878512199
artifact_zip_sha256: 1353bb4b61f894f698434a72272faa1b3612b067eda6d6a0049dfc3af4d5cec2
production_write: false
decision: historical_special_offer_provenance_unavailable
r2_historical_analogue: inactive
```

## 결론

FSB의 historical `PRODUCT_URL`을 bank-direct 공식 상품 페이지와 연결해도
2026-08-31 당시의 특판 여부를 versioned fact로 재구성할 수 없다.

- 부산 가입 가능 12개월 금리 상품 57개 중 57개 모두 URL host gate를 통과했다.
- 실제 HTTP 200으로 확인한 상품 row는 40개였다.
- 57개 상품이 가리키는 URL은 34개뿐이었다.
- 34개 상품은 11개의 shared/general URL을 사용해 exact product page가 아니었다.
- 화면 text signal 2건은 OSB 공통 메뉴의 `판매종료상품안내` 문구였으며 해당 두
  product의 상태나 특판 여부를 증명하지 않았다.
- historical special-offer state로 분류 가능한 product는 0개였다.

따라서 `PRODUCT_URL`은 보조 provenance locator로는 보존할 수 있지만,
`special_offer_flag` writer나 historical product-scope observation으로 승격하지 않는다.
R2 historical analogue는 명세의 evidence gate에 따라 **비활성 상태로 종료**한다.

---

## 1. Evidence boundary

Workflow는 FSB가 2026-08-31 snapshot row에 직접 제공한 exact key와 URL만 사용했다.

```text
FINAN_COMP_CODE + FINAN_PROD_CODE
→ FSB PRODUCT_URL
→ host validation
→ bounded HTTPS fetch
→ visible page text diagnostic
```

안전 경계:

- FSB `URL` host와 일치하거나 FSB-hosted disclosure인 URL만 허용
- HTTP URL은 HTTPS upgrade probe만 수행
- unrelated redirect host는 거부
- script/style/noscript text 제외
- full response SHA256 및 final URL 보존
- page capture 시각과 historical `as_of` 분리
- production DB/write 없음

---

## 2. Census result

| 항목 | 결과 |
|---|---:|
| FSB 부산 AREA raw rows | 67 |
| 12개월 rate candidate products | 57 |
| approved/upgraded URLs | 57 |
| unique product URLs | 34 |
| shared URL groups | 11 |
| products on shared URLs | 34 |
| HTTP 200 product rows | 40 |
| network error product rows | 17 |
| visible text signal rows | 2 |
| historical classified products | **0** |

17개 network error는 IBK 4개, 국제 1개, 진주 7개, 흥국 5개 상품이었다. 이 실패를
`normal` 또는 `not special`로 해석하지 않는다.

---

## 3. Exact-product counter-evidence

동일 URL이 서로 다른 product key를 가리키는 대표 사례:

| institution | shared URL product count | example |
|---|---:|---|
| 진주 | 7 | 대면·비대면·지역별 정기예금이 동일 `rnum=27` 사용 |
| 흥국 | 5 | E/S/비대면/강남/부산 정기예금이 동일 URL 사용 |
| IBK | 4 | 회전예금과 `참기특한정기예금`이 동일 `/deposit` 사용 |
| 웰컴 | 3 | 대면·인터넷·모바일 상품이 홈페이지 root 사용 |
| 솔브레인 | 3 | 서로 다른 정기예금 product key가 동일 상품 URL 사용 |

FSB exact product key와 `PRODUCT_URL` 사이가 일대일이라는 보장이 없으므로, 페이지의
문구를 해당 product key의 속성으로 자동 귀속할 수 없다.

## 4. Temporal counter-evidence

페이지는 2026-09-03에 capture됐다. FSB row는 2026-08-31 snapshot에서 왔더라도,
페이지 본문이 8월 31일 당시와 동일했다는 version evidence는 없다.

따라서 다음 추론을 모두 금지한다.

- 현재 페이지에 `특판` 존재 → 2026-08-31에도 특판
- 현재 페이지에 특판 문구 없음 → 2026-08-31 일반상품
- 현재 페이지에 `판매종료` 존재 → snapshot 당시 판매 종료
- URL이 동일함 → exact product page

## 5. Final R2 gate

```text
historical_special_offer_gate = blocked
reason = no_versioned_explicit_special_offer_provenance
PRODUCT_URL_role = diagnostic_locator_only
current_page_carryback = prohibited
absence_as_false = prohibited
historical_representative_rate = inactive
historical_peer_rank = inactive
historical_analogue = inactive
```

이는 구현 실패가 아니라 명세의 의도된 fail-closed 결과다. R2 foundation과 funding
point-in-time adapter는 보존하되, source evidence가 없는 historical rate population을
억지로 생성하지 않는다.

## 6. Reopen condition

R2 historical analogue는 다음 중 하나가 확보될 때만 다시 연다.

1. FSB 또는 은행의 versioned explicit special-offer field
2. exact product key에 연결된 당시 공시 원문과 유효기간
3. 상품별 immutable disclosure archive로 2026-08-31 상태를 직접 증명하는 공식 자료

단순 검색결과, 현재 홈페이지, 상품명 heuristic은 reopen evidence가 아니다.
