# 금리수집기 고도화 최종 작업명세서 v3
## Main Korea Map + Market Intelligence + Deposit Pricing Engine

```yaml
document_type: final_work_order
status: implementation_ready
date: 2026-08-18
repository: dekt-oss/bank-rate-collector
base_branch: main
working_branch: feat/main-korea-map-20260818
related_issue: 108
review_basis:
  - Fable static-code review
  - user business review 2026-08-18
production_strategy_release_gate: OFF
merge_policy: explicit_user_approval
```

---

# 0. 최종 목표

이 프로젝트의 최종 목적은 단순히 경쟁사 금리를 나열하거나 순위를 보여주는 것이 아니다.

최종 질문은 다음이다.

> **다음 기간에 필요한 순수신을 가장 낮은 조달비용으로 확보하려면 당사 예금금리를 얼마로 결정해야 하는가?**

따라서 Strategy는 최종적으로 다음 흐름을 가져야 한다.

```text
시장 현황
→ 최근 시장 변화
→ 현재 당사 금리에서 예상되는 신규수신·재예치·순수신
→ 금리 변경 시 수신 반응
→ 목표 순수신 달성을 위한 최소 필요금리
→ 추가 조달비용/FTP 확인
→ 상품·우대조건 설계 근거
```

`시장 순위`는 의사결정의 목적이 아니라 보조 설명변수다.

`TOP 10위까지 +몇 bp`를 핵심 KPI로 만들지 않는다.

---

# 1. 기존 Foundation 보존

다음은 이미 검증된 foundation으로 보고 특별한 Evidence 없이 재구현하지 않는다.

- Strategy 4업권
  - `savings_bank`
  - `cu`
  - `kfcc`
  - `nh_local`
- `수집 데이터 기준 최고금리`
- `strategy_rate_basis`
- stable product identity
- source precedence
- NH `기본금리 + e-joy` linkage 및 fail-closed
- 업권별 geography semantics
- 저축은행 전용 부산 drill-down
- OTHER 우대조건 원문 evidence
- Strategy Preview isolation
- shared writer concurrency
- Production Strategy Release Gate OFF

---

# 2. 외부 변수 현황과 최종 결정

## 2.1 이미 확보된 것

### 한국은행 기준금리 — 이미 수집

현재 `bok_ecos` collector가 ECOS에서 한국은행 기준금리를 별도 `market_indicators` 시계열로 저장한다.

현재 계약:

```text
STAT_CODE = 722Y001
ITEM_CODE = 0101000
CYCLE = D
indicator_code = bok_base_rate
```

따라서 새로 만들지 않는다.

---

### 시장 예금금리 — 이미 상당 부분 확보

금리수집기는 이미 다음 실물 상품 금리를 직접 관측한다.

- 저축은행
- 시중은행
- 새마을금고
- 신협
- 지역농축협

따라서 Strategy에서 필요한 주된 `시장금리`는 별도 채권지표를 먼저 추가하는 것이 아니라 현재 상품 데이터를 이용해 파생한다.

예:

- 시장 중앙값
- 평균
- 상위 구간
- 최고금리
- 당사 대비 spread
- 업권간 spread
- 7D/30D 변화
- 기간별 변화

---

### 시중은행 공시상품 금리 — 이미 수집

현재 Finlife bank 데이터로 시중은행 개별 정기예금 상품금리를 관측하고 있으며 메인에서는 12개월 시중은행 benchmark도 제공한다.

단 이것은 **공시상품의 금리 분포**이지 실제 신규취급액으로 가중된 은행권 실현금리가 아니다.

---

## 2.2 추가할 외부 변수

### A. 예금은행 신규취급액 기준 저축성수신금리 — 추가

한국은행 금융기관 가중평균금리의 `신규취급액 기준 저축성수신금리`를 Stage E0에서 추가 수집한다.

이유:

