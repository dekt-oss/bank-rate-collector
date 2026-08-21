# `inflow-structural-v1` Evidence Registry

- Date: 2026-08-22
- Issue: #167
- PR: #168
- Calculation guide: `docs/specs/20260822-inflow-structural-v1-calculation-guide.md`
- 목적: 현재 수신예측 엔진의 각 주장에 대해 **무엇이 저장소의 실제 사실인지, 무엇이 외부 문헌으로 뒷받침되는 방법론인지, 무엇이 아직 근거 없는 가정인지**를 분리해 관리한다.

---

# 1. Evidence 분류 규칙

이 프로젝트에서는 근거를 세 종류로 분리한다.

## A. Repository / executable evidence

현재 코드·테스트가 실제로 무엇을 계산하는지에 대한 Source of Truth다.

- 실제 공식
- 현재 계수
- 단위
- guardrail
- Python ↔ JavaScript parity
- 공개 payload 계약

이 영역은 외부 논문보다 현재 실행코드가 우선한다.

## B. External conceptual evidence

왜 금리민감도, 상대금리, log/logistic 구조, 시계열 검증 같은 접근을 검토할 수 있는지를 뒷받침한다.

**외부 문헌이 있다고 해서 현재 계수값 또는 현재 예상금액이 검증됐다는 뜻은 아니다.**

## C. Assumption / unverified

현재 시스템 운영을 위해 임시로 둔 값 또는 아직 검증되지 않은 주장이다.

이 영역은 `사실`, `실증계수`, `예측 정확도`로 표현하면 안 된다.

---

# 2. 현재 공식의 Repository Evidence

## R1. 구조모델 정의

**파일**

`src/rate_monitor/services/inflow_prediction_service.py`

**직접 확인되는 사실**

- model version = `inflow-structural-v1`
- calibration status = `uncalibrated`
- 10bp step = `0.10%p`
- 금액 단위 = `KRW_100M`
- 신규수신: `baseline * exp(clamped log effect)`
- 재예치: `logit(p0) + sensitivity * rate steps` → logistic inverse
- 총수신 = 예상 신규수신 + 예상 재예치
- 비용 = 현재/제안 총수신에 표면금리를 적용한 단순 이자차이
- low/base/high 계수는 `uncalibrated_stress_assumptions`

## R2. 현재 low/base/high 계수

현재 저장소에서 정의된 값:

| scenario | 신규수신 log 변화 / 10bp | 재예치 log-odds 변화 / 10bp |
| --- | ---: | ---: |
| low | 0.02 | 0.04 |
| base | 0.05 | 0.08 |
| high | 0.10 | 0.16 |

### Evidence 상태

**C — unverified assumption**

이 숫자들은 고려저축은행 내부실적에서 추정된 값이 아니다.
현재까지 확인한 외부 근거 중 이 네 수치 또는 이 세 band를 직접 정당화하는 자료도 없다.

따라서 문서와 UI에서 다음 표현을 금지한다.

- `업계 표준 계수`
- `고려저축은행 추정계수`
- `통계적으로 검증된 민감도`
- `BASE가 가장 가능성 높은 민감도`

## R3. 시장 TOP10 상쇄

코드의 현재 계산:

```text
current_gap  = current_own_rate - market_top10_rate
proposed_gap = proposed_rate - market_top10_rate
relative_change = proposed_gap - current_gap
```

대수적으로:

```text
relative_change
= (proposed - top10) - (current - top10)
= proposed - current
```

### Evidence 상태

**A — executable/algebraic fact**

외부 문헌의 해석이 아니라 현재 코드 자체에서 직접 도출된다.
시장 TOP10 gap은 현재/제안 위치를 표시하는 감사정보에는 남지만 현재 금리민감도에는 독립 feature로 작용하지 않는다.

## R4. 회귀 테스트

`tests/test_inflow_prediction_service.py`

검증하는 핵심 계약:

- 금리변화 0 → 기준 신규수신·재예치 보존
- +10bp → 신규수신·재예치 증가
- 금리인하 → 반대 방향
- TOP10 gap 감사값과 상대금리 step
- 신규수신 log effect guardrail
- 재예치 0~100% 경계
- 단순 표면이자비용
- 가입기간 단위
- 비정상 금융입력 fail-closed

## R5. Python ↔ Strategy JavaScript parity

