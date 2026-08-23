# Public Structural v2 Stage H — Provider Adapter

```yaml
document_type: implementation_contract
status: implementation/current-work
date: 2026-08-23
issue: 169
parent_issue: 167
base_main: 9bb409bc9c8f0ae9aa79ac190dde6c9531526f85
stage: H
production_strategy_release_gate: unchanged_off
internal_data: prohibited_in_public_repo
```

## 1. 목적

Stage H는 현재 Public Structural provider와 향후 confidential calibrated provider가 **같은 sanitized public forecast shape**를 통해 같은 Decision Surface/Cockpit을 사용하게 만드는 provider adapter를 추가한다.

이번 Stage는 private endpoint, private model, 내부자료, 내부계수, training diagnostic을 구현하거나 public repo에 반입하는 단계가 아니다.

## 2. Source of Truth

- `docs/specs/20260822-public-structural-v2-decision-cockpit-final.md`
- `src/rate_monitor/services/inflow_public_forecast_contract.py`
- `inflow-public-forecast-v1` allowlist
- Stage C~G의 sanitized Decision Surface / Cockpit 계약

## 3. 현재 문제

현재 Python/JS Decision Surface는 Public Structural forecast builder를 직접 호출한다.

```text
Decision Surface
  -> build_public_structural_v2_forecast / buildPublicForecast
  -> Public Structural inflow engine
```

따라서 결과 shape는 이미 sanitized이지만 provider 선택과 Decision Surface 생성이 결합돼 있다.

Target:

```text
Forecast Request
  -> Provider Adapter
       -> current Public Structural provider
       -> future confidential provider (이번 Stage에서는 미구현)
  -> inflow-public-forecast-v1 validator
  -> Decision Surface
  -> Cockpit
```

## 4. Public Forecast Request

Provider에 넘기는 public request는 다음 계산 입력만 가진다.

- `generated_at`
- `candidate_rates`
- `baseline_new_money`
- `maturity_amount`
- `current_rollover_rate_pct`
- `current_own_rate`
- `term_months`

Provider identity, coefficient, source file, feature/training metadata는 request/view model에 넣지 않는다.

향후 confidential provider가 추가 private feature를 필요로 하면 그 feature 결합은 provider 내부/private runtime에서 해결한다. public request 계약을 private feature carrier로 확장하지 않는다.

## 5. Adapter 계약

### 5.1 Python canonical

새 adapter는 callable provider가 반환한 payload를 `validate_public_forecast_payload()`로 **그대로 fail-closed 검증**한다.

- unknown field를 제거해 통과시키지 않음
- `private_model`, `training_metric`, `feature_importance`, `source_file`, `sample_size` 등 allowlist 밖 필드가 있으면 실패
- `ready` payload의 scenario rate axis는 request의 `candidate_rates`와 정확히 일치해야 함
- duplicate/missing/extra rate는 실패
- provider가 명시적인 `ProviderUnavailable`을 반환/발생시키면 strict `status=unavailable`, `scenarios=[]` payload로 변환
- 임의 Exception은 unavailable로 숨기지 않고 실패시켜 구현 결함을 드러냄

### 5.2 Current structural provider

현재 Public Structural v2는 adapter 구현체 중 하나로 감싼다.

계수/공식은 변경하지 않는다.

```text
StructuralProvider(request)
  -> existing build_public_structural_v2_forecast(...)
  -> adapter validator
```

### 5.3 Future confidential provider

이번 PR에서는 interface/contract만 준비한다.

금지:

- private endpoint URL
- auth secret
- private model id
- 실제 내부 coefficient
- training date/sample/metric
- internal feature names
- private repository/path

## 6. Decision Surface

Decision Surface는 provider implementation을 직접 알지 않는다.

Python은 optional provider dependency를 받아 adapter를 통해 forecast를 얻고, provider를 주지 않으면 current structural provider를 사용한다.

반환 shape는 기존 `public-structural-v2-decision-surface-v1`을 유지한다.

즉 Cockpit이 소비하는 `surface.forecast`는 provider가 바뀌어도 항상 `inflow-public-forecast-v1`이다.

## 7. Browser / JS adapter

브라우저도 provider adapter를 둔다.

- current structural provider factory는 기존 `decision_contract.js + inflow_engine.js`를 내부에서 사용
- Cockpit orchestration은 raw coefficient field를 읽지 않고 provider factory에 config 객체를 opaque하게 전달
- adapter는 sync/async provider 둘 다 `Promise.resolve()`로 수용해 향후 server endpoint provider로 교체 가능하게 한다
- provider result는 public allowlist + candidate rate axis를 fail-closed 검증한 뒤 Surface에 attach

Decision Surface rendering, chart/table, marginal logic은 provider identity를 읽지 않는다.

## 8. Unavailable semantics

Provider unavailable은 오류를 forecast 숫자로 대체하지 않는다.

```json
{
  "version": "inflow-public-forecast-v1",
  "generated_at": "...",
  "status": "unavailable",
  "amount_unit": "KRW_100M",
  "rate_unit": "percent",
  "scenarios": []
}
```

Stage H에서는 current structural provider가 정상 동작하므로 production Cockpit의 정상 경로는 계속 `ready`다.

향후 unavailable UI 개선이 필요하면 별도 presentation 변경으로 처리한다.

## 9. 테스트 / Evidence Gate

필수:

1. structural provider 결과가 기존 Python 결과와 exact shape parity
2. sanitized arbitrary provider 결과가 같은 Decision Surface `forecast` slot에 연결됨
3. unknown top-level private metadata reject
4. unknown scenario private metadata reject
5. missing/extra/duplicate candidate rate reject
6. explicit unavailable provider -> strict unavailable payload
7. arbitrary runtime Exception은 unavailable로 숨기지 않음
8. Python ↔ JS structural provider parity
9. JS async provider 수용
10. deliberate private-field leak probe reject
11. existing Stage A0~G targeted tests green
12. production-derived Strategy Chrome smoke regression green
13. Release Gate unchanged

## 10. Non-goals

- private endpoint/inference deployment
- auth/network transport
- internal calibration
- coefficient 변경
- prediction/confidence interval 의미 변경
- recommendation/optimal/probability output
- DB/schema/migration/collector/source precedence/stable product identity 변경
- Production Strategy Release Gate ON

## 11. 완료 기준

- [ ] Decision Surface가 current structural builder에 직접 결합되지 않음
- [ ] current structural provider가 adapter 뒤에서 기존 수치 유지
- [ ] future provider가 sanitized payload만으로 같은 Surface에 연결 가능
- [ ] private metadata leak fail-closed
- [ ] candidate rate axis drift fail-closed
- [ ] browser orchestration이 provider result만 Surface에 attach
- [ ] Python/JS parity green
- [ ] production-derived desktop/mobile regression green
- [ ] Release Gate OFF
