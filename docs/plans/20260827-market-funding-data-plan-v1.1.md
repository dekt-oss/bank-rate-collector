# 수신시장 데이터 수집·정리 기획서 v1.1

- Date: 2026-08-27
- Status: **Reviewed — Claude APPROVE WITH CHANGES 반영**
- Base: `main@b3ec3ba7e0c03f545c94ea99497598de0c04be2c`
- Supersedes: `docs/plans/20260827-market-funding-data-plan-v1.md`
- Scope: 데이터 수집·정규화·검증·저장 기반만. UI와 인과모델은 후속.

## 1. 목표

금리수집기에 업권·기관별 **수신자금 이동을 관측할 수 있는 신뢰 가능한 외부데이터 기반**을 추가한다.

이번 단계가 답할 질문:

1. 은행·저축은행·신협·광의 상호금융·새마을금고의 수신잔액이 월/분기별로 어떻게 변했는가?
2. 같은 기간 업권 대표 수신금리는 어떻게 변했는가?
3. 저축은행·신협·농협 등 개별 기관의 예수금/수신규모를 어디까지 공개자료로 추적할 수 있는가?
4. 향후 금리 변화와 수신 변화의 **동행성**을 분석할 수 있도록 시점·주기·단위·말잔/평잔·revision provenance를 보존할 수 있는가?

`금리 +10bp 때문에 수신이 X% 늘었다` 같은 인과 판정은 이번 범위가 아니다.

## 2. 후속 사용자 가치

### 업권별 자금이동

후속 화면에서 다음 구조를 목표로 한다.

| 업권 | 대표 수신금리 | 금리 전월비 | 수신잔액 | 월간 증감 |
|---|---:|---:|---:|---:|
| 은행 | 3.10% | -5bp | 2,150조 | -8.2조 |
| 저축은행 | 3.62% | +14bp | 104조 | +1.8조 |
| 신협 | 3.70% | +8bp | 160조 | +0.9조 |
| 광의 상호금융 | 3.45% | +3bp | 520조 | +1.2조 |
| 새마을금고 | 3.71% | +15bp | 270조 | +2.1조 |

위 숫자는 예시다. 특히 **은행 1,000조원 초과 잔액은 현재 `market_indicators.value=Rate`로 저장할 수 없으므로 Stage 0 저장타입 개선이 선행**되어야 한다.

### 개별기관 수신 경쟁력

FISIS/금융공공데이터에서 기관별 예수금이 확보되면 공시금리 위치와 QoQ/YoY 예수금 성장을 나란히 비교한다. 결과는 탐색 신호이며 인과효과로 표현하지 않는다.

## 3. 범위

포함:

- 기존 ECOS macro 저장능력·provenance·fail-closed 계약 보강
- ECOS 비은행 업권 금리, 은행 종별 수신잔액 exact series 정찰
- FISIS/금융공공데이터의 기관별 예수금/재무지표 정찰
- rolling collection과 historical backfill 분리
- raw artifact, revision audit, missing/duplicate 품질관리

제외:

- Strategy UI
- `10bp당 수신효과` 등 인과모델
- 내부 수신데이터
- 특판 레이더 구현

특판 정책은 별도 유지한다.

- 시중은행 특판: `시장 특판 레이더 / 벤치마킹`
- 저축은행·신협·MG·농축협 특판: 직접 경쟁시장 내 별도 속성

## 4. Current State

현재 `bok_ecos_macro`는 최근 48개월 월간 데이터를 수집한다.

검증 완료 contract:

- `121Y002 / BEABAA2` 예금은행 저축성수신 신규취급금리
- `121Y002 / BEABAA21` 순수저축성예금 신규취급금리
- `121Y002 / BEABAA2118` 1년 정기예금 신규취급금리
- `111Y007 / 1120600` 저축은행 수신 말잔
- `111Y007 / 1120700` 신협 수신 말잔
- `111Y007 / 1120800` 광의 상호금융 수신 말잔
- `111Y007 / 1121000` 새마을금고 수신 말잔

`1120800 상호금융`은 농협·수협·산림조합을 포괄하는 광의 개념이며 `nh_local`과 동일시하지 않는다.

### 코드 기준 확인된 위험

Claude 리뷰에서 다음이 확인됐다.

