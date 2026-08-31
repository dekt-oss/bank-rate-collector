# Claude 리뷰 요청 — 상대금리 기반 목표형 금리결정 시뮬레이터

아래 블록을 Claude Code/Claude 리뷰 세션에 그대로 전달한다.

---

## 리뷰어에게 보내는 프롬프트

`dekt-oss/bank-rate-collector` 저장소의 **설계 문서 리뷰만** 진행해주세요.
코드 수정이나 구현은 하지 마세요.

대상 브랜치:

`docs/relative-rate-goal-simulator-20260831`

먼저 원격 브랜치의 최신 HEAD를 직접 확인하고, 리뷰 첫 줄에 실제 확인한 commit SHA를 적어주세요. 로컬에 남아 있는 오래된 브랜치나 문서를 기준으로 리뷰하지 마세요.

### 1. 반드시 먼저 읽을 것

저장소 지침과 현재 기준:

1. `AGENTS.md`
2. `CLAUDE.md`
3. `README.md`
4. `docs/specs/CURRENT.md`

이번 리뷰 대상:

5. `docs/plans/20260831-relative-rate-goal-simulator-plan.md`
6. `docs/plans/20260831-relative-rate-goal-simulator-work-order.md`

기존 상위/관련 계약:

7. `docs/specs/20260818-deposit-pricing-decision-cockpit-v3.md`
8. `docs/specs/20260822-public-structural-v2-decision-cockpit-final.md`
9. `docs/specs/20260825-private-inflow-calibration-protocol-v1.md`
10. `docs/specs/20260818-internal-deposit-data-request-v1.md`

최소한 아래 현재 코드도 대조해주세요.

- `src/rate_monitor/services/public_structural_v2_market_position_service.py`
- `src/rate_monitor/services/inflow_prediction_service.py`
- `src/rate_monitor/services/public_structural_v2_decision_contract.py`
- `src/rate_monitor/services/inflow_asof_feature_contract.py`
- `src/rate_monitor/services/inflow_calibration_protocol.py`
- `src/rate_monitor/services/inflow_backtest_evaluation.py`
- `src/rate_monitor/services/inflow_private_model_registry_contract.py`
- `src/rate_monitor/services/institution_funding_direct_peer.py`
- `src/rate_monitor/services/institution_funding_direct_peer_db.py`
- `src/rate_monitor/services/institution_funding_position_service.py`
- `src/rate_monitor/services/institution_funding_strategy_payload.py`
- `src/rate_monitor/services/rate_funding_matrix_service.py`
- `src/rate_monitor/services/strategy_contract_service.py`
- `src/rate_monitor/services/strategy_decision_cockpit.py`
- `src/rate_monitor/services/strategy_external_context_service.py`
- `src/rate_monitor/services/strategy_service_base.py`
- `src/rate_monitor/services/site_service.py`

필요하면 관련 테스트, migration, 최신 PR/Issue/Actions/runtime evidence까지 확인하세요. 문서의 현재상태 설명이 실제 코드·production data와 맞는지도 검증해주세요.

### 2. 리뷰 목적

이번 설계의 핵심 전환은 다음입니다.

기존 질문:

> 금리를 3.5%로 하면 수신이 얼마나 바뀌는가?

장기 목표 질문:

> 목표 수신액/순수신을 일정 기간 안에 확보하려면 현재 경쟁시장 대비 어느 금리 범위가 필요한가?

그리고 금리를 움직일 때:

- 주요 경쟁사의 금리
- Direct Peer 대비 당사 위치
- 경쟁사 수신잔액/증감
- 금리 변경으로 새로 앞서거나 뒤처지는 경쟁사
- 비용
- 내부모형 보정 후에는 예상 수신
- 과거의 비슷한 **상대금리** 상황

을 한 화면에서 함께 보려는 기획입니다.

하지만 현재 public 데이터만으로는 당사 수신반응을 검증할 수 없으므로 설계는 반드시:

```text
현재 = factual Relative Market Simulator
향후 private calibrated champion 승인 후 = Goal-based inverse simulator
```

로 분리되어야 합니다.

### 3. 리뷰 태도

