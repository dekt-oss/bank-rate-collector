# Stage E1A — 수신반응 예측엔진 분리와 공개 경계

- Date: 2026-08-21
- Repository: `dekt-oss/bank-rate-collector`
- Issue: #167
- Current model: `inflow-structural-v1`
- Production Strategy Release Gate: **OFF**

## 1. 결론

내부 수신실적은 Strategy 정적 화면이나 public GitHub repository에서 직접 관리하지 않는다.
현재 구조 예측엔진은 내부자료가 도착할 때까지 fallback/champion baseline으로 유지하고,
실제 calibration/training은 별도 confidential runtime에서 수행한다.

공개 Strategy가 confidential engine에서 받을 수 있는 것은 예측 결과값뿐이다.
원본 내부자료, source-specific column/schema, 학습계수, feature importance, 학습·검증
진단값, 데이터 파일명과 같은 provenance는 공개 경계를 통과할 수 없다.

이번 E1A는 이 경계를 코드 계약으로 먼저 강제한다. 실제 내부자료를 받거나 계수를
변경하지 않고, 현재 Strategy runtime도 변경하지 않는다.

## 2. Current State — 현재 수신금액은 어떻게 계산되는가

현재 `inflow_prediction_service.py`는 내부 실적 미보정 구조 예측엔진이다.

### 2.1 입력

- 최근 월 신규수신 기준금액 `B`
- 다음 만기도래금액 `M`
- 현재 재예치율 `p0`
- 현재 당사금리 `r0`
- 제안금리 `r1`
- 시장 TOP10 금리 `rm`
- 가입기간 `T`
- low/base/high 민감도 scenario

### 2.2 금리 변화 단위

```text
current_gap  = r0 - rm
proposed_gap = r1 - rm
relative_change = proposed_gap - current_gap
                = r1 - r0
rate_steps = relative_change / 0.10%p
```

중요한 한계가 있다. 동일 시점의 `rm`은 위 차분에서 상쇄된다. 현재 payload에는 시장
대비 gap이 audit 정보로 남지만, 예측 민감도 자체는 결과적으로 **당사 금리의 변화폭**에
반응한다. 시장 대비 현재 위치가 같은 +10bp라도 서로 다른 반응을 만들지는 않는다.

### 2.3 신규자금

```text
new_money_log_effect = beta * rate_steps
applied_effect = clamp(new_money_log_effect, -1.5, +1.5)
predicted_new_money = B * exp(applied_effect)
```

현재 base `beta=0.05`이므로 다른 조건이 같을 때 +10bp는 신규자금을 약 `exp(0.05)`,
즉 +5.13%로 움직이는 스트레스 가정이다. 이 수치는 내부 실적으로 추정한 탄력성이 아니다.

### 2.4 재예치

```text
logit(p1) = logit(p0) + gamma * rate_steps
predicted_rollover = M * p1
```

현재 base `gamma=0.08`이다. 예를 들어 현재 재예치율이 60%이면 +10bp 시 약 61.90%로
이동한다. 이것도 실제 관측자료로 추정한 확률효과가 아니라 미보정 스트레스 가정이다.

### 2.5 예상 총수신과 표면 이자비용

```text
baseline_total = B + M * p0
predicted_total = predicted_new_money + predicted_rollover
incremental_total = predicted_total - baseline_total

baseline_interest = baseline_total * r0 * (T / 12)
predicted_interest = predicted_total * r1 * (T / 12)
surface_interest_delta = predicted_interest - baseline_interest
```

현재 이자비용은 단순 표면금리 기준이다. FTP, 조달 대체효과, 중도해지, 기간별 실제
현금흐름을 통합한 ALM 비용함수는 아니다.

## 3. Current State의 예측 한계

현재 모델은 의사결정 UI와 수학적 방향성을 검증하기 위한 baseline으로는 유용하지만,
실제 수신액 예측모델로 보기에는 다음 제약이 있다.

