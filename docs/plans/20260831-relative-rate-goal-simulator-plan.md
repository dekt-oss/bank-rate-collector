> **SUPERSEDED / 정정 (2026-08-31).** 이 문서는 v2로 대체되었으며 구현 근거로 사용하지 않는다.
>
> 아래 원문에는 현재 저장소 상태와 충돌하는 서술이 남아 있으므로 decision trail로만 보존한다.
>
> - `production_strategy_release_gate: unchanged_off` / `Production Strategy Release Gate OFF` → **오류**. 현재 Strategy는 canonical site-writer가 발행하는 production surface다. 현행 기준은 `docs/plans/20260831-relative-rate-goal-simulator-plan-v2.md`와 `AGENTS.md`다.
> - R1 public 단계의 factual/forecast 경계는 v2가 우선한다. 목표수신 입력·예상수신·추천금리·필요금리 범위는 promoted private champion 전에는 렌더링하지 않는다.
>
> **현행 문서:** `docs/plans/20260831-relative-rate-goal-simulator-plan-v2.md`

# 상대금리 기반 목표형 금리결정 시뮬레이터 — 기획안

```yaml
document_type: product_plan
status: draft_for_review
date: 2026-08-31
repository: dekt-oss/bank-rate-collector
branch: docs/relative-rate-goal-simulator-20260831
production_strategy_release_gate: unchanged_off
merge_policy: explicit_user_approval
internal_data: prohibited_in_public_repo
```

---

## 0. 결론

금리결정 화면의 중심 질문을 다음처럼 바꾼다.

기존:

> 금리를 3.5%로 바꾸면 수신이 얼마나 변할까?

목표:

> 다음 1~3개월 동안 필요한 수신을 확보하려면, 현재 경쟁시장 기준으로 어느 수준의 금리가 필요한가?

그리고 시스템이 제시한 금리를 사용자가 슬라이더로 움직이면 다음이 동시에 바뀌어야 한다.

- 예상 수신/순수신 범위 — **내부자료 보정 후에만 활성화**
- 경쟁사 대비 금리 위치
- 당사보다 높은/낮은 주요 경쟁사
- 경쟁사별 금리와 수신잔액
- 금리 조정에 따라 새로 앞서거나 뒤처지는 경쟁사 수
- 추가 표면이자비용
- 과거의 유사한 상대금리 상황 — **시점 일치 자료가 있을 때만 활성화**

핵심은 절대금리 자체보다 **상대금리**를 의사결정의 중심 변수로 올리는 것이다.

---

# 1. 왜 바꾸는가

실제 금리결정에서는 `3.50%`라는 숫자 자체보다 그 시점의 경쟁사가 얼마를 주고 있는지가 중요하다.

예를 들어 당사 금리가 같은 3.50%라도:

```text
상황 A
당사 3.50%
주요 경쟁사 중앙값 3.20%
=> 당사 +30bp

상황 B
당사 3.50%
주요 경쟁사 중앙값 3.70%
=> 당사 -20bp
```

두 상황에서 고객이 체감하는 경쟁력은 다르다.

따라서 미래의 내부실적 기반 모델은 단순히 `당사 금리 → 수신액` 관계만 보는 것이 아니라 최소한 다음을 함께 봐야 한다.

- 당사 금리
- 경쟁사 대비 금리차(`market_gap_bp`)
- 경쟁시장 내 당사 위치
- 당사 주변 금리 밀집도
- 주요 경쟁사의 수신규모/증감
- 시장 전체 금리국면
- 당사 과거 수신 흐름과 만기구조

기존 Private Calibration Protocol에 이미 `own_rate_pct`, `rate_change_bp`, `market_gap_bp`, `market_rank_best/worst`, `market_tie_count`, `market_within_5bp_count`가 허용 feature로 정의되어 있다. 이번 기획은 그 방향을 제품 UX와 과거 비교 방식까지 확장한다.

---

# 2. 기존 계약과의 관계

## 2.1 유지해야 하는 현재 기준

다음은 재구현하지 않는다.

- Public Structural v2
- Factual Market Position Engine
- stable product identity
- source precedence
- Strategy 4업권 구조
- NH e-joy 최고금리 provenance/fail-closed 계약
- 기존 market position의 anchor replacement, 공동순위, threshold crossing 계약
- public/private forecast 분리
- Production Strategy Release Gate OFF

## 2.2 기존 문서와의 충돌 해소

2026-08-18 Deposit Pricing 명세에는 장기 목표로:

> 목표 순수신을 달성하는 최소 필요금리

가 정의되어 있다.

