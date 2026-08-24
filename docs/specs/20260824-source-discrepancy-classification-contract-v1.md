# Source Discrepancy A0 Classification Contract v1

- 기준일: 2026-08-24
- 관련 Issue: #98
- 상위 coordination spec: `20260824-post-merge-improvement-master-plan-v3.md` (PR #193 Draft)
- 기준 main: `1325d54e9d28bf05040c4f6c51e92bc45bd69253`
- 상태: implementation contract / read-only audit

## 1. 결론

A0 재검증 결과, 현재 `source_discrepancy_triage.py`의 대표 원인 classification precedence는
`20260820-source-discrepancy-priority-triage-v1.md` §6과 일치한다.

따라서 이번 단계에서는 classification 의미·threshold·precedence를 변경하지 않는다.
대신 현재 규칙을 **경계값과 precedence까지 자동 테스트로 잠근 뒤**, 동일 계약으로 production
queue를 다시 생성하여 기존 6건의 class family가 유지되는지와 신규 항목이 source-data 변화인지
classification 회귀인지 분리한다.

Final-head production R2 audit에서는 기존 6건이 그대로 유지되면서 새 source data로 30건이
추가되어 queue가 **6 → 36건**으로 증가했다. 이 증가는 classification 변경이 아니다.

이 classification은 source authority가 아니라 **investigation cause / priority metadata**다.

## 2. Current classification contract

대표 원인은 아래 순서에서 처음 만족하는 하나를 선택한다.

| 순서 | 조건 | classification |
|---:|---|---|
| 1 | official signal = `official_conflict` | `official_conflict` |
| 2 | official signal ∈ `neither_supported`, `primary_supported`, `secondary_supported`, `both_supported`, `mixed_support` | `official_evidence_discrepancy` |
| 3 | status = `rate_mismatch` | `same_effective_date_conflict` |
| 4 | 두 source 중 가장 오래된 `source_effective_at` age >= 90일 | `stale_source` |
| 5 | 최고금리 절대차 >= 0.20%p | `material_rate_gap` |
| 6 | status = `rate_mismatch_date_diff` | `freshness_gap` |
| 7 | status = `rate_mismatch_date_unknown` | `unknown_effective_date` |
| 8 | 그 외 mismatch/incomplete | `incomplete_or_minor_drift` |

### 2.1 경계값

- stale age 경계: **90일 포함**
- material rate gap 경계: **0.20%p 포함**
- `rate_mismatch`는 stale 또는 큰 금리차보다 먼저 `same_effective_date_conflict`로 분류
- effective date가 unknown이어도 절대차가 0.20%p 이상이면 현재 계약상
  `material_rate_gap`이 `unknown_effective_date`보다 우선

이 순서는 우연한 `if` 배열이 아니라 현행 triage v1의 명시적 precedence로 취급한다.
변경이 필요하면 A0 후속 decision PR에서 영향도를 먼저 계산한다.

## 3. Freshness와 authority 분리

A0는 다음을 다시 고정한다.

- `source_effective_at`은 mismatch의 publication/freshness 해석을 위한 관측값이다.
- `last_seen_at`은 provenance/freshness metadata이며 현재 representative cause classification을
  직접 선택하지 않는다.
- 더 최근의 source를 자동 authority로 승격하지 않는다.
- `stale_source`와 `freshness_gap`은 어느 source가 정답이라는 의미가 아니다.
- triage는 canonical 값을 수정하지 않는다.
- triage는 FSB primary / FINLIFE secondary precedence를 변경하지 않는다.

`last_seen_at`을 classification input으로 승격하려면 별도 정책 변경으로 취급한다.
현재는 source effective date와 observation recency의 의미를 섞지 않는다.

## 4. Official evidence precedence

variant-compatible official evidence가 연결된 경우 source-only classification보다 먼저 분류한다.

단:

- official evidence가 `primary_supported`여도 canonical을 자동 선택하지 않는다.
- `secondary_supported`도 동일하다.
- `official_conflict`는 공식 surface 내부 충돌을 뜻하며 authority 결정을 차단한다.
- variant가 모호하면 official evidence를 억지로 연결하지 않는다.

A0 테스트는 official signal이 대표 classification을 override하더라도
`triage_selects_authority=false`, `triage_mutates_canonical=false`가 유지됨을 검증한다.

## 5. Queue replay contract 및 final runtime 결과

기존 production baseline의 대표 두 계열을 fixture 수준에서 재생한다.

### 대신저축은행 계열

- 기존 baseline: 정기적금 24m / 36m
- 관찰 classification: `stale_source`
- 특징: 1.00%p gap과 장기 effective-date gap이 함께 있어도
  stale age >= 90일이 `material_rate_gap`보다 먼저 대표 원인이 된다.

### DH저축은행 계열

- 기존 baseline: 정기예금 12m branch simple/compound 및 비대면 simple/compound
- 관찰 classification: `freshness_gap`
- 특징: 최근의 서로 다른 effective date + 0.10~0.15%p gap으로,
  stale/material threshold에 걸리지 않을 때 `freshness_gap`이 대표 원인이 된다.

이 fixture replay는 현재 production raw evidence 자체를 대신하지 않는다.

Final-head production R2 read-only audit 결과:

- 이전 baseline: 6건
- final-head queue: 36건
- P0 0 / P1 2 / P2 0 / P3 34
- 기존 대신 2건과 DH 4건은 순서/class family 유지
- 신규 30건은 모두 상상인플러스저축은행 `freshness_gap`
- 신규 30건은 최신 FSB successful run의 rate/effective-date 변화로 발생
- 따라서 6 → 36 증가는 classifier 회귀가 아니라 source-data/publication timing 변화

## 6. Required automated tests

A0 완료를 위해 다음을 고정한다.

1. stale 90일 boundary
2. stale 89일 + 작은 금리차 -> `freshness_gap`
3. 0.20%p material boundary
4. 0.19%p + 최근 date diff -> `freshness_gap`
5. same-date conflict precedence
6. unknown effective date + 0.20%p 이상/미만의 현재 precedence
7. official signal precedence
8. 동일 입력의 queue 결정성
9. triage가 canonical/authority를 선택하지 않음
10. 대신/DH 기존 baseline class family representative replay

테스트 파일:

`tests/test_source_discrepancy_classification_contract.py`

## 7. A0 Acceptance

A0는 다음이 모두 충족되어야 닫힌다.

- 기존 classification precedence 변경 없음
- 위 경계/precedence 테스트 통과
- 기존 source discrepancy test suite 회귀 없음
- General CI lint/test/migration 통과
- production R2 read-only audit 재실행
- 기존 baseline 6건이 동일 계약/class family로 유지되는지 확인
- 새로운 queue 항목이 있으면 source-data 변화와 classification 회귀를 분리해 보고
- 재분류 전/후 queue diff 보고
- ambiguity 차단 항목은 P0~P3 queue와 별도로 유지
- canonical/source precedence/DB/schema/rate-data write 없음

Final-head audit은 위 조건을 충족했고, 신규 30건은 source-data 변화로 분리됐다.

production audit을 실행하지 못하면 A0는 `contract locked / runtime reclassification 미검증`으로만 보고한다.

## 8. Non-goals

이번 A0 PR에서 하지 않는다.

- classification threshold 변경
- classification precedence 변경
- 기존 baseline 6건 또는 신규 30건을 오류로 자동 확정
- official evidence 추가 수집
- payment_method 7D identity 전환
- canonical 금리 수정
- source precedence 변경
- DB/schema/migration
- collector/scheduler 변경
- Strategy Release Gate 변경

## 9. 다음 단계

A0 완료 후:

1. A1 대신 24m/36m forensic
2. A2 DH 12m 4 variants forensic
3. ambiguity 51건 census
4. 신규 상상인플러스 30건은 하나의 source-change cluster로 별도 추적

순서로 진행한다.