`tests/test_inflow_prediction_parity.py`

현재 Strategy 브라우저 계산과 Python 구조모델이 golden vector 기준으로 같은 결과를 내는지 검증한다.

이 테스트는 **구현 일치성**을 검증한다. 실제 수신액에 대한 **예측 정확도**를 검증하는 테스트는 아니다.

---

# 3. External Evidence Matrix

아래 외부 출처는 현재 모델의 특정 **개념**을 뒷받침한다. 각 항목에는 반드시 `Supports`와 `Does NOT support`를 같이 기록한다.

---

## E1. 은행별 예금수요는 자기 은행 금리와 시장/평균 금리의 상대적 위치에 반응할 수 있다

### Source

Federal Reserve Board, **Sticky Deposit Rates**, FEDS 2013-80, John C. Driscoll & Ruth A. Judson.

https://www.federalreserve.gov/Pubs/feds/2013/201380/index.html

### Relevant evidence

논문은 deposit rate가 market/federal funds rate 변화에 느리고 비대칭적으로 반응함을 장기간·다수 지점 자료로 분석한다. 또한 예금금리의 시장금리 조정속도와 이질성을 실증한다.

### Supports

- 예금 관련 금리행동은 시장금리 환경과 무관한 상수가 아님
- 시점·상품·은행별 금리 반응의 이질성을 향후 모델에서 검토해야 함
- 단일 고정계수만으로 모든 환경을 설명하는 것은 강한 가정임

### Does NOT support

- 현재 `β_NM = 0.05`
- 현재 `γ_RR = 0.08`
- +10bp → 신규수신 +5.13%
- 현재 exponential 신규수신 공식을 이 논문이 직접 검증했다는 주장

---

## E2. 예금자는 deposit rate와 비가격 은행특성에 반응한다

### Source

Federal Reserve Board, **Demand Estimation and Consumer Welfare in the Banking Industry**, Astrid A. Dick, FEDS 2002-58.

https://www.federalreserve.gov/econres/feds/demand-estimation-and-consumer-welfare-in-the-banking-industry.htm

### Relevant evidence

상업은행 예금서비스에 대한 structural demand model을 추정하며, 소비자의 금융기관 선택이 deposit rate뿐 아니라 수수료, 지점 밀도, 은행 규모·특성 등에 반응함을 보고한다.

### Supports

- 예금수요에 금리(price)가 중요한 설명변수라는 방향
- 금리 하나만으로 고객행동 전체를 설명하기보다 상품/채널/은행 특성 등을 함께 검토할 필요
- discrete-choice/logit 계열 접근이 예금서비스 선택 연구에서 실제 사용된 전례

### Does NOT support

- 현재 재예치식의 `γ_RR=0.08`
- 현재 신규수신·재예치 정의가 최적이라는 주장
- 고려저축은행 고객이 미국 상업은행 표본과 같은 민감도를 가진다는 주장

---

## E3. 절대금리보다 상대 수익률 차이가 실제 자금이동에 중요할 수 있다

### Source

Federal Reserve Board, **What Drives the Substitution Between Bank Deposits and Money Market Funds?**, FEDS Notes, 2025-11-06.

https://www.federalreserve.gov/econres/notes/feds-notes/what-drives-the-substitution-between-bank-deposits-and-money-market-funds-20251106.html

### Relevant evidence

은행예금과 MMF 사이의 자금이동에서 **relative yield differentials**가 흐름의 방향과 크기에 유의한 영향을 미친다고 보고한다.

### Supports

- 향후 calibrated engine에서 `당사금리 - 경쟁/대체상품 금리` 같은 상대가격 feature를 독립적으로 검증할 근거
- 현재 TOP10이 대수적으로 상쇄되는 구조를 개선 후보로 보는 논리

### Does NOT support

- `시장 TOP10 평균`이 반드시 최적 benchmark라는 주장
- 국내 저축은행 정기예금에 동일한 계수를 그대로 적용할 수 있다는 주장

---

## E4. `deposit beta`의 통상적 의미는 현재 신규수신 β와 다르다

### Source

Federal Reserve Board, **March 2024 Senior Financial Officer Survey Results**, Part 3: Deposit Rates.

https://www.federalreserve.gov/data/sfos/march-2024-senior-financial-officer-survey.htm

### Relevant evidence

