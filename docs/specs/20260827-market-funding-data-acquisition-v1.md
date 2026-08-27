# 수신시장 데이터 수집·정리 작업명세서 v1

- Date: 2026-08-27
- Status: Draft for review
- Parent plan: `docs/plans/20260827-market-funding-data-plan-v1.md`
- Base: `main@b3ec3ba7e0c03f545c94ea99497598de0c04be2c`
- Risk: **High — financial data / external source / persistent contract / identity**

## 0. 구현 원칙

이 작업은 금융상품 금리 비교 로직을 변경하는 작업이 아니다.

금지:

- source precedence 변경
- stable product identity 변경
- 상품 dedupe 변경
- Strategy 예측계수/판정식 변경
- 기존 `rate_observations`에 수신시장 거시지표 저장
- 기관명을 문자열 유사도로 자동 병합
- 미검증 ECOS/FISIS code를 추정하여 persistence contract로 고정

모든 신규 외부통계는 **discovery → exact contract → read-only sample → parser test → persistence** 순서로 진행한다.

---

# 1. Current State 계약

## 1.1 기존 ECOS macro 경로

현재 파일:

- `src/rate_monitor/collectors/bok_ecos/macro_adapter.py`
- `src/rate_monitor/collectors/bok_ecos/macro_parser.py`
- `src/rate_monitor/collectors/bok_ecos/macro_cli.py`

운영 source:

```text
source_id = bok_ecos_macro
role = PRIMARY_OFFICIAL
trust = OFFICIAL_DIRECT
```

현재 fetch window:

```text
cycle = M
window = recent 48 months
```

현재 exact contracts:

| key | stat code | item code | meaning | normalized unit |
|---|---|---|---|---|
| bank_savings_deposit_rate | 121Y002 | BEABAA2 | 예금은행 저축성수신 신규취급금리 | percent |
| bank_pure_savings_deposit_rate | 121Y002 | BEABAA21 | 순수저축성예금 신규취급금리 | percent |
| bank_term_deposit_1y_rate | 121Y002 | BEABAA2118 | 정기예금 1년 신규취급금리 | percent |
| savings_bank_deposit_balance | 111Y007 | 1120600 | 저축은행 수신 말잔 | trillion_krw |
| credit_union_deposit_balance | 111Y007 | 1120700 | 신협 수신 말잔 | trillion_krw |
| broad_mutual_finance_deposit_balance | 111Y007 | 1120800 | 광의 상호금융 수신 말잔 | trillion_krw |
| kfcc_deposit_balance | 111Y007 | 1121000 | 새마을금고 수신 말잔 | trillion_krw |

관련 evidence:

- `docs/source-recon/strategy-external-indicators-e0-discovery.md`
- prior trusted recon runs recorded in the parser module docstring

## 1.2 저장계약

업권 scalar time series는 기존 `market_indicators` 사용.

중요 unique contract:

```text
(indicator_code, source_effective_at, source_id)
```

수신시장 데이터를 `rate_observations`에 넣지 않는다.

---

# 2. Target State

## 2.1 데이터 계층

### Layer A — Market / sector level

ECOS 기반 월별 시계열.

저장 위치:

```text
market_indicators
```

대상:

- 업권별 수신잔액
- 업권별 대표 수신금리
- 은행 종별 수신잔액

### Layer B — Institution level

FISIS/금융위원회 금융통계 Open API 기반 금융회사·조합별 재무/예수금 시계열.

저장 위치:

```text
institution_funding_observations  # 신규, D2에서 exact source contract 확인 후 생성
```

### Layer C — Structural reference

중앙회 연간/분기 통계.

v1에서는 자동 ingestion을 필수로 하지 않는다. source recon과 장기구조 분석 후보로 보존한다.

---

# 3. Stage D0 — Source Recon / Evidence Gate

**D0 완료 전 migration 또는 production write를 금지한다.**

