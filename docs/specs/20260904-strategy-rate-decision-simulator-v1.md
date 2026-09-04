# Strategy Rate Decision Simulator v1

작성: 2026-09-04  
상태: **IMPLEMENTATION LOCKED**  
브랜치: `feat/strategy-dashboard-simulator-redesign-20260904`

> 이 문서는 Strategy 금리결정 시뮬레이터 재설계의 구현 기준이다. 구현 중 요구사항이 바뀌거나 새 금융 계산 의미가 필요해지면 코드보다 이 문서를 먼저 수정한다.

## 1. 목적

현재 Strategy 시뮬레이터는 금리결정에 필요한 사실, 미보정 수신 시나리오, 모델 근거, 후보금리 표, Market Position Ladder를 한 화면에 동시에 노출해 정보밀도가 지나치게 높다.

v1의 목표는 저축은행 수신상품 담당자가 다음 질문에 빠르게 답하도록 화면을 재구성하는 것이다.

1. **금리를 X%로 정하면 현재 구조 시나리오에서 수신액이 어떻게 달라지는가?**
2. **목표 수신액 Y를 놓고 보면 어느 후보금리부터 검토해야 하는가?**
3. **그 금리는 현재 시장에서 어느 위치이며, 그 주변에 어떤 경쟁상품이 있는가?**
4. **공식 pricing peer와, 규모가 비슷한 경쟁기관은 누구인가?**
5. **과거 당사에서 비슷한 금리를 사용한 사례와 당시 시장 위치·실적 근거가 있는가?**

핵심 원칙은 **모델 구조를 설명하는 화면이 아니라 금리결정 순서대로 근거를 보여주는 화면**이다.

---

## 2. 선행 계약과 관계

관련 선행 문서:

- `docs/plans/20260831-relative-rate-goal-simulator-work-order-v2.md`
- Public Structural v2 market position / surface / marginal contracts
- Relative Pricing R1 factual peer contract
- 기존 Strategy source precedence / stable product identity / dedupe / historical alignment 계약

### 2.1 R4 inverse solver와 명확히 분리

이 v1의 `목표금액으로 찾기`는 **R4 inverse solver가 아니다.**

금지:

- R4 inverse API 호출
- champion promotion gate 우회
- calibration이 없는 상태에서 `필요금리`, `최적금리`, `추천금리`, `달성확률`로 표현
- 임의 보간(interpolation)
- 범위 밖 외삽(extrapolation)
- existing surface에 없는 금리 생성

허용:

- 기존 Public Structural v2가 이미 계산한 **forward candidate surface**를 사용
- 사용자가 입력한 목표 총수신 이상이 되는 **기존 후보 중 가장 낮은 금리점**을 찾음
- 결과를 `미보정 구조 시나리오의 첫 검토금리`로 표현

따라서 20260831 문서의 R4 promotion/champion 규칙은 그대로 유지한다. 본 문서는 기존의 public target input 금지 범위 중 **bounded structural scenario finder UI**에 대해서만 명시적으로 예외를 추가하며, calibrated inverse/recommendation 의미는 추가하지 않는다.

이 구분을 코드/카피에서 보존할 수 없으면 목표금액 모드는 **fail closed** 한다.

---

## 3. 현재 상태와 문제

### 3.1 현재 메인 화면의 문제

현재 Cockpit은 한 번에 다음을 노출한다.

- 제안금리 / 실제 시장위치 / 미보정 구조 시나리오
- Market Position Ladder
- Response Surface
- 5bp 후보금리 비교표
- stress range / marginal surface cost
- 계산식 / 민감도 / 근거

이 중 다수는 검증·분석 상세로는 유용하지만 1차 의사결정에는 과밀하다.

### 3.2 Market Position Ladder 문제

현재 Ladder는 `시장 최고`, `TOP10`, `TOP25`, `중앙값`, `현재`, `제안`을 전체 min/max 축에 동시에 놓는다. 시장 최고가 6%이고 실무 판단 구간이 3.2~3.7%처럼 좁으면 중요한 marker가 하단에 압축되어 실질적으로 읽기 어렵다.

**v1 결정:** Market Position Ladder를 primary surface에서 제거한다. 시장 위치는 rank / percentile / threshold를 직접 보여주는 compact position card/strip으로 대체한다. Ladder가 필요하면 향후 상세 분석용으로만 재도입한다.

### 3.3 데이터 가용성

현재 확인된 factual contract:

