# 수신시장 데이터 수집·정리 작업명세서 v1.1

- Date: 2026-08-27
- Status: **Reviewed — Claude APPROVE WITH CHANGES 반영**
- Parent plan: `docs/plans/20260827-market-funding-data-plan-v1.1.md`
- Supersedes: `docs/specs/20260827-market-funding-data-acquisition-v1.md`
- Base: `main@b3ec3ba7e0c03f545c94ea99497598de0c04be2c`
- Risk: **High — financial data / external source / persistent contract / identity**

## 0. 구현 원칙

이 작업은 상품 금리 비교 로직을 변경하지 않는다.

금지:

- source precedence 변경
- stable product identity/dedupe 변경
- Strategy 예측계수/판정식 변경
- 수신시장 지표를 `rate_observations`에 저장
- 기관명을 fuzzy name으로 자동 병합
- 미검증 ECOS/FISIS code를 persistence contract로 고정
- SQLite 신규 금액컬럼에 `Numeric` 사용
- missing period를 0으로 저장
- revision audit 없이 기존 관측값 overwrite

외부통계 신규 도입 순서:

`storage gate → discovery → exact contract → read-only sample → range/precision gate → parser test → persistence → backfill → scheduled collection`

---

# 1. Current State 계약

## 1.1 기존 ECOS macro

파일:

- `src/rate_monitor/collectors/bok_ecos/macro_adapter.py`
- `src/rate_monitor/collectors/bok_ecos/macro_parser.py`
- `src/rate_monitor/collectors/bok_ecos/macro_cli.py`
- `src/rate_monitor/services/indicator_service.py`

source:

```text
source_id = bok_ecos_macro
role = PRIMARY_OFFICIAL
trust = OFFICIAL_DIRECT
cycle = M
rolling window = 48 months
```

검증된 exact contract:

| key | stat | item | 의미 | 현재 normalized unit |
|---|---|---|---|---|
| bank_savings_deposit_rate | 121Y002 | BEABAA2 | 예금은행 저축성수신 신규취급금리 | percent |
| bank_pure_savings_deposit_rate | 121Y002 | BEABAA21 | 순수저축성예금 신규취급금리 | percent |
| bank_term_deposit_1y_rate | 121Y002 | BEABAA2118 | 정기예금 1년 신규취급금리 | percent |
| savings_bank_deposit_balance | 111Y007 | 1120600 | 저축은행 수신 말잔 | trillion_krw |
| credit_union_deposit_balance | 111Y007 | 1120700 | 신협 수신 말잔 | trillion_krw |
| broad_mutual_finance_deposit_balance | 111Y007 | 1120800 | 광의 상호금융 수신 말잔 | trillion_krw |
| kfcc_deposit_balance | 111Y007 | 1121000 | MG 수신 말잔 | trillion_krw |

`111Y007/1120800`은 `nh_local` 직접 업권이 아니다.

## 1.2 current persistence

`market_indicators` unique contract:

```text
(indicator_code, source_effective_at, source_id)
```

현재 `value`는 `Rate` TypeDecorator이며:

```text
MAX_RATE = 999.9999
precision = 4 decimals
SQLite storage = zero-padded fixed decimal string
```

따라서 1,000조원 이상 잔액은 현재 저장 불가다.

## 1.3 current revision behavior

현재 `_upsert()`는 같은 자연키에 content hash가 바뀌면 다음을 overwrite한다.

- value
- content_hash
- observed_at
- raw_artifact_id

기존 revision row는 별도 보존하지 않는다.

## 1.4 current warning behavior

현재 parser는 일부 drift를 warning + `continue`로 처리한다.

- stat/item mismatch
- item name drift
- unit drift
- bad time/value/range

warning 원문은 persistence되지 않고 `warning_count`만 남는다.

## 1.5 current scheduling/backfill limit

- macro collector는 현재 평일 일반 collection workflow에 포함
- 최근 48개월 × 각 contract를 반복 fetch
- `PAGE_SIZE=100`
- `list_total_count`를 검증하지 않음

48개월 rolling에는 문제가 없지만 100개월 초과 historical backfill을 같은 방식으로 구현하면 silent truncation 위험이 있다.