## 3.1 ECOS discovery

기존 `.github/workflows/e0-strategy-ecos-recon.yml` 또는 동등한 read-only diagnostic path를 재사용/확장한다.

### D0-E1: 비은행 업권 수신금리

목표 series:

- 상호저축은행 1년 정기예금 신규취급금리
- 신용협동조합 1년 정기예탁금 신규취급금리
- 상호금융 1년 정기예탁금 신규취급금리
- 새마을금고 1년 정기예탁금 신규취급금리

검증 항목:

```text
STAT_CODE
STAT_NAME
ITEM_CODE1
ITEM_NAME1
CYCLE
UNIT_NAME
first period
latest period
recent 24-36 month values
```

**문서나 검색결과에 나온 이름만 보고 code를 추정하지 않는다.**

### D0-E2: 예금은행 종별 수신잔액

우선 탐색 대상:

- 총수신 또는 예금 총액
- 정기예금
- 정기적금
- 저축성예금

필요성:

기사에서 보이는 `시중은행 정기적금 잔액`과 같은 시장흐름을 공식통계로 어느 수준까지 재현할 수 있는지 확인한다.

판정:

- exact monthly official series 존재 → v1 후보
- 분기/비정기 또는 정의 불명확 → source recon만 남기고 제외

### D0-E3: 말잔/평잔 확인

수신자금 이동의 기본 stock은 말잔을 사용한다.

```text
primary = 말잔
average balance = 별도 metric이며 대체 사용 금지
```

## 3.2 금융공공데이터/FISIS discovery

공공데이터포털에서 존재가 확인된 API군:

- 금융통계저축은행정보
- 금융통계신용협동조합정보
- 금융통계농업협동조합정보
- 금융통계수산업협동조합정보
- 금융통계산림조합정보
- 금융통계국내은행정보

### D0-F1: 실제 endpoint 확인

각 API에 대해 아래를 저장한다.

```json
{
  "dataset_name": "...",
  "service_url": "...",
  "operation": "...",
  "sample_basYm": "YYYYMM",
  "request_params": [],
  "response_fields": [],
  "observed_frequency": "M|Q|A|unknown",
  "source_unit": "...",
  "latest_period": "..."
}
```

### D0-F2: funding metric 탐색

재무현황 응답에서 아래와 같은 **수신 관련 명시적 항목**만 후보로 삼는다.

허용 예:

- 예수금
- 예금
- 정기예금
- 적금
- 수신합계

금지:

- 총부채를 예수금으로 간주
- 계정과목명을 substring 하나로 오판
- 단위가 없는 숫자를 임의로 원/천원/백만원으로 추정

### D0-F3: institution key 확인

최소한 다음을 확보한다.

- `fncoCd` 등 금융회사/조합 공식 코드
- `fncoNm`
- `basYm`
- 가능한 경우 법인등록번호 또는 보조 식별자

기관명만으로 existing `institutions`에 merge하지 않는다.

## 3.3 D0 산출물

새 파일:

```text
docs/source-recon/market-funding-data-v1.md
docs/source-recon/market-funding-data-v1.json
```

문서에는 각 series/metric을 아래 상태 중 하나로 표시한다.

```text
VERIFIED
REJECTED
DEFERRED
UNKNOWN
```

### D0 완료 조건

- ECOS 신규 후보 exact code 확인
- 최소 저축은행 API 실제 response shape 확인
- 최소 신협 API 실제 response shape 확인
- funding metric의 code/name/unit 확인 여부 기록
- institution key 확인
- production DB write 0
- secret leak 0

---

# 4. Stage D1 — ECOS Market Funding 확장

D0에서 `VERIFIED`된 항목만 구현한다.

## 4.1 parser contract

수정 대상:

```text
src/rate_monitor/collectors/bok_ecos/macro_parser.py
```

`SeriesContract`를 계속 사용한다.