| 영역 | 현재 | 고도화 목표 |
| --- | --- | --- |
| 가격 민감도 | low/base/high 고정 β·γ | 실제 history로 추정하고 시점별 안정성 검증 |
| 시장 위치 | TOP10 gap은 audit, 효과에서는 상쇄 | 경쟁금리 수준·변화·분포를 독립 feature로 반영 |
| 신규수신 | 단일 월 기준금액 × multiplier | 상품·기간·채널·계절성·시장상황 분리 |
| 재예치 | 단일 p0와 scenario γ | 만기 cohort/상품/기간/채널별 재예치율 추정 |
| 이벤트 | 직접 미반영 | 금리변경·특판·캠페인과 lag 반영 |
| 중도해지 | 직접 미반영 | runoff/early withdrawal 별도 추정 |
| 외부환경 | 설명자료 중심 | 기준금리·업권 수신·경쟁금리 history 정렬 |
| 불확실성 | low/high stress range | out-of-sample error 기반 prediction interval |
| 비용 | 단순 표면 이자비용 | FTP 포함 조달비용/목표 순수신 최적화 |

`MAX_ABS_NEW_MONEY_LOG_EFFECT=1.5`도 안전장치로 필요하지만 현재 실적 기반 cap은 아니다.
향후 실제 history에서 극단 구간의 오차와 안정성을 보고 다시 검증해야 한다.

## 4. Target Architecture — confidential engine과 public Strategy 분리

```text
[PUBLIC / bank-rate-collector]
시장 공시·외부 context + 사용자의 시나리오 입력
                    |
                    | forecast request
                    v
        [authenticated private boundary]
                    |
                    v
[CONFIDENTIAL RUNTIME / public repo 밖]
내부 원본
  -> source-specific mapping
  -> E0 canonical intake gate
  -> feature table / leakage audit
  -> time-based train + backtest
  -> champion / challenger registry
  -> private inference
                    |
                    | sanitized forecast result only
                    v
[PUBLIC Strategy]
제안금리별 예상 신규수신 / 재예치 / 총수신 / 비용 / 예측범위
```

### 4.1 public repository에 둘 수 있는 것

- 공개 forecast request/response contract
- 외부 시장 feature contract
- synthetic fixture/test
- 현재 미보정 structural fallback
- public payload privacy validator

### 4.2 confidential runtime에만 둘 것

- 실제 내부 Excel/CSV 원본과 변환 산출물
- source-specific sheet/column mapping
- 내부 상품/채널 식별 체계
- 실제 calibration coefficient와 parameter
- feature importance / model diagnostic / training log
- train/test row, sample size, private model registry metadata
- 내부자료의 존재·출처를 추론하게 할 수 있는 상세 provenance

실제 내부자료 또는 private calibration은 **public GitHub Actions에서 실행하지 않는다**.
현재 E0 intake service는 generic canonical contract와 synthetic test로만 public repo에 남긴다.
실제 source-specific mapping과 실데이터 실행은 confidential runtime의 책임이다.

## 5. Public Forecast Contract

공개 결과는 allowlist 방식으로만 통과시킨다. unknown field가 하나라도 있으면 삭제해서
계속 진행하지 않고 fail-closed로 거부한다. 이는 잘못 추가된 private diagnostic이 조용히
노출되는 것을 막기 위한 계약이다.

허용하는 top-level 의미는 다음으로 제한한다.

- 공개 contract version
- 생성시각
- 운영상태 `ready` / `unavailable`
- 공개 단위
- rate scenario별 sanitized prediction

scenario에는 제안금리와 예측 신규수신, 재예치, 총수신, 증분총수신, 단순 표면 이자비용
차이, 선택적 총수신 하·상단만 허용한다.

다음 표현과 필드는 public forecast payload에 넣지 않는다.

- `calibration_status`
- `coefficient`, `beta`, `gamma`
- `provenance`, `source`, `source_file`
- `feature_importance`, `training`, `train_*`, `test_*`
- raw/canonical internal dataset
- private model id, data fingerprint, calibration diagnostics

