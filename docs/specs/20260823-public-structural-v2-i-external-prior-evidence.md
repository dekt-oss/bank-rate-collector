# Public Structural v2 Stage I — External Prior Evidence Gate

```yaml
document_type: research_contract
status: implementation/current-work
date: 2026-08-23
issue: 169
parent_issue: 167
base_main: 0546e9d3f11df2f5d32e4dd50e433f66874b8f47
stage: I
coefficient_change: prohibited_without_identifying_evidence
production_strategy_release_gate: unchanged_off
internal_data: prohibited_in_public_repo
```

## 1. 연구 질문

> 공개 업권/거시 시계열만으로 현재 Public Structural v2의 임의 stress range 크기에
> 은행별 수신반응 계수로 사용할 수 있을 정도의 근거를 줄 수 있는가?

Stage I는 **계수 튜닝 단계가 아니다.** 공개 집계 시계열에서 관찰 가능한 시간순서,
시차, regime, 표본길이와 기술적 association을 점검하고, 그 결과가 현재
`uncalibrated_stress_assumptions`의 계수 변경을 허용할 수 있는지 Evidence Gate로
판정한다.

`NO-GO`는 실패가 아니라 정상적인 연구결과다.

## 2. Source of Truth

- `docs/specs/20260822-public-structural-v2-decision-cockpit-final.md`
- `src/rate_monitor/services/public_structural_v2_inflow_service.py`
- `src/rate_monitor/collectors/bok_ecos/macro_parser.py`
- `src/rate_monitor/services/strategy_external_context_service.py`
- `src/rate_monitor/services/deposit_pricing_external_feature_service.py`
- `src/rate_monitor/services/market_intelligence_service.py`

현재 Public Structural v2의 coefficient provenance는 계속
`uncalibrated_stress_assumptions`이다.

## 3. 공개자료 범위

### 3.1 한국은행 ECOS — repo에 이미 수집 중

`bok_ecos_macro`의 48개월 월별 계약을 그대로 사용한다.

금리:

- 예금은행 순수저축성예금금리(신규취급액)
- 예금은행 저축성수신금리(신규취급액)
- 예금은행 1년 정기예금금리(신규취급액)

수신잔액:

- 상호저축은행
- 신용협동조합
- 광의 상호금융
- 새마을금고

별도 `bok_ecos` 기준금리는 가능한 월말 시점에 carry-forward하여 coverage context로만
사용한다.

`광의 상호금융`은 농협·수협·산림조합 단위조합을 포함하므로 `nh_local`과 1:1로
매핑하지 않는다.

### 3.2 repo 시장금리 history

`collection_runs`의 공개 원천 수집 이력은 **기간 coverage 진단**에만 사용한다.

Stage I에서 짧은 repo history를 장기 은행별 flow calibration 표본으로 확대해석하지
않는다. 상품별 raw row나 내부자료를 evidence artifact로 반출하지 않는다.

## 4. 외부 공개근거 검토

한국은행의 공개자료는 다음을 뒷받침한다.

1. 금융기관 가중평균금리 통계는 예금은행의 신규취급액 기준 저축성수신금리 같은
   **시장/업권 집계 금리**를 제공한다.
   - https://www.bok.or.kr/portal/bbs/B0000501/view.do?menuNo=201264&nttId=11062275
2. 한국은행 통화정책 파급경로 설명은 기준금리가 예금·대출금리에 영향을 주지만,
   파급경로가 길고 복잡하며 경제상황에 따라 달라져 영향과 시차의 정확한 측정이
   어렵다고 명시한다.
   - https://www.bok.or.kr/eng/main/contents.do?menuNo=400024
3. BOK 이슈노트 2023-33은 2022~2023년 예금경쟁 국면에서 은행의 수신확대와
   비은행권 예금금리 인상·자금이동이 함께 나타났음을 분석한다. 이는 **경쟁 및
   regime context가 중요함**을 지지하지만 특정 은행의 +10bp가 신규자금 또는
   재예치율을 얼마만큼 바꾸는지 식별하는 연구가 아니다.
   - https://www.bok.or.kr/portal/bbs/P0002353/view.do?menuNo=200433&nttId=10081072
4. 한국은행 금융경제연구 제434호는 정책금리 변화에 대한 은행 예대금리 조정의
   비대칭성을 분석한다. 따라서 하나의 고정 coefficient를 모든 금리국면에 기계적으로
   외삽하는 것은 추가 식별 없이 정당화하기 어렵다.
   - https://www.bok.or.kr/portal/bbs/P0002455/view.do?menuNo=500788&nttId=163178

이 공개연구는 **시장금리·경쟁·regime의 관련성**에는 근거를 주지만, 현재 구조모형의
`new_money_log_change_per_10bp` 또는 `rollover_log_odds_change_per_10bp`를 은행별로
보정할 직접 근거는 제공하지 않는다.

## 5. 분석 계약

### 5.1 월별 변화량