신규 contract 예시 — code는 D0 evidence로 대체:

```python
SeriesContract(
    key="savings_bank_term_deposit_1y_rate",
    stat_code="<VERIFIED>",
    item_code="<VERIFIED>",
    item_name="<VERIFIED>",
    source_unit="<VERIFIED>",
    indicator_code="bok_savings_bank_term_deposit_1y_rate",
    indicator_name="상호저축은행 1년 정기예금금리(신규취급액)",
    unit="percent",
    value_kind="rate",
)
```

## 4.2 naming rules

업권 이름은 의미를 숨기지 않는다.

```text
savings_bank
credit_union
broad_mutual_finance
kfcc
bank
```

`mutual_finance`를 `nh_local` 의미로 재사용하지 않는다.

## 4.3 역사 backfill

현재 scheduled adapter의 48개월 rolling fetch와 역사 backfill을 분리한다.

### scheduled

```text
recent rolling window
```

장점:

- 최근 ECOS revision 재수집 가능
- API 호출량 제한

### historical backfill

별도 explicit command/workflow.

필수 옵션:

```text
--from YYYYMM
--to YYYYMM
--indicator <optional repeated>
--dry-run
```

기본 원칙:

- 사용자/운영자가 명시적으로 실행
- production DB 적용 전 read-only artifact 검증 가능
- chunked requests
- idempotent persistence

## 4.4 revisions

ECOS가 과거 값을 수정할 가능성을 고려한다.

현재 unique key는 같은 period에 한 point만 허용한다. 따라서 persistence service가 기존 point와 다른 value를 받았을 때의 정책을 구현 전에 확인한다.

가능한 정책:

1. 기존 행 update + raw artifact provenance 갱신
2. revision history 별도 저장

**v1 기본 권고:** 기존 `market_indicators` persistence behavior를 조사하고, 새 source만 독자적인 revision 정책을 만들지 않는다.

---

# 5. Stage D2 — Institution Funding Storage

D0에서 기관별 funding metric이 `VERIFIED`된 경우에만 진행한다.

## 5.1 migration

신규 테이블 후보:

```text
institution_funding_observations
```

권장 columns:

| column | type concept | required | meaning |
|---|---|---:|---|
| id | UUID/string | Y | row id |
| source_id | FK sources | Y | operational source |
| sector | string/enum-safe | Y | savings_bank / credit_union / agricultural_coop ... |
| source_entity_code | string | Y | 원천 기관코드 |
| source_entity_name | text | Y | 원천 기관명 |
| institution_id | FK institutions nullable | N | 검증된 mapping만 연결 |
| period_end | date | Y | 경제적 관측기간 말일 |
| frequency | string | Y | M/Q/A |
| metric_code | string | Y | 원천 계정/지표 코드 |
| metric_name | text | Y | 원천 계정/지표명 |
| value | high precision decimal | Y | normalized numeric value |
| unit | string | Y | normalized unit |
| source_unit | string | Y | 원천 단위 |
| observed_at | datetime | Y | 수집시각 |
| published_at | datetime/date nullable | N | 원천 제공 시에만 |
| raw_artifact_id | FK raw_artifacts | Y | provenance |
| source_locator | text | N | operation/period/code |
| content_hash | string | Y | duplicate/revision guard |
| validation_status | string | Y | valid/warning/rejected |

### Unique key

```text
(source_id, source_entity_code, metric_code, period_end)
```

필요 시 frequency를 unique key에 포함할지 D0 sample로 결정한다.

## 5.2 numeric type

`Rate` 타입을 사용하지 않는다.

이유:

- 잔액은 금리보다 훨씬 큰 값
- 현재 ECOS macro는 trillion_krw로 압축해서 `market_indicators`에 들어가지만, 기관 raw financial amount는 단위가 다양할 수 있음

권장:

```text
Numeric(24, 6) 또는 실제 source range를 보고 결정
```