UI도 향후 private engine을 사용하더라도 `내부자료 보정`, `사내 실적 기반` 같은 provenance를
표시하지 않는다. 사용자에게 필요한 것은 입력 조건, 예측 결과, 범위, 비용과 의사결정
상태이며 학습자료의 출처가 아니다.

## 6. Stage E1B — 내부자료 수령 후 calibration 절차

실제 파일 형식을 본 뒤 confidential runtime에서 source-specific mapping을 만든다.
그 다음 E0 canonical gate를 통과한 자료에 대해서만 feature engineering과 calibration을
수행한다.

예측 정확도를 높이기 위해 후보 feature를 미리 고정하지 않는다. 실제 coverage를 먼저
감사하되 최소 검토축은 실제 적용금리, 경쟁금리의 수준과 변화, 상품·기간·채널,
만기·재예치, 중도해지, 금리변경·특판 event, 외부 수신시장 context다.

가격은 은행이 시장상황을 보고 결정하므로 `금리를 올린 뒤 수신이 늘었다`만으로 금리의
순수 효과라고 단정하면 내생성 문제가 생긴다. 따라서 시계열 순서를 보존하고 가격변경
전후, 시장동행, lag, 상품/기간 효과를 같이 검토한다.

## 7. Model Validation Gate

random train/test split은 사용하지 않는다. 미래를 예측하는 업무이므로 과거로 학습하고
그 이후 기간을 맞히는 rolling/expanding time split을 사용한다.

후보모델은 최소 다음 세 baseline과 비교한다.

| Baseline | 의미 |
| --- | --- |
| Naive | 직전/계절 기준 수준 예측 |
| Structural v1 | 현재 `inflow-structural-v1` |
| Simple segmented elasticity | 기간/상품 등 최소 segment별 단순 탄력성 |

신규수신과 재예치는 하나의 숫자로만 평가하지 않는다. 규모 오차(MAE/WAPE 계열),
방향성, 과대·과소 편향, 금리변경 구간 성능, 기간별 안정성을 함께 본다. 예측범위는
low/high 임의 stress가 아니라 holdout residual 또는 quantile/blocked bootstrap 등 실제
오차분포를 이용하는 방식을 우선 검토한다.

challenger가 out-of-sample에서 baseline을 안정적으로 이기지 못하면 기존 structural
engine을 유지한다. 모델이 복잡하다는 이유만으로 승격하지 않는다.

## 8. 후속 E2 — 금리결정 최적화

예측도가 충분히 검증된 뒤 다음 문제로 확장한다.

> 목표 순수신을 충족하는 후보 중 예상 조달비용이 가장 낮고 downside risk가 허용범위인
> 금리를 선택한다.

이 단계에서 FTP와 실제 조달비용, 순수신 정의, 기간별 목표, 한도, 마진/유동성 guardrail을
연결한다. E1의 예측 정확도 검증이 끝나기 전에는 E2 최적금리를 정답처럼 제시하지 않는다.

## 9. E1A Acceptance Criteria

- public forecast schema는 allowlist다.
- unknown top-level/scenario field는 fail-closed다.
- private coefficient/provenance/training metadata를 넣으면 거부된다.
- ready 결과의 예상 신규수신·재예치·총수신은 유한한 비음수 값이다.
- `predicted_total = predicted_new_money + predicted_rollover` 불변식을 검사한다.
- optional lower/upper interval은 둘 다 있어야 하고 `lower <= total <= upper`다.
- 현재 Strategy runtime, 기존 β·γ, DB/schema/collector는 변경하지 않는다.
- Production Strategy Release Gate는 OFF를 유지한다.

## 10. Rollback

E1A는 신규 contract module/document/test만 추가한다. runtime wiring이 없으므로 문제가 있으면
해당 파일을 revert하면 기존 Strategy 동작으로 완전히 복귀한다.