---

# 2. Target State

## Layer A — market/sector scalar series

기존 `market_indicators` 재사용.

대상:

- 업권 수신잔액
- 업권 대표 수신금리
- 은행 종별 수신잔액(존재·exact code 확인 시)

v1 Layer A는 **monthly only**로 제한한다.

## Layer B — institution funding

신규 `institution_funding_observations` 후보.

대상:

- 저축은행별 예수금/수신관련 공시지표
- 신협 조합별 검증 지표
- 농협 등은 동일 contract가 성립할 때만

기관 mapping은 기존 `source_entity_links`가 유일한 canonical mapping source다.

---

# 3. Stage 0 — 저장능력·안전계약 선행

신규 외부 series를 추가하기 전에 완료한다.

## 3.1 `Quantity` TypeDecorator

`src/rate_monitor/db/types.py`에 `Rate`와 별도의 SQLite-safe fixed-decimal 타입을 추가한다.

요구사항:

- `Rate`는 수정하지 않는다.
- float/SQLAlchemy Numeric round-trip을 사용하지 않는다.
- 저장 문자열의 수치 정렬 가능성을 보장한다.
- 최소 1,000조 이상 잔액을 충분히 저장한다.
- v1 funding 지표는 음수 값 자체를 저장하지 않는다. 증감은 파생값이므로 원천 잔액에 음수가 필요 없다.
- precision은 D0 실측 최대 소수자릿수보다 작지 않아야 한다.

권장 초기 설계 예:

```text
INT_DIGITS >= 9
DEC_DIGITS >= 6
```

정확한 폭은 D0 range/precision evidence 후 migration 전에 확정한다.

`market_indicators.value`를 `Quantity`로 변경해 금리값과 큰 잔액을 모두 lossless하게 저장한다. `rate_observations` 등 기존 상품금리 컬럼의 `Rate`는 그대로 둔다.

### Migration acceptance

- 기존 `market_indicators` 전 행 round-trip 값 동일
- indicator count 동일
- source/date/code 동일
- 기존 7개 macro series latest 값 동일
- empty DB upgrade 성공
- production snapshot read-only copy에서 migration 성공

## 3.2 normalized-value hash

`content_hash`는 **DB에 실제 저장될 normalized Decimal** 기준으로 계산한다.

금지:

```text
raw Decimal hash → bind 시 quantize
```

이렇게 하면 저장값이 같은데 hash만 바뀔 수 있다.

권장:

1. TypeDecorator와 동일한 normalize helper 사용
2. normalize된 값으로 hash 계산
3. source value가 저장 precision을 초과해 정보가 손실되면 contract error

해시 입력:

```text
indicator_code
source_effective_at
normalized_value
unit
```

unit 변경은 revision이 아니라 schema drift로 실패시킨다.

## 3.3 revision audit

canonical `market_indicators` row는 latest source revision을 유지해도 되지만, 값 변경 전 audit를 남긴다.

`review_items` 권장 payload:

```json
{
  "indicator_code": "...",
  "source_effective_at": "YYYY-MM-DD",
  "old_value": "...",
  "new_value": "...",
  "old_content_hash": "...",
  "new_content_hash": "...",
  "old_raw_artifact_id": "...",
  "new_raw_artifact_id": "...",
  "old_observed_at": "...",
  "new_observed_at": "...",
  "source_locator": "..."
}
```

issue type 예:

```text
market_indicator_revision
```

revision audit insert와 canonical update는 동일 DB transaction에서 수행한다.

## 3.4 parser warning persistence

구조적 drift는 warning으로 저장하지 않고 contract error로 승격한다.

비구조 warning이 남는 경우 원문을 `review_items`에 기록한다. 단순 `warning_count`만으로 D3를 구현하지 않는다.

## 3.5 fail-closed contract unit

다음 중 하나라도 발생하면 **해당 artifact/contract point 전체를 저장하지 않는다.**

- STAT_CODE mismatch
- ITEM_CODE mismatch
- contract-breaking ITEM_NAME drift
- UNIT drift
- TIME parse failure
- DATA_VALUE parse/range failure
- pagination/count inconsistency

