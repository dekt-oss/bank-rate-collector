# Private Inflow Calibration Protocol v1 — 내부자료 수령 전 준비

- Date: 2026-08-25
- Parent Issue: #167
- Base main: `23e0f6869ca924ea3d9b2c1023b7a6c70d18bc9d`
- Public incumbent: Public Structural v2 / `inflow-structural-v1` 계열
- Scope: **내부자료 없이 미리 고정 가능한 private calibration 연구·검증 계약**
- Internal data: 이 public repository에 반입 금지
- Production Strategy: 정식 운영 기능 유지. 이번 작업은 공개 화면 계산을 변경하지 않음
- Merge: 사용자 별도 승인 전 금지

---

## 1. 목적

현재 Public Structural v2는 내부실적이 없는 상태에서 사용할 수 있는 구조적 시뮬레이터로 정비되어 있다.
실제 고려저축은행 내부실적이 들어오면 단순히 β/γ를 임의 조정하는 것이 아니라, 실제 과거기간에서 더 잘 맞는 calibrated challenger를 만들고 현재 구조모델과 동일한 시간축에서 비교한 뒤 **실제로 우수한 모델만 사람의 검토를 거쳐 승격**해야 한다.

이번 단계는 데이터를 기다리면서 멈춰 있는 단계가 아니다. 실제 자료 없이도 다음을 미리 고정한다.

1. 어떤 feature를 허용할지
2. 어떤 feature를 leakage로 금지할지
3. 어떤 모델군부터 검토할지
4. 시간순 backtest를 어떻게 자를지
5. 어떤 metric으로 incumbent와 challenger를 비교할지
6. 어느 정도 개선돼야 승격 검토 대상이 되는지
7. aggregate 성능이 좋아도 어떤 경우에는 승격을 막을지
8. 실제 모델 교체를 자동화하지 않는 governance 경계

---

## 2. 현재 상태와 목표 상태

### 현재

- Public Structural v2: 완료
- 내부자료 intake canonical contract: 완료
- PII 차단 및 최소 24개월 / 권장 36개월 history Gate: 완료
- public forecast allowlist / private metadata leak fail-closed: 완료
- 실제 내부자료 mapping/training/backtest: 자료 미수령으로 미착수

### 목표

내부자료가 도착하면 아래 순서로 바로 실행할 수 있는 상태를 만든다.

```text
source-specific internal files
        ↓
local/private adapter
        ↓
E0 intake gate
        ↓
as-of feature table
        ↓
expanding-window OOS backtest
        ↓
incumbent vs challengers
        ↓
promotion gate
        ↓
eligible_for_human_review
        ↓
사람의 검토/승인
        ↓
private champion registry
        ↓
public forecast adapter
        ↓
현재 Strategy Cockpit 재사용
```

이번 PR은 위 흐름 중 **feature / candidate / split / promotion contract**만 public code로 고정한다.

---

## 3. Feature contract

### 3.1 핵심 원칙

모든 feature는 **예측 대상기간이 시작되기 전에 이미 알 수 있었던 값(as-of data)**만 사용한다.

예를 들어 2026년 8월 수신액을 예측할 때 2026년 8월 말 잔액, 8월 실제 신규수신액, 8월 실제 재예치 결과를 feature로 넣으면 leakage다.

### 3.2 허용 feature group

#### Pricing

- `own_rate_pct`
- `rate_change_bp`
- `market_gap_bp`
- `market_rank_best`
- `market_rank_worst`
- `market_tie_count`
- `market_within_5bp_count`

현재 Public Structural 금액식에서는 시장순위가 직접 반영되지 않지만, **실제 내부자료가 들어오면 그것이 설명력이 있는지 challenger에서 검증**한다.

#### Product

- `product_key`
- `term_months`
- `channel_segment`
- `special_offer_flag`

#### Historical flow / maturity

- `lag_1_new_money_amount`
- `lag_3_new_money_mean`
- `lag_1_early_withdrawal_amount`
- `maturity_amount`
- `prior_rollover_rate_pct`

#### External context

- `bok_base_rate_pct`
- `sector_deposit_rate_pct`

#### Seasonality

- `month_sin`
- `month_cos`

### 3.3 명시적 금지

아래 contemporaneous outcome은 model feature로 사용하지 않는다.

- 현재 target 기간의 `new_money_amount`
- `rollover_amount`
- `end_balance`
- `early_withdrawal_amount`
- 기타 target/label/outcome field
- `future_*`