```text
현재 Finlife 은행금리
= 공시 상품들의 금리 수준

한국은행 신규취급액 가중평균금리
= 고객이 실제 신규로 가입한 금액을 가중한 시장 실현금리
```

두 값은 역할이 다르다.

이 지표는 다음 용도로 사용한다.

- 시장 전체 실현금리 regime
- 당사 공시금리와 실제 은행권 체결금리 수준 비교
- 내부 수신모형의 월별 macro control

ECOS 통계코드는 구현 전에 source reconnaissance로 확정하며 추정 하드코딩하지 않는다.

---

### B. 업권 전체 수신 증감 — 추가

월별 업권 전체 예금/수신 증감을 외부 시장 유동성 변수로 사용한다.

우선 대상:

- 예금은행 수신 증감
- 저축은행 수신 증감
- 상호금융 수신 증감

목적:

같은 당사 금리라도 시장 전체에 자금이 들어오는 달과 빠지는 달의 신규수신 반응은 다를 수 있다.

따라서 내부 수신액 변화 중

```text
당사 금리 효과
vs
시장 전체 자금 유입/유출 효과
```

를 분리하기 위한 control 변수다.

가능하면 한국은행 ECOS 공식 월별 통계를 사용한다.

---

## 2.3 은행채·시장성 조달금리 — v1 모델에서는 제외

### 판단

은행채 금리는 영향이 없는 지표는 아니다.

한국은행 설명 기준으로 1년 정기예금 금리는 1년 은행채 금리 같은 지표금리, 경쟁은행 예금금리, 은행의 자금 필요 정도 등을 함께 고려해 결정될 수 있다.

또한 2022~2023년에는 은행권의 시장성 수신 조달여건 변화와 예금 수신경쟁이 저축은행·상호금융으로 전이된 사례가 있었다.

그러나 본 프로젝트의 직접 의사결정 대상은 **고려저축은행 수신금리**다.

은행채의 경로는 대체로:

```text
은행채/시장성 조달여건
→ 시중은행 예금가격 결정
→ 시중은행 수신경쟁
→ 저축은행 금리 및 수신경쟁
```

이다.

현재 시스템은 중간 결과인 **시중은행 실제 공시 예금금리**를 이미 직접 관측한다.

따라서 v1에서는 은행채를 동시에 넣을 경우:

- 변수 증가
- 시중은행 예금금리와 중복 설명 가능성
- multicollinearity 가능성
- 결과 해석 난이도 증가

가 생긴다.

### 최종 결정

**은행채·CD·COFIX 등 시장성 조달금리는 Deposit Pricing Engine v1의 feature에서 제외한다.**

향후 calibration backtest에서 기존 변수만으로 설명되지 않는 regime error가 반복되고, 은행채를 추가했을 때 out-of-sample 성능이 유의하게 개선되는 Evidence가 있을 때만 재검토한다.

즉 현재는 `Excluded by evidence/scope`, 영구 금지가 아니다.

---

# 3. Stage A — Main Dashboard Korea Map

## 목표

메인 대시보드의 기존 사각형 권역 타일을 대한민국 지도형 카드로 교체한다.

이 단계는 **표현 개선**이며 계산 의미는 바꾸지 않는다.

## 원칙

```text
Data calculation = 기존 유지
Presentation = 사각형 타일 → 대한민국 지도
```

- `regionBasis()` 유지
- `regionRows()` median 유지
- 기존 filter reactivity 유지
- 기존 9개 region bucket 유지
- 17개 시도 SVG geometry는 presentation mapping으로 사용
- 부산 기존 구·군 detail 보존

## Strategy Gate 독립

현재 `korea-sido.svg` 배포 asset은 Strategy Release Gate와 결합되어 있다.

메인 페이지는 production 공개 화면이므로 gated asset에 runtime dependency를 두지 않는다.

**Stage A에서는 기존 geometry를 메인 presentation layer에 인라인 재사용한다.**

금지:

- Strategy Gate ON
- Strategy asset cleanup 완화
- `site_service.py` gate 정책 변경

