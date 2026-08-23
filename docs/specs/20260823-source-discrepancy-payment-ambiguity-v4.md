# 저축은행 원천 교차검증 v4 — payment-method ambiguity + raw provenance

기준일: 2026-08-23

관련 Issue: #98

Supersedes: `20260823-source-discrepancy-variant-freshness-v3.md`의 **현재값 해석 및 운영 감사 계약**. v3의 6D channel/method identity 원칙은 유지하되, 아래 forensic evidence와 payment-method fail-closed 규칙을 추가한다.

## 1. 목적

FSB ↔ FINLIFE ↔ 개별 저축은행 공식 공시를 비교할 때 source가 제공하지 않는 variant 차원을 억지로 추정하거나, 한 source 안의 서로 다른 적립방식 중 가장 높은 금리를 대표값으로 선택해 false mismatch를 만들지 않는다.

이번 단계는 데이터 품질 감사 계약만 강화한다.

변경하지 않는 것:

- canonical 금리
- source precedence / authority
- stable product identity
- DB schema / migration
- collector / schedule
- Strategy 계산
- Production Strategy Release Gate

## 2. 2026-08-23 forensic evidence

### 2.1 청주저축은행 정기적금

Fresh live collector capture에서 같은 `정기적금 / branch / simple` 6D key 안에 FINLIFE `payment_method`가 둘 존재함을 확인했다.

- 정액적립식(`rsrv_type=S`): 6개월 2.10%, 12개월 3.80%
- 자유적립식(`rsrv_type=F`): 6개월 3.05%, 12개월 4.00%
- FSB 정기적금(branch): 6개월 2.10%, 12개월 3.80%

Fresh capture evidence:

- FINLIFE forensic run `32634963067`: raw 7 / parsed 3,998 / valid 3,998 / error 0
- FSB forensic run `32635087753`: raw 13 / parsed 3,765 / valid 3,765 / error 0
- FSB 청주 raw: `rateinst_p3.json`, 정기적금, `JOIN_LOCATION=1`, 6m 2.10 / 12m 3.80, 기준일 2026-08-10

따라서 기존 0.95%p(6m), 0.20%p(12m) mismatch는 FINLIFE의 자유적립식 최고금리를 FSB의 정액식 surface와 비교한 **audit false positive**다. 어느 source의 금리를 자동으로 정정할 근거가 아니다.

### 2.2 대백저축은행 애플정기예금

Fresh FSB raw는 인터넷+스마트폰(`JOIN_LOCATION=2,3`) 12개월 단리/복리 nominal 4.10%를 제공한다.

2026-08-23 19:57:45 KST에 대백 공식 상품 페이지 4개를 GitHub runner에서 직접 HTTP capture한 결과도 모두 12개월 nominal 4.10%였다.

- 인터넷 단리 rnum=26: 4.10%
- 인터넷 복리 rnum=27: nominal 4.10% (연평균수익률 4.17%)
- 스마트뱅킹 단리 rnum=28: 4.10%
- 스마트뱅킹 복리 rnum=29: nominal 4.10% (연평균수익률 4.17%)

Direct-page evidence:

- workflow run `32635180304`
- artifact `9492104054`
- artifact SHA256 `27fac90b077761ed4a04475b45452acf878574d4c7ef89fd92cb152e21747a6a`

따라서 현재 truth는 **FSB = FINLIFE = bank-direct 4.10%**다.

v3/#187에서 기록된 인터넷 복리 4.00%, 모바일 단리 3.80%는 현재 live page와 일치하지 않는다. 당시 raw HTML이 보존되지 않았으므로 다음 둘 중 어느 것인지 단정하지 않는다.

1. 16:01~19:57 사이 은행 공시가 실제 변경됨
2. 당시 검색 cache / 수동 capture가 stale 또는 잘못됨

이 구분은 추측하지 않고 **historical provenance gap**으로 남긴다.

## 3. source-source identity는 6D를 유지한다

기본 automatic key는 v3와 동일하다.