또한 고객명, 계좌번호, 주민번호, 전화번호, 이메일, 주소 등 direct PII는 금지한다.

`ftp_rate_pct`는 수신액 예측 feature가 아니라 **경제성/조달원가 평가축**으로 분리한다.

---

## 4. Candidate model ladder

모델은 처음부터 복잡한 ML을 우선하지 않는다.

### 4.1 Incumbent reference

`structural_v2_reference`

- 현재 공개 구조모델
- 학습모델 아님
- challenger가 실제로 더 나은지 비교하는 기준선
- β/γ가 내부실적으로 보정됐다고 간주하지 않음

### 4.2 Challenger 1 — 필수 첫 모델

`regularized_elasticity_v1`

목적:

- 금리변화
- 시장 대비 gap
- 만기구조
- 과거 수신 흐름
- 특판
- 외부 금리환경
- 계절성

이 실제 수신액과 어떤 관계를 갖는지 **해석 가능한 regularized response model**로 먼저 확인한다.

복잡한 비선형 모델보다 먼저 통과해야 하는 기본 challenger다.

### 4.3 Challenger 2 — Segment interaction

`segment_interaction_v1`

상품/기간/채널별로 금리민감도가 실제로 다를 경우에만 interaction을 허용한다.
표본이 부족한 segment를 무리하게 분리하지 않는다.

### 4.4 Challenger 3 — Nonlinear residual

`nonlinear_residual_v1`

- 최소 60개 관측일을 요구
- 해석 가능한 challenger가 놓치는 비선형 residual이 반복적으로 존재할 때만 검토
- 단순히 in-sample 적합도가 높다는 이유로 승격하지 않음

즉 모델 복잡도는:

```text
Structural reference
→ interpretable regularized challenger
→ segment interaction
→ nonlinear residual
```

순으로 올린다.

---

## 5. Time-based backtest

랜덤 train/test split은 사용하지 않는다.
금리와 수신액은 시간순 데이터이므로 미래를 과거 학습에 섞지 않는다.

기본 outer backtest:

- 최초 train: 24개 관측일
- OOS window: 3개 관측일
- 이후 expanding window
- 마지막 fold: `final_holdout`

36개 월 관측이 있다면:

```text
Fold 1: train 24 → test 3
Fold 2: train 27 → test 3
Fold 3: train 30 → test 3
Fold 4: train 33 → test 3  ← final holdout
```

따라서 기존 intake의 의미를 다음처럼 분리한다.

- 24개월: 자료 quality/intake 및 초기 연구 가능
- 36개월: champion promotion을 검토할 수 있는 권장 최소 history

Hyperparameter tuning은 각 fold의 **train window 내부에서만** 수행한다.
OOS window와 final holdout을 보고 tuning하지 않는다.

---

## 6. Target과 metric

### 6.1 예측 구성

최종 총수신을 하나의 black-box target으로만 맞추지 않는다.

- 신규수신
- 재예치
- 총수신 = 신규수신 + 재예치

구성요소를 함께 검증한다.

### 6.2 Primary metric

`total_wape`

총수신 규모에 대한 OOS 오차를 기본 primary metric으로 둔다.

### 6.3 Guardrail metrics

- `new_money_wape`
- `rollover_rate_mae_pp`
- `bias_ratio`
- `event_direction_accuracy`

예를 들어 총수신 오차만 좋아지고 재예치가 크게 망가지는 모델은 승격하지 않는다.

금리변경 이벤트에서 반응방향을 지속적으로 틀리는 모델도 승격하지 않는다.

---

## 7. Champion / Challenger promotion gate

현재 v1 governance default는 다음과 같다.

> 이 숫자들은 고려저축은행 데이터에서 추정된 통계적 임계값이 아니라 **사전 운영·검증 기준**이다. 실제 자료가 도착한 뒤 표본구조를 확인하면서 별도 근거를 가지고 조정할 수 있다.

### 필수 데이터 조건

- candidate별 최소 history 충족
- 일반 challenger promotion: 최소 36개 관측일
- nonlinear challenger: 최소 60개 관측일
- 최소 OOS fold 4개
- OOS pricing event 최소 6개

### Primary improvement

challenger `total_wape`가 incumbent 대비 최소 **5% 상대 개선**.

### Fold consistency