## bank 업권

- 기존 concrete region evidence가 있으면 기존 계산만 사용
- nationwide만 있는 경우 시도별 복제 금지
- regional evidence가 없으면 neutral state + 안내

## Acceptance

- 기존 region tile 제거
- 즉시 대한민국으로 인지 가능한 지도
- 기존 median 값과 동일
- 기존 필터 반응 동일
- 부산 detail 보존
- Gate OFF에서도 정상
- desktop / 390px mobile 정상
- console/page error 없음

---

# 4. Stage B — Rate-to-Inflow Decision Cockpit

## 4.1 Stage B의 역할 재정의

Stage B는 순위 기능을 새로 만드는 단계가 아니다.

현재 메인 대시보드는 이미 금리분포·중앙값·당사 위치를 제공하고 Strategy simulator도 제안금리에 대한 예상 시장순위를 계산한다.

따라서 다음 기능은 핵심 개발대상에서 제외한다.

```text
10위권에 들어가려면 +몇 bp 필요한가
TOP5/TOP10 순위 자체를 목표로 하는 UI
메인 금리분포와 사실상 같은 Position Chart 중복
```

순위는 계속 표시할 수 있지만 **수신액 판단의 보조 근거**다.

---

## 4.2 Stage B의 핵심 질문

> **현재 금리라면 얼마의 수신을 기대할 수 있고, 금리를 바꾸면 그 수신액과 비용이 어떻게 달라지는가?**

현재 존재하는 `inflow_prediction_service.py` 및 Strategy prediction UI를 중심으로 화면을 재구성한다.

현재 엔진은 내부 실적 미보정이므로 Stage B 결과는 실제 forecast가 아니라 **uncalibrated stress scenario**다.

이 상태를 숨기지 않는다.

---

## 4.3 권장 화면

```text
[시장 위치]
당사 12M 3.50%
시장 중앙값 3.35%
시장 상단 3.70%
시장 내 위치: 참고정보

[금리 시나리오]
현재 3.50%
3.55%
3.60%
3.65%

각 시나리오:
- 예상 신규수신
- 예상 재예치
- 예상 총수신
- 현재 대비 증감
- 추가 표면이자비용
- 시장 위치/순위는 보조 표시
```

내부 calibration 이후에는 `순수신`과 FTP 반영 비용을 중심으로 전환한다.

---

# 5. Stage C — Market Intelligence

## 목표

시장의 금리 움직임을 `감`이 아니라 객관적인 지표로 만든다.

이 Stage는 두 가지 역할을 한다.

1. 실무자가 금리 결정의 근거로 사용
2. Stage E의 외부 시장 feature 생성

---

## 5.1 기본 지표

Evidence Gate 후 기간별로 계산한다.

- 7D / 30D
- 6M / 12M / 24M / 36M
- 업권별

후보:

### Rate Change Breadth

```text
인상 기관/상품 비중 - 인하 기관/상품 비중
```

시장 상승/하락의 폭을 측정한다.

### Upper-tier Momentum

상위 금리구간의 중앙값/threshold 변화.

### Market Median Change

기간별 시장 중앙값의 변화 bp.

### Competitor Momentum

당사 인접 경쟁군의 최근 인상/인하 빈도와 폭.

### Spread Change

- 당사 vs 저축은행 시장
- 당사 vs 시중은행
- 저축은행 vs 상호금융

### Market Churn

상위구간 진입/이탈 및 경쟁군 교체 정도.

---

## 5.2 시각화 원칙

숫자를 많이 나열하기보다 다음처럼 표현한다.

```text
12M 시장 방향: 상승
최근 7일 인상 우세
상단 +8bp / 중앙값 +2bp
부산 직접 경쟁군 4개사 인상
당사 spread +6bp → -2bp 악화
```

Stage C의 파생지표 정의와 universe는 각각 명시한다.

---

# 6. Stage D — Product / Preference Strategy

## 목표

