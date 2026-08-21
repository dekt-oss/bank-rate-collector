# Strategy 금리결정·시장근거 세부개선 v1

```yaml
document_type: implementation_spec
status: implementation/current-work
date: 2026-08-21
repository: dekt-oss/bank-rate-collector
base: main@b314b98fff207356bae8161b1f3bcefd9eb899c7
production_strategy_release_gate: unchanged
merge_policy: explicit_user_approval
```

## 1. 목적

Strategy를 실제 수신상품 담당자가 금리결정 근거를 읽는 순서에 맞춰 세부 조정한다.
이번 작업은 기존 수집·금리계산·예측계수·stable product identity를 바꾸지 않고,
이미 존재하는 Evidence와 미보정 수신 시나리오를 더 읽기 쉽게 표시한다.

## 2. 금리결정·수신반응 시나리오

### 2.1 대비와 글자 크기

- 현재 light theme에서 희미한 `planning-strip`, prediction, scenario surface의
  배경/테두리/본문 대비를 높인다.
- `수신금액 예측 엔진`의 제목·입력 라벨·설명·결과 글자를 한 단계 키운다.
- 접근성을 위해 색만으로 상태를 구분하지 않는다.

### 2.2 저민감 / 기준 / 고민감

기존 `inflow-structural-v1`의 아래 계수를 그대로 쓴다.

| 시나리오 | beta_new / +10bp | gamma_rollover / +10bp |
| --- | ---: | ---: |
| 저민감 | 0.02 | 0.04 |
| 기준 | 0.05 | 0.08 |
| 고민감 | 0.10 | 0.16 |

기존 min~max 범위 한 줄만 보여주지 않고, 제안금리에 대해 세 시나리오를 각각 표시한다.
각 카드에는 최소한 다음을 표시한다.

- 예상 신규자금
- 예상 재예치액 및 재예치율
- 예상 총수신
- 현재금리 baseline 대비 총수신 증감
- 추가 표면이자비용

세 시나리오는 **미보정 스트레스 가정**이며 확률구간/신뢰구간으로 표현하지 않는다.

### 2.3 단일 브라우저 예측 구현 계약

브라우저 예측 산식은 `web/templates/strategy.html`의 `runInflowScenario` / `predictInflow`만
실행 구현으로 사용한다. 후속 presentation에 `logistic`, `runScenario`, `predictAll` 같은
두 번째 산식 구현을 만들지 않는다.

최종 Strategy HTML에서는 parity-tested `predictInflow` 반환에 `scenarios` map을 추가하고
`window.predictInflow = predictInflow`로 명시적으로 export한다. 따라서:

- 기존 Cockpit 금리별 수신반응 표
- 신규 저민감 / 기준 / 고민감 카드

모두 같은 `window.predictInflow(...)` 실행 결과를 소비한다. `runInflowScenario` drift는
기존 `tests/test_inflow_prediction_parity.py`의 골든벡터 및 deliberate drift probe가 잡아야 한다.

### 2.4 계산 수식과 모형 근거 분리

`예측모형 상세` 안에서 계산 수식을 먼저 보여준다.

```text
rate_steps = (제안금리 - 현재 당사금리) / 0.10%p

신규자금:
log_effect = clamp(beta_new × rate_steps, -1.5, +1.5)
predicted_new_money = baseline_new_money × exp(log_effect)

재예치:
p0 = 현재 재예치율
logit(p1) = logit(clamp(p0, 0.001, 0.999)) + gamma_rollover × rate_steps
predicted_rollover = maturity_amount × p1

총수신:
predicted_total = predicted_new_money + predicted_rollover
baseline_total = baseline_new_money + maturity_amount × p0
incremental_total = predicted_total - baseline_total

표면이자비용:
term_factor = term_months / 12
baseline_interest = baseline_total × 현재금리 × term_factor
predicted_interest = predicted_total × 제안금리 × term_factor
surface_interest_delta = predicted_interest - baseline_interest
```

외부 연구 및 계수 provenance는 별도 `모형 근거` details로 접기/펴기 한다.

## 3. 시장근거

### 3.1 BOK 신규취급 금리의 의미

`은행 순수저축성예금 신규취급`은 Finlife 공시상품 평균이 아니다.
한국은행 ECOS 예금은행 가중평균금리 중 해당 월 **새로 취급된 금액을 가중한
순수저축성예금 금리**다.

`은행 1년 정기예금 신규취급` 역시 해당 월 예금은행권의 1년 정기예금 신규취급액
가중평균을 12개월 경쟁 보조 anchor로 쓰는 값이다.

화면에서 이를 `예금은행권 신규취급액 가중평균`으로 명시한다.

### 3.2 업권 수신잔액을 주 근거로 승격

시장 자금환경 카드에서는 업권별 월말 수신잔액 MoM을 먼저, 더 큰 수치 계층으로
보여준다. 기준금리와 은행 신규취급 금리는 보조 금리환경으로 후순위 표시한다.