**이 설계가 틀렸다고 가정하고 반박해주세요.**

문서에 쓰인 표현을 그대로 받아들이지 말고 실제 코드·데이터 계약·시점·identity·runtime을 근거로 검증해주세요.

특히 금융 의사결정 화면이므로 `그럴듯하지만 검증되지 않은 숫자`가 생길 가능성을 가장 엄격하게 보세요.

### 4. 반드시 답할 질문

#### A. 제품/의사결정 구조

1. `절대금리`보다 `Direct Peer 대비 상대금리`를 중심축으로 두는 방향이 실제 금리결정 지원 UX로 적절한가?
2. 최종 UX를 `목표 수신 → 필요 금리 범위 → What-if`로 뒤집는 것이 현재 cockpit 구조와 충돌하거나 빠뜨리는 의사결정 단계가 있는가?
3. Rate × Funding Matrix를 주인공이 아니라 보조근거로 내리는 판단이 합리적인가?

#### B. Public / Private 경계

4. 이번 기획이 `20260822-public-structural-v2-decision-cockpit-final.md`의 **목표 수신 → 자동 최소금리 금지** 계약을 실제로 지키는가?
5. 현재 uncalibrated stress model이 화면상 forecast/recommendation처럼 오독될 여지가 남아 있는가?
6. R3 private calibrated champion이 되기 전에 R4 inverse solver가 켜질 우회경로가 없는가?

#### C. Relative Market Contract

7. `peer median gap`, 공동순위, tie, ±5/10bp crowding, threshold crossing만으로 상대시장 위치를 충분히 설명하는가?
8. 시장 전체 universe와 Direct Peer universe를 분리하는 계약이 명확한가?
9. 경쟁사 수신잔액을 합산해 보여줄 때 coverage가 일부만 있는 경우 사용자가 전체 금액으로 오독하지 않도록 계약이 충분한가?
10. `missing funding != 0`, `exact identity only`가 모든 경로에서 fail-closed 되는가?

#### D. Direct Peer

11. 현재 `sigungu → sido → nationwide` + log-balance distance 정책을 가격경쟁 peer에도 그대로 재사용해도 되는가, 아니면 funding peer와 pricing peer를 분리해야 하는가?
12. NH N=16은 유지하되 저축은행에 복사하지 않는 방향이 맞는가?
13. peer policy에 `policy_id/version/as_of` 외에 반드시 추가해야 할 재현성 필드가 있는가?
14. 기관규모가 바뀌는 경우 Historical Peer Snapshot을 어떻게 재현해야 look-ahead bias를 피할 수 있는가?

#### E. Historical Analogue

15. 과거 `당사 금리 3.5%`가 아니라 `당시 peer 대비 위치가 비슷했던 기간`을 찾는 방식이 논리적으로 맞는가?
16. 현재 peer 집합을 과거에 복사하지 않고 point-in-time peer를 재선정하는 규칙이 충분히 엄격한가?
17. historical rate raw/evidence가 없는 경우 `historical_rate_unavailable`로 멈추는 Gate에 빠진 예외가 있는가?
18. 현재금리 carry-back, nearest-month interpolation, 미래 funding 규모 사용 등 temporal leakage 가능성을 찾아주세요.

#### F. Goal-based inverse simulator

19. `검증된 forward model → candidate grid → inverse solver` 순서가 맞는가?
20. 목표가 training/support 범위를 벗어났을 때 단순 외삽을 막는 Gate가 충분한가?
21. 금리와 수신 반응이 단조(monotonic)하지 않을 수 있는데, feasible range를 어떻게 정의해야 안전한가?
22. 하나의 `추천금리`가 아니라 범위+불확실성을 주는 계약이 충분한가?
23. 추가금리 비용과 추가수신의 한계효율을 보여주려면 어떤 검증이 더 필요한가?

#### G. 현재 데이터 readiness