Federal Reserve survey는 `deposit beta`를 정책금리 변화에 대한 은행 평균 예금금리의 basis-point 변화 비율로 정의한다.

### Supports

현재 코드의 신규수신 계수를 단순히 `deposit beta`라고 부르면 은행 ALM/금리담당자에게 다른 개념으로 해석될 위험이 있다는 판단.

### Naming rule

- 현재 `new_money_log_change_per_10bp` → 문서상 `신규수신 금리민감도`, `β_NM`
- 현재 `rollover_log_odds_change_per_10bp` → `재예치 금리민감도`, `γ_RR`
- `deposit beta`라는 표현은 정책/시장금리 → 예금금리 pass-through를 뜻할 때만 사용

### Does NOT support

Federal Reserve가 현재 수신금액 예측공식에 `β_NM`을 사용한다는 뜻이 아니다.

---

## E5. 예금의 금리민감도와 안정성은 고정불변이 아닐 수 있다

### Source

Basel Committee on Banking Supervision / BIS, **Literature review on non-maturity deposit stability: Established factors and recent developments**, Working Paper 47.

https://www.bis.org/bcbs/publ/wp47.pdf

### Relevant evidence

문헌검토는 예금행동에 다양한 요인이 작용하며 일부 영향강도가 시간에 따라 달라질 수 있음을 정리한다. 또한 rate sensitivity와 deposit beta를 예금행동 분석의 주요 개념으로 다룬다.

### Supports

- 하나의 고정 민감도 계수를 모든 기간에 영구 적용하지 말아야 할 가능성
- 향후 model stability, regime, segment별 민감도 검증 필요
- 실제 내부자료가 오면 시점별 안정성 검사를 해야 한다는 방향

### Does NOT support

- 현재 저/기준/고 계수의 값
- 정기예금 신규수신액에 현재 exponential 식을 그대로 써야 한다는 결론

---

## E6. 재예치율처럼 0~1 범위의 확률에는 logit/logistic 구조가 수학적으로 적합한 선택지다

### Source

Penn State STAT 501, **Weighted Least Squares & Logistic Regressions**.

https://online.stat.psu.edu/stat501/Lesson13

보조 출처:

Penn State STAT 504, **Binary Logistic Regression**.

https://online.stat.psu.edu/stat504/Lesson06

### Relevant evidence

logistic regression은 log-odds를 선형 predictor와 연결하고 inverse logistic을 통해 예측확률이 항상 0~1 범위에 있도록 한다.

### Supports

- 재예치율처럼 확률로 해석되는 값을 선형식으로 직접 밀어 100% 초과/0% 미만을 만들지 않기 위해 logistic link를 쓰는 수학적 이유
- `logit(p)` → predictor effect → logistic inverse라는 현재 계산구조의 일반적 통계 원리

### Does NOT support

- 현재 `γ_RR=0.08`
- 재예치가 오직 금리변화 하나로 결정된다는 가정
- 현재 aggregate 재예치율을 계좌단위 binary logistic regression과 동일한 실증모형으로 볼 수 있다는 주장

> 현재 엔진은 logistic **함수형태를 차용한 시나리오 계산**이며 실제 계좌단위 likelihood로 γ를 추정한 logistic regression은 아니다.

---

## E7. log-link/exponential 구조는 양(+)의 규모를 곱셈형으로 움직이는 일반적 모델링 구조다

### Source

Penn State STAT 504, GLM section in **Binary Logistic Regression**, Poisson Regression summary.

https://online.stat.psu.edu/stat504/Lesson06

### Relevant evidence

GLM에서 log link는 `log(mean) = linear predictor` 형태를 사용하며 inverse link는 exponential이므로 양의 기대값과 곱셈형 효과를 만든다.

### Supports

현재 신규수신의

```text
log change = sensitivity × rate step
amount = baseline × exp(log change)
```

구조가 수학적으로 어떤 의미인지 설명하는 일반적 근거.

### Does NOT support

- 신규수신 금액이 Poisson 분포라는 주장
- 현재 모델이 GLM으로 통계추정됐다는 주장
- `β_NM=0.05`라는 숫자

> 현재 구조모델은 **log-link 아이디어를 시나리오 multiplier에 사용**할 뿐, 아직 실제 데이터로 GLM을 fit한 모델이 아니다.

---

## E8. 향후 calibrated engine의 검증은 시간순서를 보존해야 한다

### Source

