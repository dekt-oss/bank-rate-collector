# Special-offer Radar R3-C — availability and structured terms

기준일: 2026-09-24  
대상 Issue: #350

## 1. 사용자 결정

Radar는 다음 두 업무 화면으로 분리한다.

- 현재 판매 중인 특판
- 과거 특판 이력

특판 근거가 확보되면 다음을 구조화한다.

- 특판금리
- 판매기간
- 한도
- 가입대상
- 조기종료 조건

## 2. Classification과 availability는 별도 계약

`confirmed_special`은 공식 source가 해당 상품을 특판이라고 명시했다는 뜻이다.
그 사실만으로 현재 가입 가능하다고 보지 않는다.

availability는 3상태다.

- `confirmed_active`: 현재 판매 중임을 별도 공식 근거가 명시
- `confirmed_ended`: 판매중지/종료/마감 근거가 있거나 명시 판매기간이 이미 종료
- `unknown`: 특판 분류는 확인했지만 현재 판매상태를 확정할 수 없음

미래 종료일만 있다는 이유로 `confirmed_active`를 만들지 않는다. 한도 소진 시
조기 종료 조건이 있는 상품은 특히 이 원칙을 지킨다.

## 3. 2026-09-24 공식 source 재확인

### 웰컴저축은행 — 웰뱅 라이킷(LIKIT) 적금

- 공식 상품 상세 `prdCd=1130313563`에서 명시적 한정 특판, 가입대상, 1만좌 한도 확인
- 별도 공식 판매중지상품 목록에서 동일 상품을 확인할 수 있어 종료 근거로 분리 사용

### 웰컴저축은행 — 웰컴 디지로카 100일적금

- 공식 상품 상세 `prdCd=1130313564`
- 1만좌 한도 특판
- 특판기간 2024-07-22 ~ 2024-12-31
- 특판 소진 시 조기 종료
- 현재 기준 명시 판매기간이 종료되어 historical evidence 후보

### IBK저축은행 — 특판 청룡비상 정기적금

- 공식 상품 상세 `/m/deposit/502132836`
- 특판내용 섹션
- 금리 4.90%
- 계약고 100억원 한도
- 가입대상 제한없음(1인 1계좌)
- 현재 판매 여부는 상세페이지 존재만으로 확정하지 않음

### 대신저축은행 — 기업자유예금 특판 안내

공식 공지 `no=588`을 2026-09-24 다시 확인한 결과 현재 페이지는 다음을 명시한다.

- 특판금리 연 3.30%
- 기간 2024-09-26 ~ 2026-12-28
- 2,000억원 한도
- 한도 소진 시 조기마감
- 해당기간 신규계좌 50억원 이상 예치
- 가입대상 법인, 개인사업자

따라서 금리/기간을 config 상수로 고정하지 않고 매 capture에서 공식 페이지를
구조화한다. 종료일이 미래여도 조기마감 조건이 있으므로 현재 판매 중으로
자동 승격하지 않는다.

## 4. Radar read model

- current tab: `confirmed_special + confirmed_active`
- history tab: 종료가 확인된 append-only `confirmed_special` evidence
- availability unknown: 어느 탭에도 넣지 않고 coverage count만 표시
- 과거 이력은 현재 snapshot resolver에 섞지 않고 evidence history에서 별도 조회

## 5. FSB binding Gate

공식 page candidate는 곧바로 confirmed evidence가 아니다. production-copy DB에서
active FSB `exact_code` link에 유일하게 연결 가능한지를 read-only로 감사한다.
alias match 자체는 confirmation이 아니다.

## 6. 이번 단계의 금지

- production DB write
- special-offer registry 자동 append
- 미래 sale_end만으로 active 판정
- 페이지 접근 가능만으로 active 판정
- name-only confirmation
- 일반 경쟁순위/Relative Pricing 모집단 변경

## 7. 첫 production-copy evidence 결과

Run `35879974171`의 첫 live capture에서 다음을 확인했다.

- 웰컴 LIKIT: 공식 판매중지 surface로 `confirmed_ended` 후보
- 웰컴 디지로카: 명시 판매기간 종료로 `confirmed_ended` 후보
- 대신 기업자유예금: 특판금리 3.30%, 2026-12-28까지이나 조기마감 조건이 있어
  availability는 `unknown`
- IBK: 상품 근거가 아니라 GitHub runner의 TLS certificate-chain 검증에서 실패
- production FSB exact-code alias binding: 4개 target 모두 0건

마지막 항목은 confirmed evidence를 만들지 말아야 한다는 뜻이다. 공식 은행 페이지
근거와 production FSB identity가 검증 가능한 동일 상품으로 연결되기 전까지
registry 자동 append를 하지 않는다.

IBK TLS 문제는 `verify=False`로 우회하지 않는다. project dependency인
`httpx`/certifi trust store를 사용해 TLS verification을 유지한 상태로 재검증한다.