24. 저축은행 `source 79 / Strategy exact 66`을 R1 전 선행 Gate로 둔 것이 맞는가? 실제 최신 runtime에서도 이 설명이 맞는지 확인해주세요.
25. 과거의 저축은행 약 2배 합산 문제는 aggregate sector row 제거로 이미 해결된 상태인지, 작업지시서가 이를 다시 문제처럼 오해하지 않는지 검증해주세요.
26. NH current rate/funding은 준비됐지만 historical aligned rate가 없다는 설명이 최신 production과 맞는가?
27. 신협 institution funding은 exact official endpoint 미확정으로 canonical unavailable이라는 설명이 맞는가?

#### H. 구현 경계/아키텍처

28. 제안한 R0→R4 순서가 실제 dependency 순서와 맞는가?
29. 새 서비스/테이블을 만들기 전에 기존 서비스로 흡수해야 할 부분이 있는가?
30. 반대로 기존 서비스에 억지로 넣으면 책임이 섞이는 부분은 무엇인가?
31. Historical Peer Snapshot은 DB persistence가 필요한가, 아니면 versioned deterministic recomputation으로 충분한가?
32. schema/API/persistent contract 변경이 필요하다면 어떤 migration/compatibility 계획이 작업지시서에 빠져 있는가?
33. Strategy build/presentation 계층에서 어느 payload contract를 확장하는 것이 최소변경인가?

### 5. 특별히 찾아야 할 위험

다음 유형을 적극적으로 찾아주세요.

- look-ahead bias
- survivorship bias
- 기관 합병/명칭변경으로 인한 historical identity 오류
- current peer를 historical peer로 잘못 사용하는 문제
- rate/funding as-of mismatch
- missing funding을 사실상 0처럼 처리하는 UI
- coverage 60% 합계를 전체 peer 합계처럼 보이는 UI
- median 기준만으로 대형 경쟁사의 영향력을 잃는 문제
- Direct Peer 선택이 금리 자체를 사용해 circular해지는 문제
- 같은 기관의 여러 상품이 peer rank에 과대표집되는 문제
- 상품/기관 단위가 섞이는 문제
- public stress 결과가 실제 예측으로 보이는 문제
- inverse solver가 OOS extrapolation을 추천하는 문제
- internal raw data가 public repo/artifact/log에 노출되는 문제
- 모델 버전과 peer-policy 버전이 분리되지 않아 재현이 안 되는 문제

### 6. 답변 형식

다음 순서로 주세요.

#### 1) 최종 판정

둘 중 하나만:

- `APPROVE FOR IMPLEMENTATION PLANNING`
- `CHANGES REQUIRED`

아직 코드 구현 승인이 아니라 **설계/작업지시서가 구현 단계로 넘어갈 품질인지**에 대한 판정입니다.

#### 2) 핵심 결론

5~10줄 이내.

#### 3) Findings

심각도 순:

- `P0` — 잘못된 금융 판단/데이터 오염/계약 위반 가능성
- `P1` — 구현 전에 고쳐야 할 설계 결함
- `P2` — 품질/명확성 개선

각 finding마다 반드시:

```text
근거 파일/섹션
현재 문제
왜 위험한가
정확한 수정 제안
```

을 적어주세요.

#### 4) 기존 spec/code와의 충돌

없으면 `없음`이라고 명시.

#### 5) 빠진 Acceptance Criteria / Evidence Gate

구현 전 추가할 항목을 구체적으로 써주세요.

#### 6) 권장 구현 순서

현재 R0~R4를 유지할지, 바꾼다면 왜 바꾸는지 제안해주세요.

#### 7) 문서 수정안

가능하면 추상적인 조언 말고 **어느 문서의 어느 절을 어떤 문장/계약으로 바꿀지** 제안해주세요.

#### 8) 사용자에게 정말 필요한 결정사항

기술적으로 저장소 증거로 결정할 수 없는 것만 질문해주세요. 저장소를 더 보면 답할 수 있는 것을 사용자에게 되묻지 마세요.

### 7. 금지사항

- 코드를 수정하지 마세요.
- PR/merge 하지 마세요.
- 내부 데이터가 있다고 가정하지 마세요.
- 현재 production에서 검증하지 않은 상태를 `완료`로 표현하지 마세요.
- 이름이 비슷하다는 이유로 기관 mapping을 제안하지 마세요.
- 인과관계를 데이터에 없는 상태에서 단정하지 마세요.