scikit-learn, **TimeSeriesSplit** documentation.

https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html

보조 출처:

Hyndman & Athanasopoulos, **Forecasting: Principles and Practice — Time series cross-validation**.

https://otexts.com/fpp3/tscv.html

### Relevant evidence

시간순 데이터에서는 일반적인 무작위 CV가 미래 데이터를 과거 학습에 섞을 수 있으므로, 이전 기간을 train으로 하고 이후 기간을 test로 하는 split을 사용해야 한다는 원칙.

### Supports

향후 내부실적 기반 challenger를 만들 때:

- random shuffle 금지
- 과거 → 미래 순서의 rolling/expanding validation
- 실제 미래예측 오차를 기준으로 champion/challenger 평가

### Does NOT support

- 현재 structural v1이 검증됐다는 주장
- 특정 모델(XGBoost, GLM 등)이 반드시 우월하다는 주장

---

# 4. Claim-to-Evidence 요약표

| Claim | 상태 | 근거 |
| --- | --- | --- |
| 현재 공식이 코드에 구현되어 있다 | **확인됨** | R1 |
| low/base/high 계수가 0.02/0.05/0.10, 0.04/0.08/0.16이다 | **확인됨** | R2 코드 |
| 그 계수들이 실제 은행실적으로 추정됐다 | **거짓 / 근거 없음** | R2 |
| +10bp BASE 신규수신은 수학상 +5.13%다 | **확인됨** | `exp(0.05)` |
| +10bp 실제 신규수신이 +5.13%일 것이다 | **미검증** | 내부 calibration 필요 |
| 재예치 확률을 logistic으로 제한하는 것은 수학적으로 설명 가능하다 | **근거 있음** | E6 |
| 실제 재예치 γ=0.08이 맞다 | **미검증** | 내부 calibration 필요 |
| 예금행동은 금리와 관련된다 | **외부 실증근거 있음** | E1, E2 |
| 상대금리/대체수익률 gap이 자금이동에 중요할 수 있다 | **외부 실증근거 있음** | E3 |
| 현재 모델이 시장 TOP10 수준을 수신민감도에 직접 반영한다 | **아님** | R3 |
| `β_NM`을 deposit beta라고 불러도 된다 | **권장하지 않음** | E4 |
| 현재 low/high 범위가 95% prediction interval이다 | **아님** | 현재는 stress range |
| 실제 예측모델 승격은 미래기간 holdout으로 검증해야 한다 | **방법론 근거 있음** | E8 |

---

# 5. 외부 근거 사용 규칙

## 5.1 문헌을 현재 계수의 출처로 둔갑시키지 않는다

예:

잘못된 표현:

```text
Federal Reserve 연구를 근거로 +10bp당 신규수신 +5.13%를 적용했다.
```

올바른 표현:

```text
외부 연구는 예금수요와 금리·상대금리 사이의 관계를 모델링할 근거를 제공한다.
현재 +5.13%는 외부 연구의 추정치가 아니라 β_NM=0.05라는 미보정 가정의 수학적 결과다.
```

## 5.2 해외 문헌을 국내 저축은행 계수로 직접 이전하지 않는다

미국·유럽 은행 자료는 **모델링 방향과 변수 후보의 근거**로 사용한다.
고려저축은행의 실제 탄력성·재예치 민감도는 자체 history에서 별도로 추정해야 한다.

## 5.3 모델 설명과 모델 검증을 구분한다

- `왜 exponential/logistic을 썼는가` → 함수구조 설명
- `그 함수가 실제 수신액을 잘 맞히는가` → out-of-sample 검증 문제

함수 형태를 설명할 수 있다고 해서 예측 정확도가 확보된 것은 아니다.

---

# 6. Maintenance Rule

다음 변경이 생기면 이 Evidence Registry도 같은 PR에서 갱신한다.

- 새로운 외부 feature 도입
- 민감도 계수 calibration
- 함수형태 변경
- 신규 모델 도입
- champion/challenger 승격
- prediction interval 도입
- deposit beta 또는 유사 용어 사용

새 외부 출처를 추가할 때는 항상 다음 네 항목을 기록한다.

1. Source title / institution / date / URL
2. Relevant evidence
3. Supports
4. Does NOT support

이를 통해 “논문이 있으니 우리 숫자도 맞다”는 식의 근거 확장을 금지한다.
