# Special-offer Radar R3-A/R3-B official evidence capture

기준일: 2026-09-23

## 결론

공식 금융사 상품 상세/공지에서 상품 단위의 명시적 특판 근거를 확보할 수 있다.
다만 특판 분류와 현재 판매상태는 별도 차원이다. 과거 특판 상세페이지가 계속
열려 있을 수 있으므로 `confirmed_special`은 "특판으로 명시되었다"는 뜻이지
"현재 판매 중"이라는 뜻이 아니다.

## 확인된 source 유형

1. 웰컴저축은행 상품 상세 — URL `prdCd`와 명시적 특판 문구.
2. IBK저축은행 상품 상세 — 상품 상세 경로와 구조화된 `특판내용` 섹션.
3. 대신저축은행 공식 공지 — 상품명, 특판금리, 적용기간을 함께 명시.

구체 target은 `config/special_offer_official_targets.json`에 고정한다.

## R3-B capture 계약

`scripts/special_offer_official_capture.py`는 다음만 한다.

- 저장소에 미리 등록한 HTTPS URL만 GET한다.
- raw HTML을 그대로 보존한다.
- raw body SHA-256, final URL, HTTP status를 기록한다.
- target별 explicit phrase와 official product key가 동시에 확인될 때만
  `confirmed_special_candidate`를 만든다.
- 적용기간이 설정된 target은
  `versioned_product_scope_observation` 후보로 표시한다.
- DB, canonical rates, `product_special_offer_evidence`를 쓰지 않는다.

따라서 capture 결과는 **candidate**일 뿐 confirmed evidence가 아니다.

## 다음 Gate — exact FSB binding

candidate를 실제 evidence registry에 넣기 전에 production-copy DB에서 반드시:

1. 같은 기관의 FSB `SourceEntityLink`를 확인한다.
2. active `exact_code` product link가 정확히 하나여야 한다.
3. official target과 FSB source product key의 연결을 추정명칭이 아니라 검증된
   mapping으로 확정한다.
4. bind 실패/복수 매칭은 `unknown`을 유지하고 audit 결과만 남긴다.

현재 R3-B PR에서는 이 DB binding을 수행하지 않는다. 즉 Radar confirmed count를
억지로 증가시키지 않는다.

## Availability

특판 분류와 현재 판매상태는 분리한다. Radar에서 "현재 특판"으로 노출하려면
후속 activation review에서 별도 availability evidence를 요구한다.

## 금지

- 상품명에 `특판`이 들어간다는 이유만으로 confirmation
- 문구를 찾지 못했다는 이유로 `confirmed_normal`
- 현재 페이지를 명시 적용기간 없이 과거로 소급
- name-only FSB binding
- capture 단계에서 production DB write
