# Special-offer Radar R3 — official source discovery

기준일: 2026-09-23  
대상 Issue: #347

## 1. 결론

FSB 일반 금리 공시는 상품의 특판 여부를 명시하지 않으므로 기존 `unknown`
정책을 유지한다. 다만 공식 저축은행 상품 상세/공지에서는 상품 단위의 명시적
특판 근거를 실제로 확인할 수 있었다.

따라서 Radar는 폐기하지 않는다. R3는 다음 두 축을 분리한다.

1. `special classification`: 이 상품이 공식적으로 특판으로 명시되었는가.
2. `availability`: 그 특판이 현재 판매 중인가.

과거 특판 상품의 상세페이지가 계속 접근 가능한 사례가 있으므로
`confirmed_special`을 곧바로 "현재 판매 중인 특판"으로 해석하지 않는다.

## 2. 확인한 공식 source 유형

### A. 공식 상품 상세 — 웰컴저축은행

#### 웰뱅 라이킷(LIKIT) 적금

- 공식 URL:
  `https://www.welcomebank.co.kr/ib20/mnu/IBNFPMDSP002?ib20_wc=IBNFPMDSP001_00%3AIBNFPMCMN001_00&prdCd=1130313563&sysDsCd=01`
- URL product locator: `prdCd=1130313563`
- 페이지 자체 문구: `롯데카드 X 웰컴 한정 특판`
- 상품 단위 special classification 근거로 사용할 수 있다.
- 별도 공식 판매중지 목록에도 동일 상품이 존재한다:
  `https://www.welcomebank.co.kr/ib20/mnu/IBNFPMDSP008`

즉 상품 상세의 특판 명시는 classification 근거이지 current availability 근거가
아니다.

#### 웰컴 디지로카 100일적금

- 공식 URL:
  `https://www.welcomebank.co.kr/ib20/mnu/IBNFPMDSP002?ib20_wc=IBNFPMDSP001_00%3AIBNFPMCMN001_00&prdCd=1130313564&sysDsCd=01`
- URL product locator: `prdCd=1130313564`
- 페이지 자체 문구: `본 상품은 1만좌 한도 특판 상품`
- 명시 특판기간: `2024.07.22 ~ 2024.12.31`, 소진 시 조기 종료

명시 적용기간이 있으므로
`versioned_product_scope_observation` 후보가 된다.

### B. 공식 상품 상세의 구조화 특판 섹션 — IBK저축은행

#### 특판 청룡비상(靑龍飛上)정기적금

- 공식 URL: `https://www.ibksb.co.kr/m/deposit/502132836`
- 상품 제목 자체가 `특판 청룡비상(靑龍飛上)정기적금`
- 별도 `특판내용` 섹션이 존재한다.
- 계약고 100억원 한도, 가입기간 12개월, 1인 1계좌 등 상품 범위가 명시된다.

자유문구에서 "특판"이라는 단어를 찾는 휴리스틱이 아니라 공식 product detail의
상품 제목/구조화 섹션을 함께 확인하는 경우에만 candidate로 인정한다.

### C. 공식 공지의 기간형 상품 범위 — 대신저축은행

#### 기업자유예금 특판 안내

- 공식 URL:
  `https://bank.daishin.com/sub.do?category=&code=03_news02&keyword=&mode=view&no=588&page=4&search=`
- 상품명: `기업자유예금`
- 특판금리: 연 3.20%
- 기간: `2024.09.26 ~ 2026.06.25`, 한도 소진 시 조기마감
- 특판 종료 후 공시금리 적용도 명시

명시적인 effective period를 가진
`versioned_product_scope_observation`의 근거가 될 수 있다.

단, 현재 FSB collector는 입출금자유예금 수집이 미해소이므로 이 상품이 현재
production DB의 exact FSB product identity에 bind되는지는 별도 runtime audit이
필요하다.

## 3. Evidence Gate

확인 결과:

- 명시적 특판 판정: 가능
- 상품 단위 locator: 가능
- 적용기간: source에 명시된 경우에만 사용 가능
- 현재 판매상태: 특판 classification과 별도 판단 필요
- FSB `unknown`: 유지
- 상품명에 "특판"이 포함되었다는 사실만으로 확정: 금지
- 특판 문구가 없다는 이유로 `confirmed_normal`: 금지
- current page를 과거에 소급: 금지
- source precedence/ranking population 변경: 금지

## 4. R3-B capture contract

이번 단계의 자동화는 DB에 confirmed evidence를 쓰지 않는다.

1. repository config에 등록된 HTTPS 공식 URL만 요청한다.
2. raw body, final URL, HTTP status, content type, captured_at, SHA-256을 보존한다.
3. parser는 config의 exact product title과 source별 explicit special marker를 모두
   확인해야 한다.
4. 조건이 하나라도 맞지 않으면 fail closed한다.
5. candidate의 `availability`는 별도 explicit 근거가 없으면
   `not_inferred`로 둔다.
6. production R2를 runner-local copy로 복원해 기존 FSB exact-code
   `SourceEntityLink`와 연결 가능성만 read-only audit한다.
7. exact binding을 증명하기 전에는 `confirmed_special` DB write를 하지 않는다.

## 5. 다음 단계

R3-B 다음 단계에서 runtime evidence를 보고 다음 중 하나로 진행한다.

- unique exact FSB binding이 확인된 source:
  기존 append-only evidence service를 통해 별도 검수 후 confirmation 경로 설계.
- 0건 또는 복수 binding:
  product identity 근거를 추가 확보할 때까지 `unknown` 유지.
- 현재 판매 여부:
  product classification과 별도 availability source/contract를 정의한 후 Radar의
  current offer 노출 조건에 사용.

Radar 활성화는 confirmed coverage와 current-availability 의미가 모두 검증된 뒤
별도 activation review에서 판단한다.