하지만 2026-08-22 Public Structural v2는 내부실적이 없는 공개 구조모형으로 `목표 수신액 → 최소금리`를 자동 계산하면 실제 예측처럼 오독될 위험이 있어 해당 기능을 제외했다.

이번 기획은 이를 뒤집지 않는다.

### 최종 계약

```text
현재 / 내부자료 미보정
= 경쟁시장 포지셔닝 시뮬레이터
= factual market facts + structural stress only
= 목표 수신 기반 자동 추천금리 금지

향후 / 내부자료 보정 완료
= 목표형 금리결정 시뮬레이터
= calibrated private forecast + relative market context
= promotion gate + human review 통과 후 목표 역산 활성화
```

즉 UI의 최종 목적은 목표형이지만, 현재 public 데이터만으로 없는 예측력을 만들어내지 않는다.

---

# 3. 핵심 개념

## 3.1 Relative Rate — 상대금리

기본 정의:

```text
peer_gap_bp
= 당사 제안금리 - Direct Peer 금리 중앙값
```

보조 정의:

- Direct Peer 대비 공동순위 범위
- Direct Peer 중 당사보다 높은 기관 수
- Direct Peer 중 당사보다 낮은 기관 수
- 당사 금리 ±5bp 이내 기관 수
- 상위 10% / 25% cutoff와의 차이

절대금리와 상대금리를 모두 보관하지만, 과거 유사사례 검색과 내부모형에서는 상대금리를 핵심 설명축으로 검증한다.

## 3.2 Direct Peer — 주요 경쟁사

`전체 업권에서 금리가 비슷한 기관`이 아니라 **실제로 당사와 비교 가치가 높은 기관 집합**이다.

기본 방향:

1. 같은 업권
2. 지리적 경쟁권
3. 비슷한 수신규모
4. 필요 시 상품/채널 특성

업권마다 동일한 N을 강제하지 않는다.

현재 NH의 N=16 정책은 NH에 맞춘 별도 정책이며 저축은행에 그대로 복사하지 않는다.

## 3.3 경쟁사 수신규모

가능한 경우 경쟁사 카드에는 금리뿐 아니라 기관별 수신잔액을 함께 보여준다.

이유:

```text
우리보다 높은 금리 기관 8개
```

만 보는 것보다:

```text
우리보다 높은 금리 기관 8개
그 기관들의 합산 수신잔액 1.8조원
Direct Peer 전체 수신의 37%
```

이 훨씬 실무적인 시장 압력을 보여준다.

단 기관별 수신잔액이 없거나 identity가 확정되지 않은 경우 0으로 대체하지 않고 `자료 없음`으로 표시한다.

---

# 4. 제품 UX — 최종 구조

## 4.1 상단: 목표 먼저 입력

최종 calibrated 모드의 첫 질문은 `금리를 얼마로 할까요?`가 아니다.

```text
[목표]
현재 수신잔액 5,000억원
목표 시점 3개월 후
목표 수신잔액 5,300억원
또는 목표 순수신 +300억원
```

둘 중 하나를 입력하면 나머지를 계산한다.

### 현재 public-only 모드

내부자료 보정 전에는 이 입력을 받아 `필요금리`를 계산하지 않는다.

대신 명확히 표시한다.

> 자사 실적 보정 전에는 목표 수신에 필요한 금리를 예측하지 않습니다. 현재는 검토 금리별 경쟁시장 위치를 비교할 수 있습니다.

## 4.2 권장 금리 범위 — calibrated 모드 전용

내부모형이 promotion gate를 통과한 이후에만 활성화한다.

예:

```text
목표 순수신 +300억원 / 3개월
검토 필요 금리 3.50~3.60%
중심 시나리오 3.55%
```

원칙:

- 단일 숫자보다 범위를 우선
- `정답`, `확정`, `달성 보장` 표현 금지
- 예측구간/불확실성 함께 표시
- model version / as-of date / data freshness 확인 가능
- feasible target이 아니면 억지 금리 외삽 금지

## 4.3 동적 What-if 슬라이더

목표 역산 결과와 별개로 사용자가 금리를 직접 움직일 수 있어야 한다.

예:

```text
3.30 ──────●────── 3.80
            3.55%
```

금리가 바뀔 때 즉시 함께 갱신:

### 현재도 factual하게 가능한 값

- 경쟁사 공동순위
- Direct Peer 중앙값 대비 ±bp
- 우리보다 높은/낮은 경쟁사 수
- 새로 앞서는 기관 / 새로 뒤처지는 기관
- ±5bp 밀집기관 수
- 경쟁사별 금리
- 경쟁사별 수신잔액/증감 — 존재할 때만
- 표면이자비용 변화