같은 실행의 다른 독립 contract는 계속 처리할 수 있다. 즉 source 전체 all-or-nothing이 아니라 **contract artifact 단위 all-or-nothing**이다.

## 3.6 `CONTRACT_BY_ITEM`

평잔과 말잔이 같은 item code를 사용할 수 있으므로 item-only key는 금지한다.

- 사용하지 않는다면 제거
- 필요하면 `(stat_code, item_code)` 복합키

---

# 4. D0 — Read-only recon

D0는 production DB write가 없어야 한다.

모든 결과는 `docs/source-recon/`와 workflow artifact로 남긴다.

## 4.1 ECOS discovery

### E1. 비은행 대표 수신금리

확인 대상 업권:

- 저축은행
- 신협
- 상호금융
- 새마을금고

반드시 확인:

- 통계표 존재 여부
- stat/item code
- exact item name
- unit
- 신규취급/잔액/약정금리 등 경제적 의미
- 월 주기 여부
- 최초/최근 시점
- 최근 36개월 missing
- min/max/decimal precision

**존재하지 않으면 없다고 결론**낸다. FinLife/자체 collector 공시금리를 ECOS 신규취급금리라고 대체하지 않는다.

### E2. 은행 종별 수신잔액

탐색:

- 총수신 또는 예금은행 예금 잔액
- 정기예금
- 정기적금

확인:

- 말잔/평잔
- 단위
- 은행권 aggregate인지
- 월 시계열인지
- 1,000조 초과 실제 max

### E3. 111Y008 평잔

`111Y007`과 item code가 같은지 확인한다. 같은 경우 contract key는 stat+item 조합으로 고정한다.

### E4. ECOS RESULT semantics

실조회로 최소 다음을 캡처한다.

- 정상 data response
- 명백한 invalid request response
- 존재하는 series지만 요청기간에 데이터가 없는 response

각 RESULT code/message를 evidence로 남겨 error/no-data 분기표를 만든다.

### E5. publication metadata

ECOS StatisticSearch가 actual publication date를 주는지 확인한다.

없으면:

```text
published_at = NULL
observed_at - source_effective_at != publication lag
```

을 contract로 고정한다.

## 4.2 existing DB revision audit

기존 production DB read-only copy에서 현재 `market_indicators`를 감사한다.

목표:

- 같은 indicator/date의 observed_at 패턴
- collection run/raw artifact history와 현재 row 비교
- 실제 revision evidence를 복원할 수 있는지

이미 overwrite돼 과거 value가 사라진 경우 "revision이 없었다"고 결론내리지 않는다. 현재 구조의 한계로 기록한다.

## 4.3 FISIS / 금융공공데이터 recon

우선순위:

1. savings_bank
2. credit_union
3. agricultural_coop

각 source에서 확인:

- 공식 endpoint
- auth/API key
- external institution code/name
- metric code/name
- 예수금 또는 수신관련 지표 정의
- source unit
- period/frequency
- 최초/최근 기간
- revision 방식
- rate limit/page contract
- 빈 응답 semantics

### institution mapping census

external code를 기존 `source_entity_links`로 exact mapping 가능한 비율을 산출한다.

```text
mapped_exact / total_external_entities
```

이름 fuzzy auto-link는 금지한다.

## 4.4 개별 MG data existence

KFCC 또는 공식 공공데이터에서 개별 금고 예수금/수신잔액 시계열 **존재 여부부터** 판정한다.

- source 없음 → D2 범위 제외
- source 있음/품질 미확인 → 후속 recon

---

# 5. Layer A schema contract

## 5.1 `market_indicators.value`

Stage 0 이후 `Quantity` 계열 fixed-decimal.

## 5.2 semantics metadata

v1에서는 consumer가 `indicator_name` 한국어를 파싱하지 않도록 다음 의미를 코드 contract에 둔다.

- frequency: `M`
- value_semantics: `rate` 또는 `stock`
- balance_basis: `eom` / `average` / `n/a`

구현 선택지:

A. `market_indicators` 컬럼 추가
B. immutable indicator contract registry + test

권고는 **A**다. 이유는 데이터 자체가 DB만으로도 해석 가능해야 하기 때문이다.

권장 nullable:

- `frequency`: 기존 row migration 후 NOT NULL 가능
- `value_semantics`: 기존 row backfill 후 NOT NULL 가능
- `balance_basis`: rate는 `n/a`, balance는 `eom`
- `published_at`: nullable

## 5.3 effective date

ECOS monthly macro에서는 `source_effective_at`가 반드시 존재한다.

parser가 YYYYMM을 month-end로 변환하지 못하면 contract 실패다. NULL point를 저장하지 않는다.

## 5.4 indicator naming

기존 indicator codes는 consumer 호환 때문에 무조건 rename하지 않는다.

말잔/평잔이 동시에 추가될 경우 새 indicator code는 basis가 드러나야 한다.

예:

```text
bok_savings_bank_deposit_balance_eom
bok_savings_bank_deposit_balance_avg
```

기존 code migration 여부는 consumer search 후 별도 결정한다.

---

# 6. Layer B schema contract

신규 테이블 후보:

```text
institution_funding_observations
```

## 6.1 columns

| field | required | contract |
|---|---:|---|
| id | Y | UUID string |
| run_id | Y | FK collection_runs |
| source_id | Y | FK sources |
| source_sector | Y | 원천의 업권 어휘 |
| source_entity_code | Y | 공식 외부기관코드 |
| source_entity_name | Y | 원천 표기 그대로 |
| metric_code | Y | 원천 metric/account code |
| metric_name | Y | 원천 metric name |
| value | Y | SQLite-safe fixed-decimal |
| source_value_text | Y | 원천 문자열 원본 |
| unit | Y | normalized unit |
| source_unit | Y | 원천 단위 |
| value_semantics | Y | stock/flow/rate |
| balance_basis | conditional | 잔액이면 eom/average 필수 |
| period_end | Y | 경제적 관측기간 끝 |
| frequency | Y | M/Q/A |
| observed_at | Y | 수집 시각 |
| published_at | N | source 제공 시만 |
| first_seen_at | Y | 최초 수집 |
| last_seen_at | Y | 최신 동일값 확인 |
| raw_artifact_id | Y | FK raw_artifacts |
| source_locator | N | source path/key |
| content_hash | Y | normalized identity/value hash |
| validation_status | Y | valid/review 등 |

`period_start`는 v1 기본컬럼에서 제외한다. 원천이 비정형 기간을 실제로 제공하는 경우에만 재검토한다.

## 6.2 unique key

기본:

```text
(source_id, source_entity_code, metric_code, period_end, frequency)
```

frequency를 포함한다. 월/분기 지표가 같은 period_end에서 충돌하는 것을 방지한다.

## 6.3 canonical institution mapping

관측 테이블에 `institution_id`를 canonical mapping으로 저장하지 않는다.

조회:

```text
observation.source_id
+ observation.source_entity_code
→ source_entity_links
  where entity_type='institution'
→ institutions.id
```

매핑 실패 observation도 valid할 수 있다.

QA:

```text
unmapped_count
unmapped_ratio
```

## 6.4 source_sector vocabulary

기존 `Sector` enum과 외부기관 분류를 억지로 같게 만들지 않는다.

예:

```text
source_sector=savings_bank → canonical Sector.SAVINGS_BANK
source_sector=credit_union → canonical Sector.CU
source_sector=agricultural_coop → mapping target may be Sector.NH_LOCAL only when source scope matches
source_sector=broad_mutual_finance → no direct canonical Sector mapping
```

실제 enum 값/매핑은 코드의 current enum을 읽고 테스트로 고정한다.

## 6.5 rejected rows

rejected 원천 row를 정상 observation 테이블에 적재하지 않는다.

- raw artifact 보존
- `review_items`에 reject reason/payload 기록
- observation에는 valid/review-accepted row만

---

# 7. Layer B value/hash/revision

## 7.1 value storage

`Numeric(24,6)` 금지.

`Quantity` 또는 별도 `FinancialQuantity` fixed-decimal TypeDecorator를 사용한다.

migration 전에 D0 sample의:

- max
- min
- decimal precision
- sign

을 확인한다.

## 7.2 content hash

해시 입력을 고정한다.

권장:

```text
source_id
source_entity_code
metric_code
period_end
frequency
normalized_value
unit
value_semantics
balance_basis
```

source_entity_name 변경만으로 금융값 revision으로 취급하지 않는다. 이름변경은 mapping/metadata issue로 별도 처리한다.

## 7.3 revision

같은 unique key에 normalized value가 바뀌면:

1. revision audit (`review_items` 또는 전용 history가 향후 필요하면 확장)
2. canonical row update
3. first_seen_at 유지
4. last_seen_at=now
5. new raw_artifact/content_hash 저장

동일값 재수집이면:

- value/artifact provenance 정책을 명확히 한다.
- canonical raw_artifact를 매번 새 artifact로 옮기지 않는 것을 기본으로 한다.
- last_seen_at만 갱신할 수 있다.

---

# 8. ECOS parser hardening

## 8.1 required fields

현재 필수필드 외 pagination total metadata를 검증한다.

response shape drift → `SchemaChangedError`.

## 8.2 unit/name mismatch

구조적 contract mismatch는 warning이 아니라 error.

## 8.3 all-or-nothing

artifact 하나는 exact contract 하나에 대응한다. 그 artifact에서 한 row라도 structural parse failure가 발생하면 points를 부분 반환하지 않는다.

권장 parser result:

```text
success → full point list
contract error → exception
source no-data → verified no-data result
```

## 8.4 no-data

D0에서 검증된 RESULT code만 no-data로 인정한다.

미지 RESULT code는 error.

---

# 9. Backfill contract

## 9.1 CLI

기존 진입점은:

```bash
python -m rate_monitor.collectors.bok_ecos.macro_cli
```

기존 CLI architecture를 바꾸지 않는 것을 기본으로 한다.

backfill command는 같은 module 또는 별도 module에 추가하되 `rate-monitor` 신규 서브커맨드라고 가정하지 않는다.

## 9.2 range

명시적 from/to를 받는다.

예시 개념:

```text
--from 201001 --to 202608
```

## 9.3 pagination

각 contract에서:

1. query total 확인
2. 100-row 이하 page 반복 또는 96개월 이하 chunk
3. 모든 page/chunk concat
4. count == expected total
5. duplicate TIME 없음
6. 응답 TIME이 요청범위 밖에 없음

## 9.4 continuity audit

backfill 직후:

- missing months
- duplicate months
- first/last period
- revision events
- total rows

을 artifact/report로 남긴다.

missing month를 자동 0-fill하지 않는다.

---

# 10. Scheduling

현재 월간 macro data를 평일마다 48개월 재조회한다.

D1 이후 다음 중 하나를 선택한다.

### Option A — macro dedicated schedule

월 1~2회 + 수동 dispatch.

### Option B — short rolling check

평일에는 최근 2~3개월만 revision check, 월 1회 longer reconciliation.

판정 기준:

- ECOS revision 빈도
- publication day pattern
- API 호출량
- 운영 복잡도

현재 48개월 daily pattern을 신규 series에 그대로 확대하지 않는다.

---

# 11. Cross-source comparison rule

ECOS `수신`과 FISIS `예수금`은 정의가 동일하다고 가정하지 않는다.

비교 전 반드시:

- 통계 정의
- 포함 계정
- 연결/별도 여부
- 말잔/평잔
- 기관 모집단

을 문서화한다.

정의 차이를 모른 상태에서 임의 허용오차(예: ±5%)를 만들지 않는다.

cross-source는 **정의가 호환된다고 증명된 경우만** reconciliation control로 쓴다.

---

# 12. D2 implementation sequence

## D2a 저축은행

필수:

- source adapter/parser
- raw artifact
- exact metric contract
- Layer B migration/model
- source_entity_links exact-code mapping
- unmapped report
- revision test

## D2b 신협

D2a schema를 재사용할 수 있다는 실증이 있을 때만.

## D2c 농협/기타

외부기관 scope가 현재 `nh_local`과 정확히 일치하는지 먼저 확인한다.

광의 상호금융 aggregate와 individual nh_local을 섞지 않는다.

---

# 13. Audit report D3

최소 지표:

- source/metric별 first/last period
- expected vs actual period count
- missing periods
- duplicate periods
- revision count
- schema/unit/range rejects
- unmapped institution count/ratio
- last successful run
- warning/review item count