`몇 %를 줄 것인가` 다음 질문인

> **그 금리를 어떤 상품구조와 우대조건으로 제공할 것인가?**

를 지원한다.

기존 preference taxonomy와 OTHER raw evidence를 재사용한다.

## 주요 비교

- 시장 전체 vs 상위 경쟁상품
- 당사 vs 직접 경쟁상품
- 기본금리 vs 우대폭 구조
- 비대면
- 신규고객
- 급여/연금
- 카드
- 자동이체
- 유지/만기
- 회원/지역
- 가입금액/기간
- 기타 특이조건

현재 evidence 없이 다음은 만들지 않는다.

- 우대조건 난이도 점수
- 고객 달성확률
- 실질 적용률

내부 실제 우대 달성 데이터가 확보되면 후속 calibration 대상으로 둔다.

---

# 7. Stage E — Deposit Pricing Engine

Stage E가 최종 핵심이다.

---

# 8. Stage E0 — Internal Data Evidence & Calibration Preparation

## 목표

현재 `inflow_prediction_service.py`의 미보정 민감도 스트레스 계수를 실제 고려저축은행 실적으로 교체할 수 있는 학습 데이터셋을 만든다.

내부 데이터 요구사항은 별도 문서:

```text
docs/specs/20260818-internal-deposit-data-request-v1.md
```

를 authoritative request로 사용한다.

## 원칙

- 개인정보 불필요
- 계좌번호 불필요
- 고객명 불필요
- 상품/기간/채널/일자 단위 집계 데이터 우선
- 최소 24개월, 권장 36개월
- 일 단위 권장, 주 단위 허용, 월 단위는 초기 탐색용 fallback

---

# 9. Stage E1 — Calibrated Inflow Model

## 목표

금리에 따른 다음 항목의 실제 반응을 추정한다.

```text
신규수신액
재예치율/재예치액
중도해지/이탈
순수신
```

핵심 개념은 `절대금리`보다 **상대금리**다.

예:

```text
당사 금리 - 저축은행 시장 중앙값
당사 금리 - 직접 경쟁군
당사 금리 - 시중은행 실현금리
당사 금리 - 상호금융 benchmark
```

---

## 9.1 내부 feature

필수 후보:

- 당사 실제 제공금리
- 상품
- 기간
- 채널
- 신규수신액
- 만기도래액
- 재예치액/재예치율
- 기존잔액
- 중도해지/이탈
- 특판/캠페인 여부

비용 계산:

- 기간별 FTP
- 내부 조달원가

---

## 9.2 외부 feature

v1 후보:

### 이미 존재

- 한국은행 기준금리
- 저축은행 상품금리 분포
- 시중은행 상품금리 분포
- 상호금융 금리
- Stage C 변화지표

### 신규 추가

- 예금은행 신규취급액 기준 저축성수신금리
- 업권 전체 수신 증감

### 제외

- 은행채
- CD
- COFIX
- 기타 채권시장 지표

단, out-of-sample 검증에서 incremental predictive value가 확인되면 이후 추가 가능하다.

---

## 9.3 모델 출력

예:

```text
제안금리: 3.58%

예상 신규수신: 160~195억원
예상 재예치: 242~260억원
예상 중도이탈: 18~25억원
예상 순수신: +22~47억원

현재 대비 추가 이자비용: +0.7억원
FTP 반영 증분 조달비용: +0.5억원
```

모든 forecast는 point estimate 하나보다 interval과 calibration status를 함께 제공한다.

---

# 10. Stage E2 — Target Net Inflow Optimizer

## 최종 목표

사용자가 원하는 목표를 먼저 넣는다.

```text
다음 달 목표 순수신 +30억원
12개월 정기예금
```

엔진은 가능한 금리 후보를 계산한다.

```text
3.50% → 예상 순수신 -8억원
3.55% → +10억원
3.58% → +31억원
3.60% → +42억원
```

그리고 다음을 제안한다.