### calibrated 이후 추가되는 값

- 예상 신규수신
- 예상 재예치
- 예상 순수신/기말수신
- 예측 범위
- 목표 대비 부족/초과
- 추가 수신 1억원당 한계비용 — 안정성 Gate 통과 시만

## 4.4 주요 경쟁사 패널

제안금리 주변의 경쟁사를 단순 TOP5가 아니라 `의사결정 관련도` 순서로 보여준다.

예:

| 기관 | 최고금리 | 당사 대비 | 수신잔액 | 6M 증감 | 상태 |
|---|---:|---:|---:|---:|---|
| A | 3.70% | -15bp | 4,900억 | +5.1% | 당사보다 높음 |
| B | 3.60% | -5bp | 5,400억 | +2.8% | 당사보다 높음 |
| 당사 | 3.55% | - | 5,000억 | - | 제안금리 |
| C | 3.50% | +5bp | 4,700억 | +6.3% | 당사가 높음 |

중요:

- 경쟁사 수신잔액이 없으면 빈칸/자료없음
- 순위만으로 경쟁사를 정의하지 않음
- `가장 높은 금리 기관`과 `Direct Peer`를 구분
- 경쟁사 선택 근거를 drill-down 가능하게 함

---

# 5. 과거 유사사례 — 절대금리 재현이 아니라 상대시장 재현

내부자료 도착 후 가장 중요한 분석 중 하나다.

잘못된 방식:

> 과거 당사 금리가 3.50%였을 때 수신액은 얼마였는가?

목표 방식:

> 과거에 당사의 경쟁사 대비 위치가 지금 검토안과 비슷했던 시점에서 수신이 어떻게 움직였는가?

## 5.1 Historical Analogue 기본 조건

후보 유사기간은 최소 다음을 as-of 시점 기준으로 비교한다.

- `peer_gap_bp`
- 경쟁군 내 순위/공동순위 범위
- 경쟁사 금리 밀집도
- 기준금리/시장 예금금리 regime
- 상품 가입기간
- 필요 시 계절성
- 당사 만기도래 규모/기존 수신 흐름 — 내부자료 존재 시

## 5.2 Point-in-time Peer 원칙

현재의 Direct Peer 집합을 과거에 그대로 복사하지 않는다.

과거 비교에서는 그 당시 알 수 있었던:

- 당시 기관 identity
- 당시 수신규모
- 당시 지리/업권 상태
- 당시 경쟁사 금리

를 기준으로 **Historical Peer Snapshot**을 만든다.

오늘의 기관규모를 사용해 2024년의 경쟁사를 재선정하면 look-ahead bias가 생길 수 있으므로 금지한다.

## 5.3 현재금리의 과거 carry-back 금지

2026년 현재 금리를 2025년 수신잔액에 붙여 과거 상황처럼 사용하지 않는다.

과거 시점에 실제 존재했던 금리 raw/evidence가 없으면:

```text
historical_rate_unavailable
```

로 유지한다.

현재 Rate × Funding Matrix의 fail-closed 원칙을 그대로 따른다.

---

# 6. 목표 역산 엔진 — 내부자료 보정 후

## 6.1 Forward model과 Inverse solver 분리

먼저 검증된 forward model이 있어야 한다.

```text
입력:
- 제안금리
- 상대금리
- peer position
- 내부 과거수신/만기
- 외부시장환경

출력:
- 예상 신규수신
- 예상 재예치
- 예상 순수신/기말잔액
- 불확실성 범위
```

그 다음 inverse solver가 후보금리 grid를 탐색한다.

```text
목표 순수신 +300억원
→ 후보금리별 calibrated forecast 계산
→ 목표를 만족하는 최소/안정적 범위 탐색
→ 비용과 경쟁사 위치를 함께 표시
```

inverse solver가 자체적으로 예측식을 갖지 않는다.

## 6.2 Fail-closed 조건

다음에서는 필요금리를 출력하지 않는다.

- private calibrated champion 없음
- 입력 target이 학습/검증 범위를 과도하게 벗어남
- historical/market feature freshness 실패
- peer coverage가 최소 Gate 미달
- monotonicity/response sanity Gate 실패
- model uncertainty가 허용한도를 초과

`계산 불가`가 잘못된 확정금리보다 우선한다.

---

# 7. Rate × Funding Matrix의 위치

Rate × Funding Matrix를 폐기하지 않는다.

다만 제품의 1차 질문은 아니다.

최종 화면 계층:

```text
1. 목표 수신 / 목표 시점
2. 필요 금리 범위 (calibrated 이후)
3. 검토 금리 What-if
4. 해당 금리의 Direct Peer 경쟁상황
5. 과거 유사 상대금리 사례
6. Rate × Funding Matrix
7. 지역/시장 상세와 근거 데이터
```