publication date가 없으면 실제 publication lag를 계산하지 않는다.

---

# 14. Test plan

## Stage 0

- Quantity zero-pad numeric ordering
- Decimal round-trip
- >999.9999 storage
- no float conversion
- old market_indicators migration equality
- Rate unaffected
- hash uses normalized stored value
- revision creates review item before overwrite

## ECOS parser

- exact stat/item/name/unit passes
- any contract drift fails whole artifact
- over-range fails whole artifact
- malformed TIME fails whole artifact
- verified no-data code returns no-data
- unknown RESULT fails
- pagination total mismatch fails

## backfill

- >100 rows retrieves all pages/chunks
- duplicate page fails
- missing page/count fails
- pre-series no-data chunk does not falsely mark source outage once code verified

## Layer B

- exact natural key uniqueness
- same period M/Q can coexist
- source_value_text retained
- Numeric not used
- exact-code mapping only
- unmapped observation persists
- rejected row not in observation table
- revision audit preserved

---

# 15. Runtime/Evidence Gate

## D0

- official endpoint read-only samples
- credentials redacted
- production DB writes 0
- artifact digest
- exact codes/units/times documented

## schema migration

- empty DB migrate
- full test/lint
- production snapshot copy migrate
- row/value parity

## new source persistence

- small bounded sample first
- stored rows counted
- raw → parsed → persisted provenance spot-check
- rerun idempotency
- revision simulation

## backfill

- bounded historical sample
- page/count audit
- only then full history

---

# 16. CI/quality checks

최소:

```bash
uv run ruff check src tests
uv run pytest
```

DB migration이 포함되면 current migration smoke를 반드시 수행한다.

문서-only PR은 코드 CI가 불필요할 수 있으나 구현 PR은 Stage별로 분리하고 각 Stage의 Evidence Gate를 첨부한다.

---

# 17. PR boundary

권장 분리:

1. **PR A — Stage 0 storage/provenance hardening**
2. **PR B — D0 recon evidence**
3. **PR C — D1a nonbank rates**
4. **PR D — D1b bank balances + D1c backfill**
5. **PR E — D2a savings-bank institution funding**
6. 후속 CU/NH 확장

D0에서 series가 없다고 판정되면 그 Stage는 구현하지 않는다.

---

# 18. 완료 판정

다음이 모두 충족돼야 `수신시장 데이터 수집 기반 v1` 완료다.

- [ ] 기존 7개 ECOS macro series 회귀 없음
- [ ] 1,000조원 초과 값 lossless 저장
- [ ] 기존 상품금리 Rate 영향 없음
- [ ] revision old/new provenance 보존
- [ ] parser drift가 partial row-drop으로 끝나지 않음
- [ ] warning/error 원문 audit 가능
- [ ] ECOS backfill pagination 완전성 증명
- [ ] no-data/error code 실증 분리
- [ ] exact contract 없는 series 저장 없음
- [ ] Layer B가 SQLite-safe fixed decimal 사용
- [ ] 기관 mapping SoT가 source_entity_links 하나임
- [ ] fuzzy auto-link 없음
- [ ] unmapped institution 비율 산출
- [ ] missing != zero
- [ ] 말잔/평잔 및 stock/flow 의미 보존
- [ ] UI/인과모델 변경 없음

---

# 19. Claude review disposition

리뷰의 Must-fix M1~M9를 모두 수용했다.

- M1 `Rate` capacity → Stage 0 Quantity
- M2 Numeric 금지 → SQLite-safe fixed decimal
- M3 mapping 중복 → source_entity_links SoT
- M4 revision overwrite → audit before update
- M5 warning row-drop → contract artifact all-or-nothing
- M6 100-row truncation → pagination/count gate
- M7 no-data RESULT → D0 evidence
- M8 sector vocabulary → source_sector 분리/mapping 명시
- M9 balance basis → explicit basis/semantics

Should-fix S1~S10도 각각 시간 의미, publication metadata, effective date, normalized hash, scheduling, warning persistence, Layer B fields, cross-source 정의, CLI, MG source existence 항목에 반영했다.