1. `market_indicators.value`의 `Rate` 상한은 999.9999라 대형 잔액을 저장할 수 없다.
2. 현재 parser는 일부 단위/항목/범위 drift를 warning 후 row skip한다.
3. warning 원문은 DB에 남지 않고 count만 남는다.
4. 같은 point 수정 시 기존 value/raw artifact/observed_at이 overwrite되어 revision provenance가 사라진다.
5. ECOS page size 100과 `list_total_count` 미검증 때문에 장기 backfill은 silent truncation 위험이 있다.
6. macro는 현재 평일 일반 collection에 포함돼 48개월을 반복 조회한다.

따라서 새 series 추가보다 **저장능력·감사계약 보강이 먼저**다.

## 5. 데이터 소스 우선순위

### Tier A — ECOS

이미 확보:

- 은행 수신금리 3종
- 저축은행/신협/광의 상호금융/MG 월말 수신잔액

D0 확인 대상:

- 비은행 업권 대표 수신금리 series 존재 여부와 exact code
- 은행 총수신/정기예금/정기적금 잔액 series 존재 여부와 exact code
- `111Y008` 평잔 item 체계
- ECOS `RESULT` 중 no-data code
- 공표일 제공 여부
- 실제 min/max/precision

비은행 금리가 ECOS에 없으면 상품 collector의 공시금리 통계를 별도 의미로 사용할 수 있으나, 이를 신규취급 가중평균금리와 동일시하지 않는다.

### Tier A/B — FISIS / 금융공공데이터

우선순위:

1. 저축은행
2. 신협
3. 농협
4. 필요 시 수협/산림조합

실조회 전에는 endpoint, metric code, 단위, 주기, 최초 시계열, publication lag, rate limit, 기관코드 매핑률을 확정하지 않는다.

### Tier B — 중앙회 장기통계

신협/MG 연간·분기 자료는 CAGR, 지역 수신구조, 상품구성 변화에 사용한다. 월별 금리반응 분석에 억지로 사용하지 않는다.

개별 MG 예수금 공개원천은 D0에서 **존재 여부부터** 판정한다.

## 6. 데이터 관리 원칙

### 원천값 우선

영구 저장 후보:

- 말잔/분기말 수신잔액
- 신규취급 가중평균 수신금리
- 검증된 기관별 예수금/재무항목

MoM/QoQ/YoY, bp 변화, 시장점유, T+1/T+2 동행성은 후속 계산 계층에서 산출한다.

### 시간 의미

- `source_effective_at` / `period_end`: 값이 의미하는 시점
- `observed_at`: 우리가 받은 시각
- `published_at`: 원천이 명시할 때만
- `frequency`: M/Q/A
- `value_semantics`: stock / flow / rate
- `balance_basis`: eom / average / n/a

`observed_at - source_effective_at`을 실제 publication lag라고 부르지 않는다.

### 금리와 잔액 정렬

월말 잔액은 `stock_eom`, 월간 신규취급금리는 `flow_weighted_avg_of_month`다.

동행성은 금리 레벨과 잔액 레벨의 단순상관이 아니라 다음과 같은 **잔액 증감**을 사용한다.

`Δbalance(M) = balance_eom(M) - balance_eom(M-1)`

### 단위와 SQLite

- 원천 문자열/단위는 raw artifact 또는 source field로 보존
- normalized unit은 contract로 고정
- SQLite에서 신규 금융수량을 `Numeric`으로 저장하지 않음
- 큰 수량은 고정소수 문자열 TypeDecorator 사용

### missing과 revision

- missing은 0이 아니다.
- canonical row를 source revision으로 갱신할 경우 overwrite 전에 `review_items`에 old/new value, hash, artifact, observed_at, locator를 남긴다.
- revision audit 없이 과거 값을 조용히 덮어쓰지 않는다.

## 7. Target 데이터 계층

### Layer A — `market_indicators`

기존 테이블을 재사용하되 Stage 0가 필요하다.

- `value`: `Rate` 대신 대형 수량도 lossless한 `Quantity` 계열 타입
- 기존 상품금리용 `Rate`는 변경하지 않음
- v1 Layer A는 월간 series만 허용
- ECOS macro `source_effective_at`은 NOT NULL contract
- frequency/value semantics/balance basis를 소비자가 `indicator_name` 문자열에서 추론하지 않도록 명시적 contract로 관리

### Layer B — `institution_funding_observations`

자연키 중심:

`(source_id, source_entity_code, metric_code, period_end, frequency)`

기관 매핑의 Source of Truth는 기존 `source_entity_links`다.

- observation에 별도 canonical `institution_id` 진실원을 만들지 않음
- exact-code 근거가 있을 때만 link 생성
- fuzzy name 자동 병합 금지
- 미매핑 observation은 저장하고 QA에서 비율 집계

