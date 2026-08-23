# Public Structural v2 Stage J — Actual-data Runtime / Visual QA

```yaml
document_type: verification_contract
status: in-progress
date: 2026-08-23
issue: 169
base_main: 4185850ef3944a3757ab8d3606ffd10f06e474ec
stage: J
runtime_logic_change: none_planned
production_strategy_release_gate: unchanged_off
```

## 1. 목적

Public Structural v2를 단위테스트·개별 Stage 성공만으로 완료 처리하지 않는다.
production-derived Strategy 데이터와 실제 Chrome에서 A~I 계약이 동시에 성립하는지
최종 통합 검증한다.

Stage J는 기능 확장이 아니라 **완료 판정 Gate**다. 검증 중 결함이 나오면 해당 결함만
최소 수정하고 동일 Gate를 다시 통과해야 한다.

## 2. Source of Truth

- `docs/specs/20260822-public-structural-v2-decision-cockpit-final.md`
- Stage A0~I merged implementation
- `inflow-public-forecast-v1` sanitized forecast contract
- Production Strategy Release Gate default OFF contract

## 3. Actual-data factual spot check

production-derived `data/strategy-table.json`을 실제 browser가 읽는 것과 같은 방식으로
해석한다.

### 3.1 dense tie

저축은행 정기예금 6/12/24/36개월 중:

1. 고려저축은행 anchor가 존재하고
2. 1bp UI grid에서 선택 가능한 금리이며
3. 동일금리 competitor 수가 가장 많은 실제 금리

를 자동 선택한다.

`dense tie` 검증이 형식적 1개 동률이 되지 않도록 실제 competitor 동률 수가 최소 3개
이상이어야 한다. 이 3은 모델 threshold가 아니라 **dense tie 실제사례를 확보하기 위한
QA fixture 조건**이다.

### 3.2 independent hand calculation

Stage J smoke는 UI/engine의 rank 계산 결과를 그대로 신뢰하지 않고 실제 market rows에서
독립 계산한다.

- counterfactual universe = peers + proposal
- anchor current row는 peer에서 제외
- `rank_best = higher + 1`
- `rank_worst = higher + peer_ties + 1`
- top10 cutoff = descending `ceil(N * 0.10)`번째
- top25 cutoff = descending `ceil(N * 0.25)`번째
- median
- market max
- ±5bp peer count

그 결과를 browser engine과 실제 Cockpit 표시값에 대조한다.

### 3.3 self replacement

proposal = current rate인 별도 점검에서:

- universe N이 변하지 않음
- anchor가 자기 자신과 동률로 세어지지 않음
- tie competitor count는 peers만 포함

을 확인한다.

## 4. Structural 5bp / marginal sanity

실제 시장 universe에 구조 시나리오 입력은 synthetic QA 값만 사용한다.

```yaml
baseline_new_money: 100
maturity_amount: 200
current_rollover_rate_pct: 60
```

이는 내부실적이 아니며 기존 public structural formula의 runtime 연결만 점검한다.

검증:

- economics grid 인접점은 정확히 5bp
- 모든 grid 금리가 Candidate table에 존재
- fixed-5bp surface interest delta는 finite amount로 표시
- `NaN` / `Infinity` 없음
- ratio 기반 `한계조달원가`는 노출되지 않음
- off-grid proposal은 ratio/marginal을 임의 외삽하지 않음
- stress range는 probability/confidence/prediction interval로 표현되지 않음

현재 Stage E가 불안정한 denominator ratio를 아예 공개하지 않도록 결정했으므로 Stage J의
`marginal denominator stability` 확인은 **ratio 미노출 + fixed 5bp delta만 노출** 계약을
확인하는 방식으로 수행한다.

## 5. Runtime / visual QA

두 viewport를 실제 Chrome으로 확인한다.

- desktop: 1280 × 900
- mobile: 390 × 844

필수:

- document horizontal overflow 없음
- Ladder 동일금리 중복 marker 없음
- Ladder label/rate bounding-box collision 없음
- Candidate table text overflow 없음
- browser pageerror/console error 없음
- screenshot artifact 생성

Cockpit은 hover-only tooltip에 의존하지 않는 구조다. `[title]` / `[data-tooltip]`가 없으면
`inline-no-hover-tooltip-dependency`로 기록하고, 별도 hover tooltip이 생기면 Stage J가 그
존재를 metrics에 기록한다.

## 6. Task-based smoke

stopwatch 숫자를 성공기준으로 만들지 않는다. 실제 화면에서 아래 4개 task의 정보가
즉시 존재하는지 확인한다.

1. 현재/제안 **실제 시장 위치**를 찾을 수 있음
2. **시장 사실**과 **미보정 구조 시나리오**가 분리되어 있음
3. **다음 5bp 표면비용**을 찾을 수 있음
4. `stress range`를 확률구간으로 오해시키는 문구가 없음

금지 표현:

- 추천금리
- 최적금리
- 달성확률
- confidence interval
- prediction interval
- 한계조달원가

## 7. Release Gate OFF regression

같은 production-derived DB local copy로 먼저 **환경변수 없이** 일반 site build를 수행한다.

필수:

- `strategy.html` 미생성
- `data/strategy-table.json` 미생성
- main index에 Strategy navigation 미노출

그 다음 QA 전용 isolated build에서만 `RATE_MONITOR_STRATEGY_DASHBOARD=1`을 켜 Chrome
검증을 수행한다.

Stage J가 Production Strategy Release Gate를 ON하는 변경은 하지 않는다.

## 8. Verification

- Public Structural v2 targeted Ruff
- `tests/test_public_structural_v2_*.py` 전체
- browser script syntax
- production DB runner-local restore
- local-copy migrations
- Release Gate OFF actual-data build
- QA-only Strategy ON build
- 기존 Stage F/G/H Chrome regression smoke
- Stage J actual-data handcalc/runtime/visual smoke
- metrics JSON + desktop/mobile screenshots artifact
- artifact 직접 visual inspection
- GitHub review/thread 확인
- adversarial self-review

General CI의 기존 unrelated Ruff debt는 Stage J diff와 별도로 보고한다.

## 9. 완료판정

아래가 모두 만족될 때 Public Structural v2 구현계획의 Stage J를 완료한다.

- [ ] actual dense tie 확인
- [ ] anchor self replacement 확인
- [ ] factual rank/cutoff 손계산 일치
- [ ] structural 5bp grid sanity
- [ ] marginal ratio 미노출 / finite fixed-step cost
- [ ] desktop Chrome PASS
- [ ] 390px mobile Chrome PASS
- [ ] overflow / label collision PASS
- [ ] task-based smoke PASS
- [ ] Release Gate default OFF PASS
- [ ] screenshots 직접 visual review PASS
- [ ] private/internal data 변경 없음
- [ ] 새 P0/P1 blocker 없음
