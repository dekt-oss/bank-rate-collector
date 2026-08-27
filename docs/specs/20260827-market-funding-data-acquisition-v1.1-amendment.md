# 수신시장 데이터 수집 작업명세 v1.1 — Stage 0 정정

- Date: 2026-08-27
- Applies to: `docs/specs/20260827-market-funding-data-acquisition-v1.1.md`
- Reason: adversarial self-review에서 Stage 0/D0 순서 모순 발견

## 정정 대상

v1.1 §3.1에는 `Quantity`의 정확한 폭을 D0 range/precision evidence 이후 확정한다고 적었으나, 같은 문서의 전체 실행순서는 **Stage 0 저장능력 개선 → D0 source recon**이다.

이 둘을 동시에 적용할 수 없으므로 아래 규칙이 우선한다.

## authoritative rule

### 1. Stage 0에서 `Quantity` 저장 contract를 먼저 확정한다

D0 결과에 의존하지 않는 충분한 capacity를 선택한다.

v1 권장 contract:

```text
non-negative fixed decimal
INT_DIGITS = 12
DEC_DIGITS = 6
MAX = 999999999999.999999
SQLite storage = zero-padded fixed decimal string
```

목적:

- 현재 `Rate`의 999.9999 상한 제거
- 은행 수신잔액처럼 1,000조원을 초과하는 normalized `trillion_krw` 값 수용
- 기존 market-indicator 금리값도 lossless 저장
- SQLite `Numeric`/float round-trip 회피

`Rate` 자체는 변경하지 않는다.

### 2. D0 range/precision gate의 역할

D0는 `Quantity` 타입 설계를 뒤늦게 결정하는 단계가 아니다.

대신 **각 신규 source contract가 이미 정해진 Quantity 범위와 precision 안에 안전하게 들어오는지 증명**한다.

검증:

- observed min/max
- sign
- source decimal precision
- unit normalization 이후 max/precision

신규 source가 v1 Quantity capacity를 초과하면 해당 source를 저장하지 않고 별도 schema decision gate를 연다.

### 3. migration acceptance

Stage 0 migration은 D0 이전에 다음을 증명한다.

- 기존 `market_indicators` 모든 Decimal 값 동일
- 기존 row count 동일
- source/code/effective date 동일
- 기존 7개 ECOS macro series latest numeric value 동일
- `Rate`를 사용하는 상품금리 테이블 영향 없음
- 1,000조원 초과 synthetic quantity round-trip 성공

## precedence

이 정정문은 `docs/specs/20260827-market-funding-data-acquisition-v1.1.md` §3.1의 "D0 이후 정확한 폭 확정" 문장보다 우선한다. 그 외 v1.1 내용은 그대로 유지한다.