migration 전 max/min sample을 수집한다.

## 5.3 institution mapping

v1에서 mapping은 enrichment이지 persistence 필수조건이 아니다.

### 저장 가능

```text
source_entity_code + source_entity_name
```

### `institution_id` 연결 허용

- 기존 institution에 동일 공식 source code가 이미 매핑돼 있음
- 또는 별도 deterministic mapping table/evidence가 존재

### 금지

```text
normalize(name) == normalize(existing name)
```

하나만으로 자동 merge.

매핑 실패는 데이터 유실이 아니라 `institution_id = NULL`로 저장하고 QA report에서 집계한다.

---

# 6. Stage D2 Collector Architecture

권장 구조:

```text
src/rate_monitor/collectors/fsc_financial_stats/
  __init__.py
  adapter.py
  parser.py
  contracts.py
  cli.py
```

단일 adapter에서 업권 contract를 설정형으로 관리하되, source schema가 실질적으로 다르면 억지 추상화하지 않는다.

## 6.1 Operational source 분리

ECOS와 금융위원회/FISIS는 별도 source다.

예:

```text
fsc_financial_stats_savings_bank
fsc_financial_stats_credit_union
fsc_financial_stats_agricultural_coop
```

이유:

- 한 API의 schema drift가 모든 업권 수집을 실패시키지 않음
- collection health를 업권별로 분리 가능
- provenance 명확

## 6.2 Raw artifact

API response 원문을 기존 raw artifact 체계로 보존한다.

request_meta 최소 항목:

```text
service_url (secret redacted)
operation
basYm
pageNo
numOfRows
sector
metric scope
```

서비스키는 artifact/로그/exception에 남기지 않는다.

## 6.3 Pagination

`totalCount` 기반 pagination을 구현한다.

검증:

- page overlap 없음
- final page 누락 없음
- duplicate entity/metric row count

---

# 7. Normalization Contract

## 7.1 period

원천이 `basYm = YYYYMM`을 주는 경우:

```text
period_end = calendar month end
```

단, 실제 값이 분기말만 존재하는 경우 frequency를 `Q`로 기록한다.

`basYm` 형식만 보고 월간 데이터라고 단정하지 않는다.

## 7.2 amount units

원천 단위가 확인된 경우에만 normalized unit으로 변환한다.

권장 normalized units:

```text
krw
million_krw
billion_krw
trillion_krw
percent
count
```

하나의 metric code는 history 전체에서 동일 normalized unit을 사용한다.

unit drift 발견 시 warning이 아니라 contract error로 승격하는 것을 기본으로 한다.

## 7.3 missing / zero

```text
missing != 0
```

빈 문자열, `-`, `N/A`를 0으로 저장하지 않는다.

원천이 명시적인 0을 제공했을 때만 0 저장.

---

# 8. Data Quality / Validation

## 8.1 series-level checks

각 metric마다:

- first period
- latest period
- row count
- missing expected periods
- duplicate periods
- min/max
- unit set
- source schema fingerprint

## 8.2 continuity

### monthly series

최근 24개월 기준 missing month 탐지.

### quarterly series

최근 8분기 기준 missing quarter 탐지.

### annual series

연간 구조통계는 별도 QA class.

## 8.3 sanity checks

금융데이터에서 값 변화율이 매우 크더라도 임의 삭제하지 않는다.

예:

```text
abs(MoM) > threshold
```

는 `warning/review`로 만들 수 있지만 원천값 자체를 버리는 자동 필터로 사용하지 않는다.

## 8.4 cross-source checks

가능한 경우만 수행:

- ECOS 저축은행 업권 총수신 vs institution API 합계
- ECOS 신협 총수신 vs institution API 합계

목적은 **완전 일치 강제**가 아니다.

차이가 날 수 있는 이유:

- 말잔/평잔 차이
- 보고대상 범위
- 연결/별도 기준
- publication timing
- 기관 포함범위