- 전체 상품시장 현재 위치: 사용 가능
- 공식 pricing peer: 사용 가능
- pricing peer의 수신잔액 / 6M 증감 / rate/funding 기준일: 사용 가능
- Public Structural v2 forward surface: 사용 가능, 단 **미보정**
- 총자산: 현재 확인된 Strategy / Relative Pricing public payload에서 표준 필드 계약을 확인하지 못함
- 과거 당사 금리: 일부 historical foundation 존재
- 과거 당사 특정 상품의 당시 전체시장 snapshot + 판매액/신규수신/재예치: production 의사결정 surface에 완전히 연결되지 않음

없는 값은 0으로 처리하지 않는다. 근거가 없으면 `자료 미연동`, `근거 없음`, `비교 불가`로 표시한다.

---

## 4. 정보구조

Primary 화면의 순서는 아래로 고정한다.

### 4.1 Header

제목: `금리결정 시뮬레이터`

짧은 설명: `검토금리 또는 목표 수신액을 기준으로 시장 위치·경쟁사·미보정 수신 시나리오를 한 번에 비교합니다.`

항상 노출하는 안전 라벨:

`내부 실적 미보정 · 구조 시나리오`

### 4.2 Mode tabs

두 모드만 primary control로 둔다.

1. **금리로 계산**
2. **목표금액으로 찾기**

모드 변경 시 동일한 market scope / term / own anchor / scenario input 계약을 공유한다.

---

## 5. Mode A — 금리로 계산

### 5.1 입력

- 검토금리 (%)
- 기존 기본금리 + 우대금리 입력과 동기화하거나 동일 canonical proposal rate를 사용
- 최근 월 신규수신 기준액
- 다음 만기도래액
- 현재 재예치율

### 5.2 Primary 결과

다음만 크게 보여준다.

1. `검토금리`
2. `예상 총수신 · 구조 시나리오`
3. `stress range`
4. `현재 대비 총수신 변화`
5. `전체 상품시장 위치`
6. `TOP10 / TOP25 / 중앙값과의 관계`

`예상`은 항상 미보정 구조 시나리오라는 문맥 안에서만 사용한다.

### 5.3 금리비용

표면이자비용은 보조 지표로 유지하되 FTP/ALM 경제원가와 혼동하지 않는다.

---

## 6. Mode B — 목표금액으로 찾기

### 6.1 입력

- 목표 총수신액(억원)
- 최근 월 신규수신 기준액
- 다음 만기도래액
- 현재 재예치율

### 6.2 solver 의미

입력 목표 `T`에 대해 기존 forward surface 후보를 금리 오름차순으로 정렬한 뒤:

`predicted_total >= T`

를 만족하는 **첫 existing candidate**를 반환한다.

반드시 지킬 것:

- candidate grid 밖 금리 생성 금지
- interpolation 금지
- extrapolation 금지
- surface 자체가 비어 있으면 계산 금지
- 입력 3개 중 하나라도 없으면 계산 금지
- 목표가 surface 최대값보다 크면 out-of-support
- 목표가 surface 최소값보다 작으면 가장 낮은 existing candidate가 반환될 수 있으나 `목표 이하로도 충분한 구조 시나리오`임을 명시

### 6.3 표시명

허용:

- `첫 검토금리`
- `목표 이상이 되는 첫 후보금리`
- `미보정 구조 시나리오 금리`

금지:

- `추천금리`
- `최적금리`
- `필요금리`
- `정답금리`
- `달성확률`

### 6.4 out-of-support

문구:

`현재 구조 시나리오 범위에서는 목표금액을 만족하는 금리 후보를 찾을 수 없습니다.`

이 경우 rate를 임의로 만들어 표시하지 않는다.

---

## 7. 시장 위치 — Ladder 대체

Primary 화면에서는 Market Position Ladder를 제거하고 `시장 위치` 카드/strip을 사용한다.

필수 정보:

- 검토금리
- 공동순위 범위 / 전체 비교상품 수
- 가능하면 상위 비율(percentile/quantile 표현은 기존 rank contract에서 deterministic하게 계산)
- TOP10 진입선
- TOP25 진입선
- 시장 중앙값
- 현재 당사금리

시장 최고금리는 보조 정보로만 표시한다. 하나의 극단값 때문에 의사결정 구간이 시각적으로 압축되지 않게 한다.

---

## 8. 현재 금리 주변 경쟁상품

사용자가 선택한 검토금리 주변의 **실제 현재 상품**을 바로 보여준다.

우선 구간:

1. 정확 동률
2. ±5bp
3. ±10bp

표시:

- 업권
- 금융사
- 상품
- 최고금리
- 검토금리 대비 bp
- 기준일

stable product identity / 현재 market scope / selected term 계약을 그대로 따른다.

상품을 임의로 기관단위 대표로 축약하지 않는다. 공식 pricing peer와도 별도 섹션이다.

---

## 9. 경쟁기관을 2종으로 분리

### 9.1 공식 pricing peer