금리 signal:

```text
rate_change_bp[t] = (rate[t] - rate[t-1]) * 100
```

업권 수신잔액:

```text
balance_growth_pct[t] = (balance[t] / balance[t-1] - 1) * 100
```

연속 월이 아닌 구간은 변화량을 만들지 않는다.

### 5.2 time-order / lag

각 balance outcome month `t`에 대해 금리 signal을 다음과 같이 정렬한다.

```text
lag 0: rate_change[t]   ↔ balance_growth[t]
lag 1: rate_change[t-1] ↔ balance_growth[t]
lag 2: rate_change[t-2] ↔ balance_growth[t]
lag 3: rate_change[t-3] ↔ balance_growth[t]
```

미래 금리를 과거 balance outcome에 연결하지 않는다.

### 5.3 association

표본이 너무 적은 correlation 숫자를 노출하지 않기 위해 최소 8개 pair가 있을 때만
Pearson/Spearman을 계산한다.

이 8은 통계적 유의수준이나 coefficient 채택 기준이 아니라 **퇴화한 소표본
기술통계를 숨기기 위한 표시 Gate**다.

모든 association의 의미는 고정한다.

```text
descriptive_association_not_causal
```

### 5.4 chronological stability screen

표본을 시간순서로 절반 분할하고 각 절반에 최소 6개 pair가 있을 때만 두 구간의
Pearson 부호를 비교한다.

이 역시 OOS 예측성능 검증이 아니다.

### 5.5 aggregate temporal OOS feasibility screen

공개 집계시계열에 최소:

- 앞 24개월
- 뒤 12개월

의 비중첩 시간구간을 만들 수 있는지만 표시한다.

이는 **aggregate context의 시간분할 가능성**일 뿐 은행별 coefficient의 OOS 검증이
아니다. 24+12개월이 확보되어도 아래 identification Gate를 통과하지 못하면 계수는
변경하지 않는다.

### 5.6 regime

주요 예금은행 수신금리의 월변화 부호를 그대로 사용한다.

- rising: `> 0`
- flat: `= 0`
- falling: `< 0`

임의의 1bp tolerance로 regime을 다시 정의하지 않는다.
각 regime에서 업권 balance growth의 표본수와 median만 기술한다.

## 6. Identification Gate

현재 공개자료에는 다음이 없다.

- 고려저축은행 개별 신규유입액
- 고려저축은행 만기도래액 대비 실제 재예치율의 장기 시계열
- 당사 금리변경 이벤트와 고객유입을 연결한 bank-specific panel/event data
- 고객/상품 mix control
- 캠페인·채널·특판·영업정책 control
- 경쟁사 동시 금리변경에 대한 충분한 식별전략

반면 관찰되는 것은 예금은행 집계금리와 업권 전체 수신잔액이다.

따라서 aggregate association이 크고 시간분할에서 같은 부호를 보여도 다음 변환은
금지한다.

```text
aggregate correlation
  != bank-specific new-money elasticity
  != bank-specific rollover elasticity
  != causal +10bp response
```

## 7. Stage I Gate 결과 계약

Stage I public source contract만으로는 coefficient 변경을 허용하지 않는다.

```yaml
coefficient_change: NO_GO
public_prior_role: context_only_not_parameter_calibration
stress_range_status: retain_uncalibrated_stress_assumptions
blocking_reasons:
  - aggregate_series_do_not_identify_bank_specific_new_money_or_rollover_response
  - no_bank_specific_new_money_rollover_decomposition_in_public_sources
  - causal_identification_not_established_by_descriptive_time_series
```

실제 production-derived 공개 시계열의 coverage/association/regime 결과는 CI artifact로
생성하고 이 문서에 최종 evidence를 추가한다.

## 8. 보안 / 공개 경계

허용:

- BOK 공개 시계열의 월별 aggregate diagnostics
- 공개 원천 수집 이력의 시작/종료/월수 같은 coverage
- correlation 및 regime 기술통계
- NO-GO 사유

금지:

- 실제 내부 실적 데이터
- private model / coefficient / feature name
- training row / diagnostics
- 내부 source mapping
- confidential repository/path
- aggregate association을 β/γ로 변환한 값

## 9. Verification Gate

- targeted Ruff
- targeted pytest
- production DB snapshot은 runner-local read-only 분석
- migrations는 local copy에만 적용
- evidence JSON/Markdown artifact 생성
- artifact에 raw 상품행/내부자료 없음
- `coefficient_change == NO_GO` assertion
- Public Structural v2의 `CALIBRATION_STATUS == uncalibrated` 유지 확인
- General CI baseline debt와 Stage I diff 분리 보고
- adversarial self-review

## 10. Non-goals

- coefficient 변경
- stress range 축소/확대
- private calibration
- UI 변경
- collector/source contract 변경
- DB/schema/migration 변경
- 추천금리/최적금리/달성확률 생성
- Production Strategy Release Gate 변경