> **목표 순수신 +30억원을 만족하는 최소 예상금리: 3.58%**

그 뒤 비용을 함께 보여준다.

```text
추가 이자비용
FTP 반영 조달비용
예상 수신 범위
시장 위치
주요 불확실성
```

시장 순위는 여기에서도 보조지표다.

---

# 11. 목표변수 정의

최종 모델의 primary target은 **순수신**으로 한다.

권장 정의:

```text
순수신 변화
= 신규수신
+ 재예치
- 만기 이탈
- 중도해지 등 기타 유출
```

단 실제 내부 회계/업무 정의와 일치시키기 위해 Stage E0에서 treasury/business definition을 먼저 확정한다.

신규수신만을 목표로 두지 않는다.

---

# 12. 개발 순서

최종 권장 순서:

```text
Stage A  Main Korea Map
   ↓
Stage B  Rate-to-Inflow Decision UI 정리
   ↓
Stage C  Market Intelligence
   ↘
    E0   내부 데이터 확보 및 calibration dataset 준비
   ↗
Stage D  Product / Preference Strategy
   ↓
Stage E1 Calibrated Inflow Model
   ↓
Stage E2 Target Net Inflow Optimizer
```

Stage C와 E0는 가능한 경우 병렬 준비할 수 있다.

---

# 13. PR Boundary

## PR A — Main Korea Map

- `site.html` map presentation
- 기존 region calculation 재사용
- mapping tests
- browser validation

## PR B — Rate-to-Inflow Decision Cockpit

- 기존 Strategy simulator 재배치/정리
- 순위 중심 문구 축소
- 수신액 시나리오 중심 IA
- 기존 uncalibrated 경고 유지

## PR C — Market Intelligence

- historical Evidence Gate
- 7D/30D 및 기간별 시장 변화 파생
- 시장 변화 지표/시각화

## PR D — Product / Preference Strategy

- top-tier vs market preference structure
- raw evidence drilldown

## PR E0 — Calibration Data Contract

내부 데이터가 실제 확보된 이후 작성한다.

내부 파일을 저장소에 직접 커밋하지 않는다.

## PR E1/E2

실제 내부 데이터 calibration과 검증을 거친 후 별도 진행한다.

---

# 14. Verification

## Stage A/B/C/D

- Ruff
- pytest
- migration/model parity
- inline JS validation
- desktop 1280/1440
- mobile 390
- console/page error 없음
- Strategy Release Gate OFF

## E1/E2 추가 검증

필수:

- train/validation/test time split
- leakage check
- baseline model 비교
- out-of-sample error
- 금리 변경구간 backtest
- campaign 기간 제외/포함 sensitivity
- regime별 성능
- interval coverage
- feature ablation

특히 외부 feature는 `추가하면 그럴듯하다`가 아니라 **실제 out-of-sample 성능 개선 여부**로 채택한다.

은행채 등 제외 변수도 같은 원칙으로 재평가한다.

---

# 15. Non-Goals / Safety Gates

사용자 승인 및 별도 Evidence 없이 다음을 하지 않는다.

- Strategy Release Gate ON
- 자동 merge
- canonical max_rate 변경
- collector/source precedence 재설계
- stable product identity 변경
- NH e-joy linkage 변경
- geography semantics 변경
- 내부 개인고객 raw data repository 저장
- 미보정 모델을 실제 forecast라고 표시
- 시장 순위를 수신성과의 원인으로 단정
- 은행채 등 변수를 근거 없이 계속 추가

---

# 16. 구현 착수 기준

현재 바로 착수 가능한 범위:

1. **PR A — Main Korea Map**
2. 이후 **PR B — Rate-to-Inflow Decision UI**
3. 동시에 Stage E0 내부데이터 요청 실행

Stage C는 historical Evidence Gate 후 진행한다.

Stage E1/E2는 내부 데이터 확보 및 품질검증 전에는 실제 calibration을 시작하지 않는다.

Production Strategy Release Gate는 계속 OFF다.