따라서 먼저 definition을 맞추고 차이를 기록한다.

---

# 9. Collection Schedule

## 9.1 ECOS

현재 macro collection schedule을 조사한 뒤 기존 운영주기와 결합한다.

월간 통계이므로 매일 불필요한 대규모 backfill은 금지.

권장:

- 기존 scheduled macro path 유지
- 최근 48개월 또는 evidence 기반 rolling window로 revision 반영
- 신규 historical backfill은 manual workflow

## 9.2 FISIS/금융공공데이터

경제적 관측주기와 API endpoint의 업데이트 빈도를 D0에서 분리 기록한다.

예:

```text
API service refresh = daily/real-time label
financial observation = quarterly
```

이 경우 수집 스케줄은 월 1~수회 polling이면 충분할 수 있다.

D0 evidence 없이 daily schedule을 만들지 않는다.

---

# 10. CLI / Diagnostics

최소 CLI 요구사항:

```text
rate-monitor collect-market-funding --source bok_ecos_macro --dry-run
rate-monitor collect-market-funding --source fsc_savings_bank --period 202606 --dry-run
rate-monitor funding-data-audit
```

실제 command naming은 현재 CLI architecture를 조사해 일관되게 맞춘다.

`funding-data-audit` 출력 예:

```text
ECOS
  savings_bank_balance: 49 points, latest=2026-07, missing=0
  credit_union_balance: 49 points, latest=2026-07, missing=0

FSC SAVINGS BANK
  institutions=79
  mapped=77
  unmapped=2
  metrics=1
  latest=2026Q2
  duplicates=0
```

---

# 11. Tests

## 11.1 ECOS parser

- exact stat code mismatch rejects/warns per current convention
- exact item name mismatch
- unit drift
- invalid month
- invalid numeric
- other item mixed in response
- new nonbank rate contract
- bank balance contract

## 11.2 FISIS/FSC parser

Fixture-based tests:

- required fields
- pagination
- basYm parsing
- institution code preservation
- exact metric whitelist
- amount unit conversion
- missing vs zero
- schema drift fail-closed

## 11.3 persistence

- same key idempotent
- revised value policy
- institution_id nullable
- duplicate source row does not duplicate stored observation
- raw_artifact FK retained

## 11.4 migration

- empty DB upgrade
- current schema upgrade
- unique/index contract

---

# 12. Verification Gate

## D0

- read-only source probes succeed
- exact code evidence committed
- no secrets

## D1

- unit/parser tests pass
- existing seven ECOS macro contracts unchanged
- sample backfill on temporary DB
- recent 24 months continuity report

## D2

- migration success
- minimum 2 periods sample for institution metric
- institution count sanity
- unmapped identities explicitly reported
- no name-only merge

## Full repository

가능한 경우:

```text
uv run ruff check src tests
uv run pytest
alembic upgrade head on empty DB
```

현재 CI contract를 추가로 확인하고 관련 workflow가 있으면 실행한다.

---

# 13. Implementation Boundary

## PR/Stage 1 — Recon only

변경:

- diagnostics/workflow if needed
- source-recon docs/json

DB 변경 없음.

## PR/Stage 2 — ECOS extension

변경:

- macro contracts/parser/adapter
- backfill command/workflow
- tests

기존 `market_indicators` schema 유지 가능하면 migration 없음.

## PR/Stage 3 — Institution funding

변경:

- new collector
- new persistence model/migration
- tests/audit

저축은행 먼저 구현하고 신협/농협은 exact contract가 동일한 경우만 같은 PR 또는 후속 PR로 확장한다.

한 PR에서 모든 업권을 동시에 구현하지 않는 것을 기본으로 한다.

---

# 14. 표시/분석 단계로 넘길 데이터 계약

UI 팀/후속 Strategy 단계는 수집 DB를 직접 해석하지 않고 service layer에서 아래 normalized record를 받는다.

