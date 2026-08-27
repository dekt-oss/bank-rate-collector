# Strategy v2 — 수신시장·금리경쟁 통합 개편안

- 작성일: 2026-08-27
- 상태: **기획/구현 경계 확정 전 검토본**
- 기준 브랜치: `feat/market-funding-stage0-d0-20260827`
- 관련: Issue #108, #167, #205
- 데이터 근거:
  - `docs/source-recon/market-funding-d0-evidence-20260827.md`
  - `docs/source-recon/market-funding-d1-evidence-20260827.md`

## 0. 결론

이번 데이터 확장은 기존 Strategy에 카드 몇 개를 붙이는 수준이 아니다.

현재 Strategy가 주로 **공시금리 경쟁상황 → 인사이트 → 지역/TOP5 → 상품기획**을 보여준다면, D0 이후에는 다음 의사결정 루프를 하나의 화면에서 만들 수 있다.

> **시장에 돈이 어디에 쌓이고 있는가 → 실제 조달금리가 어떻게 움직이는가 → 경쟁사가 어떤 가격을 제시하는가 → 당사는 어디에 위치하는가 → 어떤 수신상품/금리를 설계할 것인가**

따라서 Strategy v2의 핵심은 `시장자금 → 금리경쟁 → 당사위치 → 수신반응/구조 → 실행` 순으로 기존 화면을 재배치·통합하는 것이다.

새 페이지를 하나 더 만드는 대신 기존 `/strategy.html`을 정식 Strategy workspace로 유지하면서 정보 위계를 재설계한다.

