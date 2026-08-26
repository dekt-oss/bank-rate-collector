# Stage E0-5 — Deposit Pricing External Feature Bundle

- Date: 2026-08-18
- Base: `main` (`f81e40e1c8704d0b924803b1d45eec29e531d506`)
- Related: Issue #108
- Production Strategy Release Gate: **OFF 유지**

## 목표

Stage E의 외부 macro 근거와 향후 calibration 입력 후보를 하나의 read-only 계약으로 묶는다.
새 수집원을 추가하지 않고 이미 검증된 두 source를 재사용한다.

> **v1 모델 사용 범위:** 이 bundle은 현재 Strategy의 근거/표시용 context이며 향후
> calibration dataset의 입력 후보다. 현재 `inflow_prediction_service`의 미보정
> inflow/rollover 예측식과 coefficient에는 policy rate나 아래 macro feature를
> 투입하지 않는다. `feature_roles`의 `control`/`anchor` 명칭은 분석상 의도된 역할을
> 설명하며, 현재 모델에 이미 통제변수로 적용됐다는 뜻이 아니다.

```text
bok_ecos
→ 한국은행 기준금리

bok_ecos_macro
→ 예금은행 신규취급액 수신금리
→ 비은행 업권 월말 수신잔액 / 연속월 MoM
```

## v1 feature roles

아래 role은 **현재 coefficient 적용 상태가 아니라 향후 calibration에서 검토할 분석 역할**이다.

- 기준금리: monetary-policy regime control
- 순수저축성예금 신규취급액 금리: bank deposit-market realized price control
- 1년 정기예금 신규취급액 금리: 12M competition anchor
- 업권 수신잔액 MoM: sector liquidity-flow control

현재 public inflow prediction은 이 bundle을 입력으로 받지 않는다. 따라서 외부 feature 값이
바뀌더라도 현행 `inflow_prediction_service`의 계산값이나 coefficient는 이 단계에서 변하지 않는다.

## 명시적 제외

아래는 v1 feature에 포함하지 않는다.

- bank bond rate
- CD rate
- COFIX

현재 관측 중인 시중은행 상품금리와 중복설명 가능성이 있고 모델 복잡도를 먼저
늘릴 이유가 없다는 사용자/설계 결정이다. 향후 out-of-sample 개선 evidence가 있을
때만 재검토한다.

## fail-closed

- `market_indicators` 없음 → `schema_unavailable`
- 기존 `bok_ecos`의 valid `bok_base_rate` 없음 → policy `no_data`
- source/unit/date 계약 불일치 → `source_contract_mismatch`
- macro context 일부 부재 → aggregate `partial`
- missing을 0으로 대체하지 않는다.

## 다음 단계

이 bundle은 Stage E calibration code가 사용할 수 있도록 미리 고정한 외부 입력 계약이다.
내부 실적자료가 오기 전에는 현재 uncalibrated inflow coefficient를 이 값으로
재학습하거나 현재 예측식에 직접 투입하지 않는다.

내부자료가 확보되면:

```text
internal performance features
+ current market/Stage C features
+ this external macro bundle
→ calibration dataset
→ time-based validation
→ calibrated inflow / rollover model
```

로 연결한다. 실제 모델 투입은 calibration 설계·검증을 거친 별도 단계에서만 수행한다.
