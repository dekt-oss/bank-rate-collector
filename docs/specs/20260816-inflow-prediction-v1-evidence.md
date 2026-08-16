# 수신금액 예측엔진 v1 — 근거와 가정 경계

```yaml
document_type: evidence_note
status: experimental
created_at: 2026-08-16
model_version: inflow-structural-v1
calibration_status: uncalibrated
```

## 결론

이 엔진 전체가 Federal Reserve, New York Fed, 한국은행이 발표한 하나의 공식
예측식인 것은 아니다.

외부 연구에서 근거를 가져오는 부분과 이 프로젝트가 선택한 통계적 함수형태,
그리고 아직 실적으로 추정하지 않은 스트레스 계수를 분리한다.

| 구성요소 | 현재 엔진 적용 | 근거의 성격 |
| --- | --- | --- |
| 상대 예금금리와 수신 선택 | 시장 대비 금리 위치를 전략 변수로 사용 | Fed 예금수요 연구 |
| 금리 변화와 deposit flow | 금리 변경에 따라 신규수신이 움직이는 방향성 | NY Fed 실증 연구 |
| 국내 비은행 수신경쟁 | 저축은행을 포함한 비은행 수신경쟁 해석 | 한국은행 분석 |
| 신규자금 exponential/log-link | 금액 예측이 음수가 되지 않도록 함 | 프로젝트 통계 모형 선택 |
| 재예치 logistic link | 재예치율이 0~100% 확률 범위를 벗어나지 않도록 함 | 프로젝트 통계 모형 선택 |
| 저·기준·고 β/γ | 불확실성을 범위로 표시 | 미보정 스트레스 가정 |

## 1. 상대금리와 예금수요

Federal Reserve FEDS의 *Sticky Deposit Rates*는 개별 은행의 예금금리가 시장의
평균 예금금리보다 높거나 낮을 때 은행의 예금 시장점유율이 변하는 형태의
예금수요함수를 사용한다.

이 엔진은 여기서 **절대금리만 보지 않고 시장 대비 상대금리 위치를 함께 본다**는
경제적 구조를 참고한다.

출처:
- Federal Reserve Board, FEDS 2013-80, *Sticky Deposit Rates*
- https://www.federalreserve.gov/pubs/feds/2013/201380/index.html

## 2. 금리와 deposit flow 민감도

New York Fed의 2025년 분석은 은행의 예금금리 변화에 예금 flow가 얼마나
반응하는지 추정하며, 그 민감도가 시기에 따라 크게 달라질 수 있음을 보인다.

이 엔진은 여기서 **금리 변경이 신규수신 flow에 영향을 준다는 방향성**과
**한 개의 고정 민감도를 정답처럼 사용하지 않아야 한다는 점**을 참고한다.

출처:
- Federal Reserve Bank of New York, Liberty Street Economics,
  *The Rise in Deposit Flightiness and Its Implications for Financial Stability*
- https://libertystreeteconomics.newyorkfed.org/2025/07/
  the-rise-in-deposit-flightiness-and-its-implications-for-financial-stability/

## 3. 국내 비은행 수신경쟁

한국은행 BOK 이슈노트 2023-33은 은행권의 수신 확대에 대응해 저축은행 등
비은행권이 예금금리를 빠르게 높이며 수신을 확보한 시기의 행태를 분석한다.

이 엔진은 이를 **한국의 저축은행 수신도 경쟁기관 금리와 분리해 볼 수 없다는
국내 시장 근거**로 사용한다.

출처:
- 한국은행 BOK 이슈노트 제2023-33호,
  *예금취급기관의 예금조달행태 변화 및 정책적 시사점*
- https://www.bok.or.kr/portal/bbs/P0002353/view.do?menuNo=200433&nttId=10081072

## 4. 외부 연구에서 직접 가져오지 않은 부분

### 신규자금 exponential/log-link

현재 신규자금 식의 `exp()`는 특정 중앙은행 논문의 계수를 복사한 것이 아니다.
예측 금액이 음수가 되지 않도록 하기 위한 프로젝트의 함수형태 선택이다.

### 재예치 logistic link

현재 재예치율의 logistic 식도 특정 저축은행의 공식 재예치 모형이 아니다.
확률값을 0~100% 범위 안에서 다루기 위한 프로젝트의 함수형태 선택이다.

### β·γ 민감도

현재 저민감·기준·고민감의 β·γ 값은 외부 논문에서 가져온 업계 평균도 아니고,
고려저축은행 실적으로 추정한 값도 아니다. 모델 동작과 의사결정 범위를 보기 위한
**미보정 스트레스 가정**이다.

따라서 UI와 payload는 `uncalibrated` 상태를 유지한다.

## 5. calibrated 전환 조건

다음 내부 실적을 확보하고 시장금리 history와 같은 기준일로 연결한 뒤,
out-of-sample 검증에서 안정적인 계수를 확인해야 `calibrated`로 바꿀 수 있다.

- 상품·가입기간별 실제 신규취급액
- 실제 적용 또는 대표금리
- 만기도래액
- 재예치액 또는 재예치율
- 가입채널
- 특판·캠페인 여부
- 가능하면 신규계좌수와 중도해지액

그 전까지 이 엔진은 **연구 근거가 있는 구조 + 미보정 민감도 시나리오**로 해석한다.