Production Strategy는 현재 정식 운영 기능이다(Issue #205). 이번 개편은 Strategy를 숨기거나 release gate를 끄는 작업이 아니다.

---

# 1. 현재 Strategy 화면 — 무엇을 보존할 것인가

현재 `web/templates/strategy.html`의 주요 구조는 다음이다.

1. 시장 범위/상품/가입기간 scope
2. decision/evidence strip
3. KPI
   - 시장 최고
   - 시장 평균
   - 시장 집단 수
   - 상위10 중앙
4. `시장 흐름`
   - 금리 추세 63일
   - 최근 금리 변동 30일
5. `시장 해석`
   - 오늘의 판단
   - 우대조건 트렌드
6. `경쟁 구도`
   - 지역별 금리
   - 업권별 TOP5
7. `상품 기획`
   - 상품기획 simulator
   - 경쟁 위치
   - 예금 모드의 수신반응 예측

이 기능들은 대부분 폐기 대상이 아니다. 문제는 **의사결정 중요도에 비해 공시금리 화면의 비중이 너무 크고, 자금시장 자체의 크기·변화·실현금리가 빠져 있었다**는 것이다.

## 보존 원칙

- 현재 prediction coefficients/formula를 이번 화면개편에서 변경하지 않는다.
- source precedence를 변경하지 않는다.
- stable product identity/dedupe를 변경하지 않는다.
- 기존 TOP5 own-position decoration을 보존한다.
- 기존 `오늘의 판단 → 근거 → 행동` presentation 방향을 확장한다.
- 지역 지도와 우대조건은 제거하지 않고 **detail layer**로 내린다.

---

# 2. D0 이후 새로 확보된 의사결정 데이터

## 2.1 업권별 실제 신규취급 수신금리

ECOS exact series로 월별 1년 금리를 확보했다.

예: 2026-07

| 업권 | 실제 신규취급 대표금리 |
|---|---:|
| 예금은행 | 3.48% |
| 저축은행 | 4.21% |
| 신협 | 3.56% |
| 새마을금고 | 3.48% |

이는 기존 collector의 공시 최고금리/기본금리와 의미가 다르다.

- collector: **경쟁사가 제시한 가격**
- ECOS: **시장에서 실제 신규취급된 대표 조달가격**

둘을 합치면 `공시 ↔ 실현금리` 간극을 분석할 수 있다.

## 2.2 업권별 수신잔액

2026-06 말 실제 값:

| 업권 | 잔액 |
|---|---:|
| 예금은행 | 2,281.489조 |
| 저축은행 | 100.356조 |
| 신협 | 140.366조 |
| 광의 상호금융 | 519.427조 |
| 새마을금고 | 243.248조 |

따라서 업권간 자금시장 크기와 월별 증감을 Strategy의 공식 데이터로 만들 수 있다.

단, `잔액 증감`을 `신규 순유입`이라고 부르지 않는다.

## 2.3 예금은행 상품 구조

2026-06:

- 총예금 2,281.4891조
- 저축성예금 1,896.1270조
- 정기예금 1,132.5026조
- 정기적금 62.6589조

## 2.4 정기예금 만기 구조

2026-06:

- 6개월 미만: 238.366조
- 6개월~1년 미만: 176.076조
- 1년~2년 미만: 661.979조
- 2년~3년 미만: 29.438조
- 3년 이상: 26.643조

이 값들은 정기예금 총액과 정확히 reconciliation됐다.

## 2.5 release lag

현재 실제 관측:

- 금리 최신월: 2026-07
- 수신잔액 최신월: 2026-06

따라서 Strategy는 하나의 `최신` 기준으로 합치면 안 된다.

---

# 3. Strategy v2의 핵심 UX 원칙

## 3.1 한 화면의 질문을 5개로 제한한다

사용자가 위에서 아래로 다음 질문에 답을 얻도록 한다.

1. **지금 수신시장의 방향은?**
2. **금리경쟁은 얼마나 강한가?**
3. **당사는 경쟁사 대비 어디에 있는가?**
4. **금리 변화 뒤 수신잔액은 어떻게 반응했는가?**
5. **그래서 어떤 상품·금리를 설계해야 하는가?**

## 3.2 같은 월과 최신 신호를 분리한다

화면 상단에 두 clock을 둔다.

### 분석 기준월

금리와 수신잔액을 같이 비교할 수 있는 가장 최근 공통월.

예:

> 분석 기준월 `2026-06`

### 최신 선행신호

더 늦게 공표된 금리 등이 있으면 별도 표시.

예:

> 최신 금리 `2026-07` · 저축은행 4.21% · 전월 +47bp
> 7월 수신잔액은 공표 대기

절대로 7월 금리와 6월 잔액을 한 행에 넣고 동월 데이터처럼 보이지 않게 한다.

## 3.3 모든 시장지표에 basis를 노출한다

최소 다음 metadata를 UI 또는 tooltip/detail에 제공한다.

- source
- source effective date/month
- frequency
- `신규취급액 가중평균` / `월말 말잔`
- population
- latest/release lag

`5대은행 기사 데이터`와 `전체 예금은행 ECOS` 같은 모집단 차이를 숨기지 않는다.

---

# 4. 목표 IA — Strategy v2

상단 sticky sub-navigation 후보:

> **브리핑 | 자금흐름 | 금리경쟁 | 당사포지션 | 수신반응 | 수신구조 | 상품기획**

모바일에서는 전부 동시에 노출하지 말고 horizontal scroll/segmented anchor로 처리한다.

---

# 5. Section A — 오늘의 수신 브리핑 [신규 / 최상단]

현재 4개 KPI가 차지하는 최상단을 **의사결정형 hero**로 교체한다.

## Card A1. 자금 방향

예:

> **은행권 증가 / 비은행 주요 업권 감소**
>
> 2026-06 예금은행 +26.19조 (+1.16%)
> 저축은행 -0.09조 (-0.09%)

표현 금지:

> “비은행에서 은행으로 26조 이동”

직접 자금추적 데이터가 아니므로 업권간 transfer를 단정하지 않는다.

## Card A2. 실현 조달금리

예:

> 저축은행 1년 신규취급 3.74%
> 전월 대비 +35bp

그리고 별도 leading badge:

> 7월 4.21% / +47bp

## Card A3. 공시 ↔ 실현 금리차

기존 collector의 동월 12개월 공시금리 중앙값/상위권과 ECOS 신규취급금리를 비교한다.

예시 개념:

```text
공시 중앙값 4.15%
실현 신규취급 3.74%
spread +41bp
```

정확한 비교군은 같은 업권/상품유형/가입기간으로 align 가능한지 검증한 뒤 활성화한다.

## Card A4. 당사 위치

현재 own-position logic을 hero 수준으로 끌어올린다.

- 당사 최고/기본금리
- 경쟁 중앙값 대비 bp
- TOP5 경계 대비 bp
- 시장 순위

D1 개별기관 수신잔액이 검증되면 추가:

- 당사 수신잔액
- 1M/3M/12M 성장률
- 업권 성장률 대비 상대성장

D1 미검증 동안은 이 부분을 빈 카드로 두지 말고 **아예 노출하지 않는다.**

---

# 6. Section B — 수신시장 흐름 [신규 핵심]

목적:

> **돈이 어느 업권에 얼마나 쌓여 있고 최근 방향이 어떤가**

## B1. 업권별 수신잔액 trend

기본 표시:

- 예금은행
- 저축은행
- 신협
- 새마을금고

광의 상호금융은 필요에 따라 별도 참조 series로 표시한다. 이를 `농·축협`과 1:1로 오인시키지 않는다.

### 차트

절대 잔액 규모가 너무 달라 한 축에서 은행이 다른 업권을 압도하므로 기본 그래프는 다음 중 하나가 적합하다.

- index=100 normalized trend
- 업권별 small multiples
- 절대잔액/증감률 toggle

한 그래프에 모든 절대금액을 억지로 겹치지 않는다.

## B2. 이번달 증감 heat row

| 업권 | 잔액 | 전월 증감액 | 전월 증감률 |
|---|---:|---:|---:|

이 표는 시장 방향을 가장 빠르게 읽는 용도다.

## B3. 12/24/36개월 변화

단기 노이즈와 구조변화를 분리한다.

- 1M
- 3M
- 12M
- 필요시 24M/36M detail

---

# 7. Section C — 금리 경쟁 [기존 기능 대폭 통합]

현재 `시장 흐름`의 금리 중심 기능을 여기로 모은다.

## 유지

- 63일 공시금리 추세
- 최근 30일 금리 변동
- 시장 최고
- 시장 평균
- 상위10 중앙
- 경쟁사 TOP5
- own institution position

## 추가

### C1. 실현금리 benchmark

ECOS 1년 신규취급금리를 reference line/card로 추가한다.

### C2. 공시↔실현 spread

공시 경쟁이 실제 조달가격에 어느 정도 반영되는지 볼 수 있게 한다.

### C3. 경쟁 강도

예:

- 30일 인상기관 비중
- 상위10 중앙 변화 bp
- 상위권 dispersion
- 특판 등장/소멸 수

기존 데이터로 검증 가능한 항목부터 넣고, 새 causal metric을 만들지 않는다.

---

# 8. Section D — 당사 조달 포지션 [D1 성공 시 신규 핵심]

이 섹션은 개별기관 예수금 actual data가 Evidence Gate를 통과한 뒤 활성화한다.

## D1. 당사 vs 업권

- 당사 수신잔액
- 전월 증감액/증감률
- 3M/12M 성장률
- 업권 growth 대비 상대성장
- peer median 성장률

## D2. 당사 금리 위치

현재 Strategy의 금리 ranking을 연결한다.

```text
당사 금리 gap = 당사 공시금리 - peer median
상대 수신성장 = 당사 잔액성장률 - sector 성장률
```

## D3. peer matrix

개별 저축은행/조합을 대상으로:

| 기관 | 공시금리 | 금리 gap | 수신잔액 | 1M 성장 | 12M 성장 |
|---|---:|---:|---:|---:|---:|

단, identity/coverage가 충분한 기관만 포함한다.

## D4. scatter

충분한 역사와 동일 basis가 확보되면:

> x = 경쟁금리 gap
> y = 다음달 상대 수신성장

으로 표시한다.

차트 제목은 `금리 위치와 다음달 수신성장의 관계`처럼 쓰고 `금리 인상 효과`라고 부르지 않는다.

---

# 9. Section E — 금리-수신 반응 [신규]

이 섹션은 **관계/반응 분석**이다. 인과효과 분석이 아니다.

## 기본 lag

- T0
- T+1
- T+2

D0에서 금리와 잔액 release lag가 다른 것이 실제로 확인됐기 때문에 lag alignment를 데이터 모델 수준에서 명시한다.

## 기본 계산

```text
rate_change_bp(t)
balance_growth(t)
balance_growth(t+1)
balance_growth(t+2)
```

개별기관 데이터가 생기면:

```text
rate_gap(t) = institution_rate(t) - peer_median_rate(t)
relative_balance_growth(t+1)
  = institution_balance_growth(t+1) - sector_balance_growth(t+1)
```

## 화면

### E1. reaction matrix

| 금리 변화월 | Δ금리 | 동월 잔액 | T+1 | T+2 |
|---|---:|---:|---:|---:|

### E2. rolling relationship

12/24/36개월 window.

### E3. 해석 문구

허용:

> 최근 24개월에서 금리상승 뒤 다음달 상대 수신성장이 함께 높아진 구간이 많았다.

금지:

> 금리를 10bp 올리면 수신이 0.8% 증가한다.

후자는 통제변수와 충분한 표본을 갖춘 별도 모델이 검증될 때만 가능하다.

---

# 10. Section F — 수신 구조 [신규]

## F1. 예금 vs 적금 구조

ECOS 예금은행:

- 정기예금
- 정기적금
- 기타 저축성예금

추이와 mix 변화를 보여준다.

이 카드로 기사에서 보던 `정기적금 감소`를 표준 공공데이터 시계열로 계속 확인할 수 있다.

## F2. 정기예금 만기구조

- <6M
- 6M~<1Y
- 1Y~<2Y
- 2Y~<3Y
- 3Y+

현재 실제 데이터에서는 1Y~<2Y 비중이 매우 크므로, 단순 숫자보다 stacked bar/100% mix가 적절하다.

## F3. D1 확장

개별기관 재무 API가 예수금 구성까지 제공할 경우에만:

- 당사 수신 mix
- peer mix
- 업권 mix

를 추가한다.

필드가 없으면 추정하지 않는다.

---

# 11. Section G — 경쟁 디테일 [기존 기능 재배치]

현재 중요하지만 상단 핵심 decision flow와는 한 단계 떨어지는 항목을 모은다.

## 유지

- 우대조건 트렌드
- 지역별 금리 지도
- TOP5 detail
- 부산 drill-down
- 업권별 상세 filter

## 배치

`금리 경쟁` 아래의 detail 영역 또는 sub-tab/accordion이 적합하다.

특히 지도는 유용하지만 전체 Strategy의 primary hero가 될 필요는 없다.

Issue #108의 요구였던 `인사이트 선배치 / 지도·TOP5 축소`와도 일치한다.

---

# 12. Section H — 상품 기획 / 실행 [기존 엔진 보존 + context 강화]

현재 product-planning simulator는 유지한다.

## 변경하지 않을 것

- 현재 prediction coefficients
- 현재 structural formula
- current β/γ assumptions
- source precedence
- identity/dedupe

Issue #167의 private calibration 경계도 그대로 유지한다.

## 추가할 context

상품기획 카드 옆에 현재 시장 context를 작은 strip으로 제공한다.

예:

```text
시장 실현 1Y 4.21% ↑47bp
저축은행 수신잔액 100.36조 ↓0.09%
공시 상위10 중앙 4.35%
당사 4.10% / 상위10 대비 -25bp
```

이 정보는 prediction coefficient에 몰래 넣는 feature가 아니라 **사용자 의사결정 context**다.

추후 calibration model에서 사용하려면 #167의 private training/inference 경계를 통해 별도 검증한다.

---

# 13. `오늘의 판단` 업그레이드

현재 insight card를 없애지 않고 Strategy v2 전체를 요약하는 **Action Center**로 승격한다.

각 insight는 반드시 3단 구조를 쓴다.

### 상황

> 저축은행 신규취급금리가 2개월 연속 상승했지만 6월 수신잔액은 감소했다.

### 근거

> 6월 신규취급 3.74% (+35bp), 잔액 100.36조 (-0.09%)
> 7월 신규취급 4.21% (+47bp), 7월 잔액 공표 대기

### 행동

> 공시 최고금리 단독 추종보다 7월 수신잔액 발표와 경쟁사 12개월 상위권 변화를 함께 확인.

이렇게 해야 사용자가 지표를 보고 다시 해석하는 부담을 줄일 수 있다.

---

# 14. 화면 밀도 / desktop layout 권고

## 상단 1 screen

1. scope + 분석기준월
2. 오늘의 수신 브리핑 4카드
3. Action Center 1~2줄

사용자는 첫 화면에서:

- 자금 방향
- 금리 방향
- 당사 위치

를 모두 파악해야 한다.

## 중단

2-column 또는 12-column grid:

- 수신시장 흐름 7/12
- 금리경쟁 5/12
- 이후 full-width 반응분석

## 하단

- 수신구조
- 경쟁 detail
- 상품기획 workspace

상품기획은 긴 interaction이 있으므로 bottom anchor로 유지해도 된다.

---

# 15. 모바일 전략

모바일에서 desktop chart를 축소만 해서는 안 된다.

우선순위:

1. 브리핑
2. Action Center
3. 업권별 증감 row
4. 당사 위치
5. 상품기획 핵심 input

장기 chart/만기구조/지도는 horizontal scroll이 아니라:

- compact cards
- single-series selector
- expandable detail

을 사용한다.

---

# 16. Data contract 제안

기존 product-rate dataset과 시장 funding dataset을 한 row 구조로 합치지 않는다.

## 16.1 market funding series

최소 contract:

```text
series_code
series_name
source_id
scope_type        # sector / institution
scope_key
metric_kind       # rate / balance / mix
basis             # new_business_weighted_avg / end_of_month
frequency         # monthly
source_effective_at
value
unit
source_locator
revision metadata
```

## 16.2 analysis derived layer

원본과 파생값을 분리한다.

```text
balance_change
balance_growth
rate_change_bp
rate_gap
relative_balance_growth
lag_months
analysis_window
```

Derived row에도 source months를 보존한다.

---

# 17. 절대 금지 semantic

1. `잔액 증가 = 신규 순유입`
2. `A업권 감소분이 B업권으로 이동`
3. 서로 다른 최신월을 같은 월로 합침
4. 5대은행 기사 모집단과 전체 예금은행 ECOS 혼합
5. `광의 상호금융 = 농축협` 1:1 표기
6. 개별기관 identity 검증 전 합계/순위
7. correlation을 `금리 인상 효과`로 표현
8. 공시금리와 신규취급 실현금리를 같은 정의처럼 사용
9. 추정 Data.go operation/field를 저장계약으로 승격

---

# 18. 구현 단계

## Stage S0 — 저장 안전성 완료

D0에서 발견된 2,000조원대 balance를 안전하게 저장할 wide fixed-decimal `Quantity`를 완성한다.

- model
- migration
- historical compatibility
- tests
- revision audit

완료 전 신규 대형 balance를 production DB에 쓰지 않는다.

## Stage S1 — ECOS market funding persistence/backfill

이미 exact-verified series부터 저장한다.

- 업권 실현 1Y rate
- 업권 balance
- bank deposit categories
- maturity buckets

임시 DB integration → production snapshot flow 순.

## Stage S2 — Strategy v2 data payload

UI를 먼저 만들지 말고 stable JSON/service contract부터 만든다.

- analysis month
- leading month
- briefing
- funding trends
- realized vs advertised rate

## Stage S3 — Strategy v2 Core UI

- new briefing hero
- funding flow
- upgraded rate competition
- Action Center
- current detail sections rearrangement

이 단계만으로도 D1 없이 상당한 Strategy v2가 성립한다.

## Stage S4 — D1 institution funding

`DATA_GO_KR_SERVICE_KEY`가 준비되고 actual rows 검증 후:

- 저축은행
- 신협
- 농업협동조합

순으로 exact contract를 만든다.

업권별로 Evidence Gate를 독립 적용한다. 세 업권을 한 번에 통과한 것으로 간주하지 않는다.

## Stage S5 — 당사 조달 포지션

기관 identity가 맞는 업권만:

- balance trend
- peer growth
- relative growth
- matrix/scatter

활성화.

## Stage S6 — 금리-수신 반응

T0/T+1/T+2 + 12/24/36m relationship metrics.

## Stage S7 — 예측/calibration 후속

내부 실적과 결합하는 단계는 Issue #167의 private boundary를 따른다. Strategy v2 UI 개편과 섞지 않는다.

---

# 19. 권장 1차 출시 범위

Strategy v2 첫 버전은 **D1을 기다리지 않고** 다음으로 충분히 출시 가치가 있다.

### 포함

- 오늘의 수신 브리핑
- 업권 수신시장 흐름
- 실현 1Y 조달금리
- 기존 공시금리 경쟁과 통합
- 분석 기준월 / 최신 선행신호 분리
- 은행 예금/적금 구조
- 정기예금 만기구조
- 기존 지역/TOP5/우대조건 재배치
- 기존 상품기획 엔진 보존

### 후속 활성화

- 개별 저축은행 예수금
- 개별 신협 예수금
- 개별 농축협 예수금
- 당사/peer balance position
- institution-level rate-vs-balance relationship

이 구조라면 D1이 늦어져도 Core Strategy v2 전체가 빈 화면이 되지 않는다.

---

# 20. Acceptance criteria

## Data

- source/date/frequency/basis/population이 모든 new series에서 추적 가능
- analysis month와 leading month를 코드 수준에서 구분
- balance wide-decimal 저장 안전성 검증
- revision 발생 시 최신값 silent overwrite가 아니라 provenance 유지

## Calculation

- stock/flow semantic tests
- lag alignment tests
- no division by zero
- missing month handling
- sector/institution denominator tests

## UI

- 첫 viewport에서 시장방향/금리방향/당사위치 파악 가능
- current Strategy 기능 손실 없음
- desktop/mobile layout smoke
- current data-unavailable 상태에서 graceful fallback
- source/effective-month visibility

## Regression

- current product filtering/ranking/source precedence unchanged unless separately specified
- existing prediction engine output unchanged
- stable product identity unchanged
- Strategy production publication remains ON

---

# 21. 최종 권고

현재 Strategy의 장점은 이미 **경쟁 공시금리와 상품기획 도구가 연결되어 있다는 점**이다.

D0가 추가한 데이터의 가치는 이를 별도 통계 페이지로 만드는 것이 아니라, 기존 Strategy 앞단에 **시장자금과 실제 조달가격이라는 두 개의 현실 레이어**를 붙이는 데 있다.

따라서 Strategy v2는 다음 한 문장으로 정의한다.

> **경쟁사가 몇 %를 주는지 보는 화면에서, 시장의 돈이 어디로 움직이고 실제 조달금리가 어떻게 형성되는지 확인한 뒤 당사 상품가격을 결정하는 수신 전략 워크스페이스로 확장한다.**

이 방향을 기준으로 S0→S1→S2→S3를 Core Track으로 먼저 진행하고, D1 institution data는 검증되는 업권부터 S4/S5에 progressive enhancement하는 것이 가장 안전하다.