## sector funding record

```json
{
  "period": "2026-07",
  "sector": "savings_bank",
  "balance": 104.2,
  "balance_unit": "trillion_krw",
  "rate_1y": 3.62,
  "rate_unit": "percent",
  "balance_source": "bok_ecos_macro",
  "rate_source": "bok_ecos_macro"
}
```

## institution funding record

```json
{
  "period": "2026Q2",
  "sector": "savings_bank",
  "source_entity_code": "...",
  "institution_id": null,
  "institution_name": "...저축은행",
  "metric": "total_deposits",
  "value": 1234567,
  "unit": "million_krw",
  "source": "fsc_financial_stats_savings_bank"
}
```

후속 분석에서만 MoM/QoQ/YoY를 계산한다.

---

# 15. 특판과의 경계

이번 작업에서 특판 데이터 수집은 구현하지 않는다.

확정된 제품정책:

```text
시중은행 특판
= 시장 특판 레이더 / 벤치마킹
!= 저축은행 직접 경쟁순위
```

수신시장 데이터가 안정화되면 특판 시작·종료 시점과 업권 수신흐름을 **관찰형 annotation**으로 함께 보여줄 수 있다.

예:

```text
2026-08: 주요 시중은행 고금리 적금 프로모션 집중
```

하지만 특판 때문에 수신이 이동했다고 자동 인과판정하지 않는다.

---

# 16. Adversarial Review Checklist

구현자는 완료 전 "내 설계가 틀렸다"고 가정하고 아래를 다시 확인한다.

1. 이미 존재하는 ECOS macro series를 중복 저장하고 있지 않은가?
2. `1120800 상호금융`을 농축협만으로 오해했는가?
3. 말잔과 평잔을 섞었는가?
4. API의 `업데이트 주기`와 통계의 관측주기를 혼동했는가?
5. FISIS 재무항목의 총부채를 예수금으로 잘못 해석했는가?
6. 단위를 추정했는가?
7. 기관명을 fuzzy matching해 identity를 오염시켰는가?
8. 공표일을 수집일로 대체했는가?
9. missing을 0으로 저장했는가?
10. derived MoM/QoQ 값을 source fact처럼 persistence했는가?
11. ECOS revision이 왔을 때 과거값 정책이 정의돼 있는가?
12. raw artifact에서 저장값까지 provenance를 역추적할 수 있는가?

---

# 17. Claude Review Questions

Claude에 아래 질문으로 리뷰를 요청한다.

1. 현재 `market_indicators`를 업권 수신잔액/금리에 계속 사용하는 것이 architecture상 자연스러운가?
2. `institution_funding_observations` 신규 테이블은 지나치게 범용적이거나 부족하지 않은가?
3. 금융회사 identity를 nullable mapping으로 분리하는 방식이 existing stable identity와 충돌하지 않는가?
4. D0→D1→D2의 Evidence Gate가 금융데이터 변경 위험에 충분한가?
5. scheduled rolling fetch와 historical backfill 분리가 기존 collector conventions와 맞는가?
6. derived metric 비영속화 방침이 dashboard build 성능/복잡도 측면에서 적절한가?
7. 이 명세에서 빠진 FISIS/FSC API의 장애·rate-limit·revision 위험이 있는가?
8. Stage 3을 저축은행 우선으로 제한하는 것이 최소 범위 원칙에 맞는가?

---

# 18. Done Definition

이번 **문서 단계** Done:

- 기획서와 작업명세서가 최신 main 구조를 반영
- 기존 ECOS macro 구현을 중복 계획하지 않음
- 검증된 current contracts와 미확정 source contracts를 분리
- 특판 구현은 scope 밖으로 분리
- Claude review 질문 명시

실제 **데이터 수집 구현 단계** Done은 별도 PR들에서 D0/D1/D2 Gate를 각각 통과한 뒤 판정한다.
