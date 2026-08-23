# Public Structural v2 — Stage G factual-only rate finder

- status: `implemented/complete`
- date: 2026-08-23
- issue: #169
- parent: `20260822-public-structural-v2-decision-cockpit-final.md`
- production_strategy_release_gate: `unchanged_off`
- implementation_pr: #178
- final_validation: #181 / Issue #169 completed

## 1. 목적

Stage G는 실제 비교상품 금리만으로 **시장 조건을 충족하는 최소 선택가능 금리**를 계산한다.
결과는 추천·최적화·예측이 아니라 현재 시장 snapshot에 대한 **조건충족 값**이다.

허용하는 조건은 다음 6개뿐이다.

1. 상위 10% 진입선 도달
2. 상위 10% 진입선 초과
3. 상위 25% 진입선 도달
4. 상위 25% 진입선 초과
5. 시장 최고 동률
6. 시장 최고 초과

목표 총수신, 달성확률, 추천금리, 최적금리, 고객반응 추정은 Stage G 범위가 아니다.

## 2. competitor-only benchmark

Stage B의 `market_position`은 반사실 시장에 제안금리를 삽입해 제안 후 순위를 계산한다.
이 결과의 `market_max_rate`·TOP10·TOP25를 Stage G 목표값으로 재사용하면 제안금리가
자기 자신의 benchmark를 움직이는 self-reference가 생길 수 있다.

따라서 Stage G benchmark는 별도 계약으로 고정한다.

1. 현재 선택된 Strategy 비교군을 사용한다.
2. stable product 기준 당사 anchor 상품 1개를 정확히 제거한다.
3. 제안금리는 삽입하지 않는다.
4. 남은 competitor-only 금리로 TOP10, TOP25, 시장 최고를 계산한다.
5. competitor가 0개면 fail-closed 한다.

즉 Stage G의 benchmark는 제안금리를 바꿔도 변하지 않는다.

## 3. 금리 정밀도와 선택 단위

서로 다른 두 계약을 섞지 않는다.

### 3.1 경제적 동일성

금리의 canonical 정밀도는 기존 DB 계약과 동일한 `DECIMAL(7,4)` / `0.0001%p`다.
시장 최고 **동률**은 이 정밀도에서 정확히 같은 값만 의미한다.

### 3.2 Strategy UI 선택 단위

현재 Strategy 금리 입력은 `step="0.01"`, 즉 `0.01%p = 1bp` 단위다.
Stage G는 실제 화면에서 선택 가능한 최소값을 보여주기 위해 이 단위를 사용한다.

이 1bp는 **현재 UI의 선택 granularity일 뿐 은행의 금리결정 정책이나 경제적 tolerance가 아니다.**

## 4. 최소 선택가능 금리 계산

`step = 0.01%p`라 할 때:

- TOP10/TOP25 `도달`: cutoff 이상인 첫 UI tick
- TOP10/TOP25 `초과`: cutoff보다 큰 첫 UI tick
- 시장 최고 `초과`: competitor max보다 큰 첫 UI tick
- 시장 최고 `동률`: competitor max가 UI tick에 정확히 놓일 때만 해당 tick

중요한 edge case:

- competitor max가 `3.8015%`라면 1bp UI에서 정확한 동률은 만들 수 없다.
- 이 경우 `시장 최고 동률`은 `unavailable`이며 benchmark `3.8015%`를 그대로 보존한다.
- `3.81%`를 동률이라고 부르지 않는다. 그것은 이미 시장 최고를 초과한다.

TOP10/TOP25의 `도달`은 exact tie가 아니라 `>= cutoff` 조건이므로 off-grid cutoff라면
다음 1bp tick이 정상적인 최소 조건충족 값이다.

## 5. 공개 output contract

Stage G output은 다음 의미만 갖는다.

```text
version
status
benchmark_universe = competitor_only_anchor_removed
competitor_count
selection_step_pp
selection_step_bp
selection_semantics
conditions[]
```

각 `conditions[]`는 다음을 포함한다.

```text
target             # top10 | top25 | market_max
relation           # reach | exceed | tie
label
benchmark_rate_pct
status             # ready | unavailable
minimum_selectable_rate_pct  # ready일 때만
reason                       # unavailable일 때만
```

금지 output:

- forecast / predicted amount
- probability
- recommendation / optimal score
- coefficient / model parameter
- private metadata / 내부자료

## 6. Python ↔ JS parity

Python을 canonical 구현으로 두고 browser JS mirror를 동일 계약으로 검증한다.
JS는 부동소수점 동률 오판을 피하기 위해 금리를 `0.0001%p` 정수 unit으로 변환해 계산한다.

필수 parity 케이스:

- benchmark가 1bp tick 위에 있는 경우
- benchmark가 1bp tick 사이에 있는 경우
- 시장 최고 exact tie 가능/불가능
- TOP10/TOP25 reach/exceed
- anchor missing / duplicate / current-rate mismatch
- competitor 0개
- invalid selection step

## 7. Cockpit 표출

Stage F Cockpit에 `시장조건 충족 금리` factual block을 추가한다.

표출 원칙:

- 구조 시나리오 입력 여부와 무관하게 보인다.
- competitor-only benchmark를 사용한다.
- 제안금리를 바꿔도 값이 변하지 않아야 한다.
- exact benchmark와 최소 선택가능 금리를 함께 보여준다.
- `조건충족 값 · 자동 결정 아님`을 고정 표기한다.
- 1bp는 현재 Strategy 입력 선택단위라는 설명을 고정 표기한다.

## 8. Runtime gate

production-derived Strategy build를 desktop/mobile Chrome에서 검증한다.

필수 검증:

1. factual finder 6개 조건 렌더
2. 제안금리 변경 전/후 finder 결과 동일
3. 시장 최고 동률의 off-grid unavailable 의미 보존
4. 구조 시나리오 금액/확률/계수의 finder 유입 없음
5. `추천금리`, `최적금리`, `달성확률` 미표출
6. desktop/mobile horizontal overflow 및 시각적 겹침 없음
7. 기존 Stage F Ladder/Response Surface/candidate table 회귀 없음

## 9. Boundary

변경하지 않는다.

- DB/schema/migration
- collector/source precedence
- stable product identity
- structural inflow coefficient
- public/private forecast boundary
- Production Strategy Release Gate

Stage G 완료 조건은 Python/JS parity + targeted tests + production-derived desktop/mobile Chrome + screenshot 직접 확인이다.