기존 `strategy.relative_pricing`의 공식 gate를 그대로 사용한다.

의미: 공식 가입가능범위·대표금리·identity/freshness 정책을 통과한 **가격 경쟁기관**.

표시 가능 정보:

- 기관
- 대표금리
- 검토금리 대비 gap
- 금리 기준일
- 수신잔액
- 최근 6개월 수신 증감
- 수신 기준월

### 9.2 비슷한 급 경쟁사 — 규모 peer

사용자 요구에 따라 공식 pricing peer와 별도로 둔다.

핵심 규모축은 다음 2개로 고정한다.

1. **수신잔액(예수금/수신잔액)**
2. **총자산**

이 두 지표를 다른 임의 지표로 대체하지 않는다. 추가 축이 필요하면 문서를 먼저 수정한다.

#### Evidence Gate

규모 peer 계산 전에 반드시 확인한다.

- 동일 canonical institution identity인가
- 수신잔액과 총자산 단위가 명시되어 있는가
- 각 지표의 기준일/기준월이 있는가
- 당사와 비교기관의 시점 차이가 허용범위 안인가
- missing을 0으로 바꾸지 않는가
- 총자산 source와 수신잔액 source의 institution mapping이 검증되었는가

#### v1 fail-closed 정책

현재 public Strategy payload에서 총자산 계약이 확인되지 않으면 **규모 peer를 계산하지 않는다.** UI에는 다음처럼 표시한다.

`비슷한 급 경쟁사 · 총자산 근거 미연동`  
`수신잔액만으로 유사규모 기관을 임의 선정하지 않습니다.`

총자산 근거가 연결된 뒤 별도 spec update에서 distance/band 정책을 확정한다. 구현자가 임의로 ±20%, z-score, log-distance 등의 공식을 만들어 넣지 않는다.

---

## 10. 과거 당사 사례

사용자가 검토금리 X%를 선택하면 가능한 범위에서 당사의 유사금리 과거사례를 보여준다.

목표 필드:

- 당시 상품명 / stable product identity
- 당시 금리
- 당시 기준일
- 당시 전체시장 위치
- 당시 TOP10/TOP25/중앙값
- 신규 판매액 또는 신규수신
- 잔액 변화
- 재예치율

### 10.1 단계적 공개

현재 evidence가 연결된 필드만 사실로 표시한다.

예:

- 과거 당사 금리는 있지만 당시 market snapshot이 없으면 `당시 시장위치 근거 미연동`
- 판매액이 없으면 `상품별 판매액 미연동`
- 재예치율이 없으면 `재예치 실적 미연동`

과거사례를 현재 forward model calibration처럼 사용하지 않는다. correlation / 사례 참고와 model causal calibration을 분리한다.

---

## 11. Progressive disclosure

Primary 화면에서 제거/축소:

- Market Position Ladder: 제거
- Response Surface: 기본 접힘
- 후보금리 5bp wide table: 기본 접힘
- 계산 수식: 기본 접힘
- 민감도 저/기준/고 상세: 기본 접힘
- provenance / model version: 기본 접힘

상세 메뉴 예:

`상세 분석 · 5bp 후보 / 수신반응 곡선 / 계산 가정`.

데이터를 삭제하지 않고 decision-first hierarchy로 내린다.

---

## 12. 카피 계약

사용자 visible 용어는 업무 언어를 우선한다.

권장:

- 검토금리
- 목표 총수신
- 구조 시나리오
- 첫 검토금리
- 시장 위치
- 현재 금리 주변 경쟁상품
- 공식 가격 경쟁기관
- 비슷한 급 경쟁사
- 과거 당사 사례

기본 화면에서 숨김/지양:

- PUBLIC STRUCTURAL v2
- Market Position Ladder
- Response Surface
- threshold
- stress band 원문 기술명

기술명은 상세 근거에서만 허용한다.

---

## 13. 구현 경계

### 이번 v1에서 허용

- presentation 재구성
- 기존 Public Structural v2 forward surface 재사용
- existing candidate를 이용한 bounded target finder
- 현재 market rows에서 금리주변 상품 추출
- Relative Pricing R1 factual peer 재사용
- historical evidence가 있으면 read-only 표시
- missing evidence fail-closed UI

### 이번 v1에서 금지

- collector 변경
- source precedence 변경
- DB schema / migration 변경 없이 해결 가능한 범위에서 임의 데이터 생성
- 새로운 elasticity 계수
- R4 inverse solver 호출
- calibrated recommendation semantics
- funding/asset identity를 fuzzy guess로 결합
- 수신잔액만으로 `비슷한 급`이라고 확정
- 없는 과거 판매액 생성

총자산 데이터를 실제로 새로 수집·저장해야 하면 **별도 high-risk data contract 작업**으로 분리한다.