Matrix는 다음 질문을 보조한다.

> 현재 비슷한 기관들 중 누가 상대적으로 높은/낮은 금리로 수신을 늘리고 있는가?

인과효과를 증명하는 차트로 표현하지 않는다.

---

# 8. 데이터 준비 상태와 선행 과제

## NH

현재 가장 준비도가 높다.

- current 12M rate coverage 확보
- institution funding coverage 확보
- Direct Peer N=16 정책 존재

남은 핵심:

- 과거 시점 금리 raw/evidence 확보 여부 확인
- Historical Peer Snapshot 가능 범위 확인

## 저축은행

원천 funding 79개 기관이 존재하지만 Strategy exact mapping은 현재 66개 수준이므로 먼저 identity gap을 해결해야 한다.

특히 대형 기관이 누락된 상태에서 peer/funding 분포를 만들면 경쟁군이 편향될 수 있다.

따라서:

1. 13개 source identity exact mapping
2. 79개 coverage 재검증
3. 저축은행 전용 peer N/거리 정책 결정
4. 그 후 상대금리/수신 시뮬레이터 활성화

순서로 진행한다.

## 신협

개별기관 funding의 exact official endpoint가 확정되지 않아 현재 production canonical funding으로 보지 않는다.

금리는 사용할 수 있어도 경쟁사 수신금액은 `자료없음`으로 fail-closed한다.

---

# 9. 제품 표현 규칙

## 허용

- 경쟁사 대비 +13bp
- 공동 4~7위 / 16개
- 당사보다 높은 peer 3개
- 제안금리에서 새로 앞서는 기관 5개
- 경쟁사 수신잔액 합계 — exact funding identity가 있을 때
- calibrated model 기준 예상 범위
- 과거 유사 상대금리 시점

## 금지

내부실적 보정 전:

- 권장금리 3.55%
- 목표 +300억 달성금리
- 예상 수신 +280억
- 달성확률 84%

공통:

- 금리 인상 때문에 수신이 늘었다는 단정
- current rate를 historical funding month에 carry-back
- missing funding을 0으로 처리
- 이름만 비슷한 기관 자동 merge
- 임의 종합점수로 중요한 실제 숫자를 숨김

---

# 10. 구현 단계 제안

## Phase R0 — 계약/데이터 readiness

- relative-rate definitions 고정
- Direct Peer / Historical Peer Snapshot 구분
- savings bank identity 79/79 exact coverage 목표
- NH historical rate evidence 조사
- CU funding unavailable 상태 명시

## Phase R1 — Public Relative Market Simulator

내부자료 없이 구현 가능.

- candidate rate slider
- Direct Peer table
- peer median gap
- rank range / crossing
- competitor funding amount/growth 표시
- above/below peer funding aggregate
- surface cost
- current factual market only

## Phase R2 — Historical Relative Context

공식 과거 rate/funding evidence가 충분한 업권부터.

- point-in-time peer snapshot
- historical relative-rate timeline
- 유사시장 사례 검색
- 단, 당사 내부수신 결과 연결 전에는 `시장 과거사례`로만 표현

## Phase R3 — Private Internal Calibration

내부자료를 public repo 밖에서 수령 후.

- internal rate/flow/maturity mapping
- as-of feature table
- relative-market features
- OOS backtest
- challenger promotion gate
- human review

## Phase R4 — Goal-based Pricing

R3 champion 승인 후.

- target ending balance / net inflow input
- inverse candidate search
- feasible rate range
- What-if dynamic forecast
- uncertainty
- marginal funding cost
- historical analogue evidence

---

# 11. 성공 기준

최종적으로 수신 담당자가 다음 순서로 사용할 수 있어야 한다.

```text
1. 목표 수신액과 기간을 입력한다.
2. 시스템이 검증된 범위 안에서 필요한 금리구간을 제시한다.
3. 해당 금리를 적용했을 때 주요 경쟁사가 누구이고 어디까지 앞서는지 본다.
4. 경쟁사의 금리와 수신규모를 함께 확인한다.
5. 슬라이더로 5~10bp 조정하면서 예상 수신/비용/경쟁위치 변화를 본다.
6. 과거에 상대시장 위치가 비슷했던 사례를 확인한다.
7. 최종 금리를 사람이 결정한다.
```

시스템의 역할은 금리를 자동 결정하는 것이 아니라 **사람이 금리를 결정하기 위해 필요한 상대시장·수신반응·비용 근거를 같은 화면에서 일관되게 제공하는 것**이다.