- 전체 fold 중 최소 75%에서 incumbent보다 개선
- 어느 한 fold에서도 incumbent 대비 10%를 넘는 catastrophic regression 금지
- final holdout은 반드시 incumbent보다 좋아야 함

### Component guardrail

- 신규수신 WAPE가 incumbent 대비 5% 이상 악화되면 차단
- 재예치율 MAE가 incumbent 대비 5% 이상 악화되면 차단
- absolute bias 5% 초과 차단
- 금리변경 이벤트 방향 정확도 55% 미만 차단

### 중요

Gate 통과 결과는:

`eligible_for_human_review`

이다.

아래가 아니다.

- auto promoted
- production champion
- 통계적으로 진실인 모델

실제 champion 교체는 별도 human review와 승인 후 private registry에서 수행한다.

### Promotion evidence identity

Promotion report는 점수만 담지 않는다. 아래 identity를 함께 담고 fail-closed 검증한다.

- `experiment_id`
- `model_artifact_sha256`
- `training_data_fingerprint_sha256`
- `feature_schema_sha256`

Champion activation에서는 report의 `version`, `candidate_key`, 위 네 identity와 registry row가
모두 정확히 일치해야 한다. 같은 candidate의 다른 실험 report를 digest만 다시 계산해 재사용할
수 없다.

---

## 8. 왜 aggregate metric 하나로 결정하지 않는가

예를 들어 전체 3년 평균에서는 challenger가 좋아도 마지막 3개월 금리환경에서 크게 무너질 수 있다.

또 총수신은 좋아졌지만:

- 신규수신은 크게 과대예측
- 재예치는 크게 과소예측

해서 우연히 합계만 맞을 수도 있다.

따라서 다음을 동시에 본다.

```text
전체 OOS 개선
+ fold consistency
+ final holdout
+ 신규수신 component
+ 재예치 component
+ bias
+ 실제 금리변경 event 방향
```

---

## 9. Leakage / privacy boundary

Public repository에는 다음을 넣지 않는다.

- 실제 내부 원본파일
- 내부 aggregate raw rows
- 실제 calibrated coefficient
- 실제 training diagnostics
- feature importance
- model artifact
- 고객/계좌 식별정보

Public repository가 갖는 것은 오직:

- feature 이름 계약
- 모델 후보 이름/역할
- split 생성 규칙
- metric 이름
- 승격 Gate
- synthetic unit tests

이다.

실제 학습은 local/confidential runtime에서 수행하고, 최종 public Strategy에는 기존 `inflow-public-forecast-v1` allowlist를 통과한 결과만 전달한다.

---

## 10. 이번 범위에서 하지 않는 것

- 실제 내부자료 mapping
- 실제 모델 fitting
- coefficient 생성
- β/γ 변경
- Public Structural v2 수식 변경
- Strategy UI 변경
- public forecast schema 확장
- FTP 수익성 모델 구현
- DB/schema/migration
- canonical 금리/source precedence 변경
- 자동 추천금리
- 자동 champion 교체

---

## 11. 내부자료 도착 후 실행 순서

1. 원본 파일은 public Git/GitHub 밖 private workspace에 저장
2. source-specific adapter 작성
3. E0 intake gate 통과
4. as-of feature table 생성 + leakage audit
5. `regularized_elasticity_v1`부터 fitting
6. expanding-window OOS backtest
7. 현재 structural reference와 동일 기간 비교
8. promotion gate 평가
9. 필요 시 segment challenger
10. 표본이 충분할 때만 nonlinear challenger
11. final holdout 확인
12. human review
13. champion 확정 후 private inference
14. public forecast allowlist adapter를 통해 Strategy 연결
15. 운영 후 drift/forecast error 지속 모니터링

---

## 12. Acceptance criteria

- feature allowlist / forbidden leakage field가 코드로 고정됨
- 36개 관측일 → 24+3 expanding OOS 4 folds가 deterministic하게 생성됨
- 마지막 fold는 final holdout으로 분리됨
- 후보 모델 ladder가 코드 계약으로 고정됨
- aggregate 개선만으로 승격되지 않음
- component regression / fold regression / final holdout 실패가 fail-closed됨
- 통과해도 auto promotion 없음
- promotion report가 exact experiment/model/data/schema evidence에 결합됨
- production data / internal data / coefficient / DB write 없음
- 기존 Public Structural / Strategy runtime 결과 불변
- Inflow Engine Contract CI + General CI 통과