value는 SQLite-safe fixed-decimal 문자열 타입을 쓴다.

## 8. Fail-closed 목표

다음 drift는 warning + 일부 row 저장으로 끝내지 않는다.

- stat/metric code mismatch
- contract-breaking item name change
- unit drift
- parse/range failure
- pagination count mismatch

**contract 단위 all-or-nothing**을 기본으로 한다. 구조적 drift가 있으면 그 contract 실행값을 저장하지 않고 `review_items`에 error를 남긴다.

ECOS HTTP 200 `RESULT`의 오류/no-data 분기는 D0 실조회 evidence 후에만 구현한다.

## 9. Backfill

기간만 48개월→수백개월로 늘리지 않는다.

필수 gate:

- `list_total_count` 확인
- page/chunk 반복
- 요청·응답 TIME 범위 대조
- duplicate/missing 검사
- 전체 count 검증
- no-data code 분리

## 10. 실행 순서

### Stage 0 — 저장능력/안전계약

새 series 추가 0개.

1. `Quantity` 계열 타입
2. `market_indicators.value` migration
3. 기존 7개 series 값 회귀 없음 검증
4. revision audit 정책
5. parser drift/error 원문 persistence
6. `CONTRACT_BY_ITEM` 제거 또는 `(stat_code,item_code)` 복합키화

### D0 — read-only recon

Production DB write 0.

- ECOS exact series/no-data/published/min-max/precision 정찰
- FISIS/공공데이터 endpoint/metric/unit/frequency/history 정찰
- 외부기관코드 exact mapping률 측정
- 개별 MG 예수금 원천 존재 여부 확인
- 기존 `market_indicators` revision/관측지연 패턴 read-only 감사

### D1a — 비은행 업권 금리

D0에서 공식 exact contract가 확인된 경우만.

### D1b — 은행 종별 수신잔액

Stage 0 + D0 exact contract가 모두 완료된 경우만.

### D1c — historical backfill

pagination/no-data gate를 가진 전용 경로로 rolling collection과 분리.

### D2a — 저축은행 개별기관 funding

Layer B + exact-code mapping.

### D2b — 신협/농협

D2a contract가 해당 source에도 성립할 때만.

### D3 — audit/report

missing/duplicate/revision/unmapped/parser error/last available period를 보고한다.

## 11. 인과 해석 제한

1. 잔액 레벨과 금리 레벨의 단순상관을 금지한다.
2. 업권 수신변화에는 만기구조·정책·계절성·기관 편입변화가 섞인다.
3. lead-lag에 `효과`, `설명력`, `인과`라는 표현을 자동 부여하지 않는다.
4. 표본 길이를 함께 표시한다.
5. 합병·인가취소·신규편입에 따른 stock jump를 자금이동으로 오인할 수 있음을 명시한다.

## 12. 완료 기준

- 기존 7개 ECOS macro series 회귀 없음
- 1,000조원 초과 수량 lossless 저장
- 상품금리 `Rate` 영향 없음
- exact contract 없는 series persistence 금지
- unit/frequency/semantics/basis 추적 가능
- partial row-drop으로 green 처리하지 않음
- warning/error 원문 감사 가능
- revision 전후 값/artifact 역추적 가능
- missing과 zero 구분
- backfill 100-row silent truncation 방지
- 검증된 no-data/error 분기
- `source_entity_links` 단일 매핑 진실원
- fuzzy institution auto-merge 없음
- unmapped ratio 보고 가능
- UI/인과모델 변경 없음

## 13. Claude 리뷰 반영표

- M1 수량 저장상한 → Stage 0 `Quantity`
- M2 SQLite `Numeric` 금지 → fixed-decimal TypeDecorator
- M3 기관매핑 중복 → `source_entity_links` 재사용
- M4 revision provenance → overwrite 전 `review_items`
- M5 partial row-drop → contract all-or-nothing target
- M6 backfill pagination → count/page gate
- M7 no-data RESULT → D0 실증
- M8 sector 어휘 → source 어휘와 기존 `Sector` 분리
- M9 말잔/평잔 → explicit semantics/basis

Should-fix의 시점 의미, publication lag 한계, hash precision, 일간 macro 재수집, warning persistence, Layer B 필드, cross-source 정의 차이, CLI 진입점, 개별 MG 원천 존재 여부도 세부 작업명세 v1.1에 반영한다.