ECOS 월별 자료는 공표시차가 있으므로 `data_month`를 숨기지 않고
`공식 월간통계 최신 공표월`로 표시한다. 저장소가 원천보다 더 최신인 값을
추정하거나 보간하지 않는다.

### 3.3 30일 근거 두 종류를 구분

화면에는 서로 다른 두 30일 근거가 존재한다.

1. `market_changes`: 최근 30일에 실제로 발생한 상품 최고금리 변경 **이벤트 집계**
2. `market_intelligence`: 요청 window의 80~125% 범위에 있는 시작/종료
   stable-product snapshot을 비교하는 **동일상품 수준 변화 비교**

따라서 이벤트 집계는 존재하지만 30D baseline snapshot이 부족해
`market_intelligence`가 `insufficient_history`일 수 있다. 이를 모순처럼 보이지 않게
각 카드에 근거 종류를 명시한다.

### 3.4 시장 참여 폭

지원 scope에서는 비율만 아니라 아래 실제 건수를 함께 표시한다.

- 인상 n건
- 인하 n건
- 이동없음 n건
- 총 비교상품 n건

`churn`이라는 내부 용어는 화면에서 쓰지 않고
`상위 10% 구성 교체율`로 풀어 쓴다. 진입/이탈 건수도 함께 표시한다.

## 4. 12개월 시장 추이 그래프

절대금리 차이가 커 미세 등락이 평평해 보이는 문제를 해결하기 위해,
현재 절대금리 그래프를 없애지 않고 `금리수준` / `기준일 대비 변화(bp)` 두 보기를 제공한다.
기본 보기는 작은 움직임을 읽기 쉬운 `기준일 대비 변화(bp)`로 한다.

- 변화 보기에서 각 series 첫 관측값을 0bp 기준으로 정규화한다.
- 축은 실제 delta min/max에 padding을 둬 자동 맞춤한다.
- 절대금리 보기를 선택하면 기존 의미와 값을 보존한다.
- 수치 확대가 실제 변화폭을 왜곡하지 않도록 y축 단위를 명시한다.

## 5. 최근 시장 변화 패널

`최근 시장 변화 · 30일 방향과 주요 이벤트`는 최초 로드 시 펼쳐 둔다.
이후 사용자가 summary를 클릭해 접으면 그 조작을 존중하고 자동으로 다시 열지 않는다.
제목과 설명에서 `최근 30일 상품변경 이벤트 집계`임을 명시한다.

## 6. 의사결정 IA

기존 독립 `시장 인사이트` 카드는 `01 금리 결정`의 `금리결정 준비도` 바로 아래로
이동하고 중복 설명을 줄인다.

그 바로 아래에 `경쟁사 TOP5`를 배치한다.

목표 순서:

```text
01 금리 결정
  금리결정 준비도
  금리결정 인사이트
  경쟁사 TOP5
  금리·수신반응 시나리오

02 시장 근거
  업권 수신잔액 흐름
  보조 금리환경
  동일상품 snapshot 경쟁방향
  30일 상품변경 이벤트

03 상품·우대조건 설계
  Preference Intelligence
```

지역 지도는 기존 Search handoff 원칙을 유지하며 Strategy에서 다시 복원하지 않는다.
중복 지역 shell을 숨길 때 `.ux-region-handoff`는 숨기지 않는다. 별도 handoff
presentation 단계로 직전 모듈의 상태를 되돌리는 구조를 만들지 않는다.

## 7. 비범위

- DB / schema / migration
- collector / source parser 변경
- inflow sensitivity 계수 변경
- 실제 내부자료 calibration
- FTP 계산식 추가
- 순수신 optimizer
- source precedence / stable product identity
- Production Strategy Release Gate 변경

## 8. 검증

- 관련 Ruff / pytest
- 기존 Python inflow prediction 골든벡터 및 deliberate JS drift probe 유지
- 최종 HTML의 `runInflowScenario` / `predictInflow` 단일 구현 계약
- Cockpit `+10bp` 기준 결과와 민감도 `기준` 카드의 총수신·비용 동일
- presentation idempotency / fail-closed
- desktop 1440px / mobile 390px Chrome smoke
- 저/기준/고민감 3개 카드와 수식/근거 details 존재
- `최근 시장 변화` details 최초 open, 사용자 click 후 closed 상태 유지
- market-intelligence unsupported 30D와 event 30D의 근거 설명 동시 노출
- 추이 그래프 delta 모드에서 실제 첫 관측값 0bp 및 현재 delta와 일치
- 시장참여폭의 인상/인하/이동없음 건수와 service payload 일치
- 시장 인사이트 → TOP5가 금리결정 준비도 바로 아래 의사결정 블록에 배치
- Search 지역 상세 handoff 가시성 유지
- horizontal overflow 없음
- Production Strategy Release Gate 불변
