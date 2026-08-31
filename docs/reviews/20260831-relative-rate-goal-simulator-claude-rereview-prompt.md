# Claude 재리뷰 요청 — 상대금리 기반 목표형 금리결정 시뮬레이터 v2

아래 블록을 그대로 Claude에 전달한다.

---

## 리뷰어에게 보내는 프롬프트

`dekt-oss/bank-rate-collector`의 상대금리 기반 목표형 금리결정 시뮬레이터 **v2 설계만 재리뷰**해주세요. 코드 구현은 하지 마세요.

대상 브랜치:

`docs/relative-rate-goal-simulator-20260831`

먼저 GitHub 원격에서 브랜치 HEAD와 main HEAD를 직접 확인하고 리뷰 첫 부분에 적으세요. 로컬 stale checkout을 기준으로 판단하지 마세요.

### 반드시 읽을 것

- `AGENTS.md`
- `docs/plans/20260831-relative-rate-goal-simulator-plan-v2.md`
- `docs/plans/20260831-relative-rate-goal-simulator-work-order-v2.md`
- `docs/reviews/20260831-relative-rate-goal-simulator-claude-review-response.md`
- `docs/evidence/20260831-savings-bank-funding-identity-coverage.md`
- `docs/specs/20260822-public-structural-v2-decision-cockpit-final.md`
- `docs/specs/20260825-private-inflow-calibration-protocol-v1.md`
- `docs/specs/20260818-internal-deposit-data-request-v1.md`

그리고 관련 source/test/workflow를 직접 대조하세요.

특히:

- `.github/workflows/collect.yml`
- `.github/workflows/collect-savings-fast.yml`
- `src/rate_monitor/services/public_structural_v2_market_position_service.py`
- `src/rate_monitor/services/inflow_prediction_service.py`
- `src/rate_monitor/services/institution_funding_direct_peer.py`
- `src/rate_monitor/services/institution_funding_direct_peer_db.py`
- `src/rate_monitor/services/inflow_calibration_protocol.py`
- `src/rate_monitor/services/inflow_asof_feature_contract.py`
- `src/rate_monitor/services/inflow_backtest_evaluation.py`
- `src/rate_monitor/services/inflow_private_model_registry_contract.py`
- `src/rate_monitor/services/rate_funding_matrix_service.py`
- `.gitignore`

### 이번 재리뷰에서 확인할 핵심

이전 리뷰의 P0 4건이 **문구만 바뀐 것이 아니라 구현자가 오해할 수 없을 정도로 계약이 수정됐는지** 확인하세요.

#### 1. Production surface

v2는 Strategy를 `on_canonical_site_writer` production surface로 취급합니다.

- OFF라는 과거 서술이 남아 있지 않은가?
- R1 public 변경의 verification 수준이 production exposure에 맞는가?

#### 2. Factual cost

R1 cost는 다음 순수 arithmetic으로 분리했습니다.

`notional × (proposal-current)/100 × term/12`

- `predicted_total` 또는 uncalibrated sensitivity 경로가 다시 들어올 여지가 없는가?
- `100억원당` 표준화 + optional user notional이 factual 표현으로 충분한가?
- `한계조달원가` 기존 금지와 충돌하지 않는가?

#### 3. Funding peer / pricing peer 분리

v2는:

- 기존 Direct Peer = funding peer
- 신규 pricing peer = valid rate 기준 institution peer
- funding = optional enrichment

로 나눴습니다.

확인:

- funding missing 기관이 pricing peer에서 사라지지 않는가?
- coverage contract가 실제 selection bias를 드러내는가?
- 기존 `institution_funding_direct_peer*` 책임이 오염되지 않는가?

#### 4. Product / institution key 분리

v2는 기존 product-level market position을 유지하고 신규 institution-level pricing position을 별도 모듈로 둡니다.

확인:

- 기존 product contract를 깨지 않는가?
- institution representative rate 축약이 결정론적인가?
- 동일 institution 다상품 과대표집이 pricing peer에서 차단되는가?
- market_* / peer_* 의미가 명확히 분리되는가?

### 이전 P1/P2 반영 확인

다음도 각각 확인하세요.

- public R1/R2 DOM에 목표입력 자체가 없음
- peer feature는 기존 market feature와 별도 이름
- monotonicity gate를 기존 기능처럼 오기하지 않고 R4 신규 산출물로 정의
- internal raw/private data의 git/artifact 기계적 방어가 R3 선행 작업으로 잡힘
- historical region current-value carry-back 금지
- historical peer는 versioned deterministic recomputation 기본
- 합병/명칭변경 중복계상 방지 테스트 포함
- product/term/channel/special-offer scope mismatch 후보 제외

### 79/66 evidence 재검토

이번 v2에는 다음 evidence 문서가 추가됐습니다.

`docs/evidence/20260831-savings-bank-funding-identity-coverage.md`

문서가 인용한 GitHub Actions run/artifact를 가능하면 직접 확인해서 다음을 독립 검증하세요.

- 2026-03 savings bank institution_count 79
- mapped_count 66
- unmapped_count 13
- institution total 99,573,991 million KRW
- ECOS total 99,574,000 million KRW
- reconciliation aligned

증거를 직접 확인할 수 없으면 `미검증`으로 표시하고 읽은 척하지 마세요.

### 사용자 정책 6건

v2는 다음을 아직 `proposed` 또는 evidence-gated로 둡니다.

1. institution 대표금리: matched scope 내 max rate, 특판 별도 radar
2. factual cost: 100억원당 + optional user notional
3. pricing peer 범위: 기관 소재지가 아니라 상품 availability/join scope
4. 신협: pricing peer 유지 + funding 자료없음
5. 목표입력 UI: R4 promoted champion 이후
6. 저축은행 peer N: remediation/calibration 전 미정

이 6건에 대해 **기술적으로 위험한 기본안이 있는지만** 판단하세요. 사용자 영업정책을 임의 확정하지 마세요.

### 파일 경계 평가

v2는 신규 책임을 다음처럼 분리합니다.

- `institution_rate_reduction.py`
- `pricing_peer_selection.py`
- `pricing_peer_position.py`
- `surface_cost_contract.py`
- 추후 `goal_rate_inverse_solver.py`

다음 관점으로 평가하세요.

- 기존 모듈에 넣는 편이 더 맞는 것이 있는가?
- 반대로 여전히 책임이 섞인 곳이 있는가?
- persistent schema 변경 없이 시작 가능한가?
- R1에서 불필요한 DB migration을 유도하지 않는가?

### 판정

둘 중 하나만 사용하세요.

`APPROVE FOR IMPLEMENTATION PLANNING`

또는

`CHANGES REQUIRED`

### 답변 형식

1. 확인한 branch HEAD / main HEAD
2. 판정
3. 핵심 결론 5~10줄
4. P0 / P1 / P2 Findings
   - 파일/절 근거
   - 위험
   - 정확한 수정안
5. 이전 리뷰 P0 4건 각각 `RESOLVED / PARTIAL / NOT RESOLVED`
6. 79/66 evidence 검증 결과
7. 신규 설계의 hidden coupling / look-ahead / selection bias 점검
8. 구현 전 반드시 추가할 Acceptance Criteria가 있으면 제시
9. 사용자 정책 6건에 대한 기술적 권고
10. 최종 구현 순서가 R0-A~R4로 안전한지 판정

코드, PR, merge는 하지 마세요. 검증하지 못한 것은 반드시 미검증이라고 적으세요.
