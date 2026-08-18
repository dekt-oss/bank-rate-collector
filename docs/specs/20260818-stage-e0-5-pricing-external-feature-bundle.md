# Stage E0-5 — Deposit Pricing External Feature Bundle

- Date: 2026-08-18
- Base: `main` (`f81e40e1c8704d0b924803b1d45eec29e531d506`)
- Related: Issue #108
- Production Strategy Release Gate: **OFF 유지**

## 목표

Stage E v1이 사용할 외부 macro control을 하나의 read-only 계약으로 묶는다.
새 수집원을 추가하지 않고 이미 검증된 두 source를 재사용한다.

```text
bok_ecos
→ 한국은행 기준금리

bok_ecos_macro
→ 예금은행 신규취급액 수신금리
→ 비은행 업권 월말 수신잔액 / 연속월 MoM
```

## v1 feature roles

- 기준금리: monetary-policy regime control
- 순수저축성예금 신규취급액 금리: bank deposit-market realized price control
- 1년 정기예금 신규취급액 금리: 12M competition anchor
- 업권 수신잔액 MoM: sector liquidity-flow control

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

이 bundle은 Stage E calibration code의 외부 입력 계약이다.
내부 실적자료가 오기 전에는 현재 uncalibrated inflow coefficient를 이 값으로
재학습하지 않는다.

내부자료가 확보되면:

```text
internal performance features
+ current market/Stage C features
+ this external macro bundle
→ calibration dataset
→ time-based validation
→ calibrated inflow / rollover model
```

로 연결한다.