---

## 14. 구현 구조 제안

새 presentation을 기존 큰 template 직접 수정 대신 별도 모듈로 합성하는 방식을 우선한다.

예상 모듈:

- `strategy_rate_decision_simulator_presentation.py`

기존 엔진은 source of truth로 재사용:

- `PublicStructuralV2MarketPosition`
- `PublicStructuralV2Surface`
- `PublicStructuralV2Marginal`
- existing `strategy.relative_pricing`

기존 Cockpit은 새 simulator가 성공적으로 mount된 경우 legacy primary surface를 숨기고, 상세 분석에 필요한 engine/output만 재사용한다.

---

## 15. Acceptance Criteria

### 기능

- [ ] `금리로 계산` 모드가 proposal rate 변경 시 headline 결과를 갱신한다.
- [ ] `목표금액으로 찾기`가 existing forward candidate만 검색한다.
- [ ] 목표 finder에 interpolation/extrapolation이 없다.
- [ ] out-of-support가 fail closed한다.
- [ ] `추천금리/최적금리/필요금리/달성확률` 카피가 없다.
- [ ] Market Position Ladder가 primary 화면에 없다.
- [ ] 시장 위치는 rank + TOP10/TOP25/median 중심으로 읽힌다.
- [ ] 선택 금리 주변 실제 상품이 업권/기관/상품과 함께 보인다.
- [ ] 공식 pricing peer와 규모 peer가 같은 개념처럼 합쳐지지 않는다.
- [ ] 총자산 근거가 없으면 규모 peer 계산을 차단한다.
- [ ] historical sales/renewal missing을 0으로 표시하지 않는다.

### UX

- [ ] 3초 내 `검토금리 → 예상수신 → 시장위치` 흐름을 읽을 수 있다.
- [ ] 상세 모델 정보는 기본 접힘이다.
- [ ] 데스크톱에서 primary decision area가 기존 cockpit보다 세로로 짧다.
- [ ] 390px 모바일에서 horizontal page overflow가 없다.
- [ ] mode switch와 입력 focus/keyboard가 동작한다.

### 회귀/안전

- [ ] 기존 source precedence / stable identity / dedupe 변화 없음
- [ ] Relative Pricing R1 gate 유지
- [ ] R4 promotion gate 유지
- [ ] blank/null scenario input을 numeric zero로 coercion하지 않음
- [ ] Ruff 통과
- [ ] 전체 pytest 통과
- [ ] 빈 DB migration/model parity 통과
- [ ] Strategy production-copy browser smoke 통과
- [ ] desktop/mobile screenshot 육안검증

---

## 16. 테스트 Matrix

필수 테스트:

1. target exactly candidate total → 해당 candidate
2. target between two candidate totals → 목표 이상을 만족하는 첫 existing candidate
3. target above max → no result / out-of-support
4. blank target → no result
5. blank baseline/maturity/rollover → no target calculation
6. non-monotonic surface → 금리 오름차순 existing candidate 중 조건을 만족하는 첫 점만 선택하며 `최적` 의미를 부여하지 않음
7. missing total assets → size-peer blocked
8. missing funding → 0으로 변환하지 않음
9. nearby products exact tie / ±5bp / ±10bp boundary
10. selected sector/term 변경 시 nearby market context 갱신
11. R1 peer gate blocked → fake peer 미표시
12. historical missing sales → missing label
13. simulator injection idempotence
14. Strategy 외 Search 페이지 no-op

---

## 17. 구현 순서

1. **이 문서 commit/push — 먼저 완료**
2. current payload / total-assets / historical evidence 재감사
3. simulator presentation shell + Mode A
4. bounded Mode B
5. market position compact card
6. current-rate-nearby products
7. official pricing peer composition
8. similar-tier peer evidence gate
9. historical case evidence surface
10. legacy Ladder 제거 + expert disclosure
11. unit/contract tests
12. full CI
13. production-copy Chrome desktop/mobile 검증
14. adversarial self-review
15. Draft PR

---

## 18. Change Control

다음 사항을 바꾸려면 **코드보다 이 문서를 먼저 수정한다.**

- 목표금액 역산 의미
- candidate 검색 범위
- interpolation/extrapolation 허용 여부
- 추천/최적 표현
- 유사규모 경쟁사 기준축
- historical evidence의 factual/calibrated 의미
- source precedence / identity / freshness 허용범위

현재 고정 결정:

- 목표 finder = bounded existing-candidate structural scenario finder
- similar-tier dimensions = **수신잔액 + 총자산**
- Market Position Ladder = primary 화면에서 제거
- Response Surface / 후보금리표 / 계산근거 = 상세 분석으로 이동
- public recommendation / optimization semantics = 금지