`normalized institution + normalized product + product type + term + join_channel + interest_method`

`payment_method`를 무조건 7번째 strict key로 추가하지 않는다. 이유는 FSB가 정액/자유 적립식 차원을 제공하지 않는 경우가 있어 7D exact match를 강제하면 실제 비교 가능한 적금까지 대량으로 source-only 처리할 수 있기 때문이다.

## 4. payment_method ambiguity fail-closed

각 source에서 동일한 6D key의 후보들을 먼저 본다.

### 4.1 비교 차단 조건

다음 두 조건이 동시에 참이면 해당 6D key를 일반 rate comparison에서 제외한다.

1. `payment_method` 값이 둘 이상 존재
2. `(base_rate, max_rate)` 조합도 둘 이상 존재

이 경우:

- 최고금리 한 행을 대표로 선택하지 않는다.
- `ambiguous_variant_dimension`으로 surfaced한다.
- `dimension=payment_method`를 기록한다.
- 후보 payment method, rate, source locator, raw artifact provenance를 보존한다.
- P0~P3 rate-mismatch queue에는 넣지 않는다.

### 4.2 비교 허용 조건

payment method가 여러 개여도 rate pair가 모두 동일하다면 금리 감사 결론은 동일하므로 기존 6D 비교를 허용한다.

같은 payment method의 중복 행은 기존 representative 규칙을 유지한다.

## 5. official evidence provenance v4

현재값을 주장하는 bank-direct evidence는 가능한 경우 다음을 함께 보존한다.

- URL
- `captured_at`
- `capture_method`
- workflow/run identifier
- artifact identifier
- raw HTML 또는 response artifact
- nominal rate와 annualized yield의 구분

검색 결과 snippet/cache만으로 현재 truth를 확정하지 않는다.

Freshness/provenance는 authority score가 아니다. 더 최근에 캡처됐다는 이유만으로 canonical source를 자동 교체하지 않는다.

## 6. downstream semantics

- `dimension_ambiguities`는 source mismatch queue와 별도다.
- P0~P3는 **실제로 비교 가능한 source pair**의 mismatch/incomplete만 정렬한다.
- official contradiction queue도 ambiguity가 해소된 source candidate에 대해서만 생성한다.
- 대백 current official evidence 4개 surface는 각각 4.10%로 평가한다.
- 청주 6/12개월은 payment-method ambiguity로 surfaced하며, 자유적립식 최고금리를 임의로 FSB와 비교하지 않는다.

## 7. 운영 Evidence Gate

실행 경로:

`production R2 restore(read-only runner-local copy) → local migration → 6D source audit + payment-method ambiguity detection → dated official evidence → P0~P3 + official contradiction queue → artifact`

금지:

- production DB write
- R2 canonical write
- rate-data write
- canonical silent overwrite
- source precedence / authority 자동선택
- DB schema / migration 변경
- collector / schedule 변경
- Strategy 계산 / Release Gate 변경

## 8. Acceptance

- payment_method가 다르고 rate도 다른 동일 6D 후보는 fail-closed 된다.
- payment_method가 달라도 rate가 동일하면 비교 가능하다.
- 청주 정기적금 6/12개월이 `dimension_ambiguities`에 surfaced 된다.
- 청주 6/12개월 false mismatch가 P0~P3 queue에서 제거된다.
- 대백 4개 official evidence group이 모두 current 4.10%로 평가된다.
- 대백 current official contradiction이 남지 않는다.
- provenance에 payment_method와 raw/source locator가 보존된다.
- General CI: Ruff / full pytest / empty DB migration/model parity 통과.
- production R2 read-only discrepancy audit 통과.
- 최신 P0/P1/P2/P3, dimension ambiguity, official contradiction 결과를 artifact와 Issue #98에 기록한다.

## 9. 비범위

- canonical 금리 수정
- source precedence 변경
- payment_method를 stable/canonical identity에 강제 편입
- historical DB destructive repair
- 자동 bank-direct crawler의 본 구현
- Strategy 경고 UI
