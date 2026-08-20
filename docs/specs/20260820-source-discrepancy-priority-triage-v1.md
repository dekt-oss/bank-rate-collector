# 저축은행 원천 불일치 중요도 자동분류 v1

기준일: 2026-08-20

선행 PR: #153  
관련 Issue: #98

## 1. 목적

#153의 `FSB ↔ 금융상품한눈에 ↔ 개별 저축은행 공식 홈페이지` read-only
교차검증 결과에서 **조사해야 할 mismatch를 중요도순으로 자동 정렬**한다.

이 단계의 점수는 `어느 원천이 정답인가`를 자동 판정하는 authority score가 아니다.
운영자가 어떤 불일치부터 공식 evidence를 확인할지 정하는 **investigation priority**다.

불변 조건:

- canonical 금리 자동 수정 없음
- FSB primary / FINLIFE secondary precedence 변경 없음
- product identity / alias registry 변경 없음
- production DB/R2 write 없음
- `rate-data` write 없음
- Vercel deploy 없음
- Strategy 계산 변경 없음

## 2. 입력 범위

대상은 discrepancy report의 다음 status만이다.

- `rate_mismatch`
- `rate_mismatch_date_diff`
- `rate_mismatch_date_unknown`
- `incomplete_rate`

#153 production audit의 기준점은 mismatch/incomplete 27행이다.

`unmatched_product`와 `source_only`는 상품 identity 조사 성격이 달라 이번 queue에는
섞지 않는다. 별도 identity triage로 확장할 수 있다.

## 3. 출력

full report의 `triage`와 별도
`work/source-discrepancy-priority-queue.json`을 동시에 만든다.

각 queue item은 다음을 가진다.

- `rank`
- `priority`: `P0` / `P1` / `P2` / `P3`
- `score`: 0~100
- `classification`
- 기관 / 상품 / 기간
- FSB / FINLIFE 최고금리와 절대 차이
- 두 source의 `source_effective_at`
- 기준일 gap
- 가장 오래된 source effective age
- 연결된 official evidence status/signal
- 점수 구성요소
- 권고 조사행동
- raw artifact / source locator provenance
- 동일 기관 mismatch 개수

## 4. 점수

점수는 deterministic additive heuristic이고 최종값은 100으로 cap한다.

### 4.1 mismatch 상태

| 신호 | 점수 |
|---|---:|
| 동일 기준일 `rate_mismatch` | +45 |
| `rate_mismatch_date_unknown` | +35 |
| `incomplete_rate` | +35 |
| 기준일 차이 `rate_mismatch_date_diff` | +20 |

같은 날 공시라고 주장하면서 금리가 다르면 단순 publication lag로 설명하기 어렵기 때문에
가장 높은 기본 점수를 준다.

### 4.2 공식 evidence

| official signal | 점수 |
|---|---:|
| `official_conflict` | +50 |
| `neither_supported` | +45 |
| `primary_supported` | +40 |
| `secondary_supported` | +40 |
| `both_supported` | +35 |
| `mixed_support` | +30 |

#153의 fail-closed 계약을 그대로 사용한다.
`official_conflict`는 source authority를 선택하지 않고 조사 우선순위만 올린다.

### 4.3 최고금리 절대 차이

| 절대차이 | 점수 |
|---|---:|
| >= 1.00%p | +30 |
| >= 0.50%p | +24 |
| >= 0.20%p | +16 |
| >= 0.10%p | +10 |
| > 0 | +5 |

### 4.4 source 기준일 간격

`rate_mismatch_date_diff`일 때만 추가한다.

| 기준일 gap | 점수 |
|---|---:|
| >= 365일 | +18 |
| >= 90일 | +12 |
| >= 30일 | +8 |
| >= 7일 | +4 |

### 4.5 stale effective date

report 생성일 대비 두 source 중 더 오래된 `source_effective_at`을 본다.

| age | 점수 |
|---|---:|
| >= 365일 | +20 |
| >= 90일 | +12 |
| >= 30일 | +6 |

오래된 공시가 현재행으로 carry-forward되어 있을 위험을 별도로 올린다.

## 5. Priority

기본 threshold:

- `P0`: score >= 80
- `P1`: 55~79
- `P2`: 35~54
- `P3`: < 35

다음 direct official evidence는 점수와 무관하게 `P0`으로 올린다.

- `official_conflict`
- `neither_supported`
- `primary_supported`
- `secondary_supported`

이 override 역시 source authority를 자동 선택하지 않는다.
직접 evidence가 있는 문제를 사람이 먼저 검토하게 하는 queue 규칙일 뿐이다.

## 6. 원인 자동분류

우선순위와 원인분류는 분리한다.

1. `official_conflict`
2. `official_evidence_discrepancy`
3. `same_effective_date_conflict`
4. `stale_source`
5. `material_rate_gap`
6. `freshness_gap`
7. `unknown_effective_date`
8. `incomplete_or_minor_drift`

한 행에 여러 위험신호가 있어도 `classification`은 위 precedence로 대표 원인을 정하고,
세부 근거는 `score_components`에 모두 보존한다.

## 7. 조사행동

분류 결과에 따라 다음 행동을 자동 제안한다.

- 공식 내부 충돌: 상품공시와 시행 공지의 최신성/적용범위 확인
- 공식이 양 source 모두 미지지: FSB/FINLIFE raw payload와 locator 양쪽 재검증
- 공식이 FSB만 지지: FINLIFE 값·기준일 재검증
- 공식이 FINLIFE만 지지: FSB raw artifact 재검증
- 동일 기준일 불일치: 양 source 원문 payload 직접 대조
- stale source: 갱신 누락/carry-forward 확인
- 큰 금리차: 공식 홈페이지 evidence 우선 확보
- 기준일 차이: 정상 publication lag인지 확인

## 8. 정렬 안정성

정렬키:

1. `P0 → P1 → P2 → P3`
2. score 내림차순
3. 절대 금리차 내림차순
4. 기관명
5. 상품명
6. 기간

동일 입력은 항상 동일 queue 순서를 만든다.

동일 기관의 mismatch가 여러 개면 `institution_mismatch_count`를 같이 출력하지만,
행 개수가 많다는 이유로 점수를 가산하지 않는다. 여러 상품이 한 번에 바뀐 기관이
과도하게 상위권을 독점하는 것을 막는다.

## 9. 운영 검증

`source-discrepancy-audit.yml`에서 production R2 snapshot을 runner-local로 복원한 뒤:

1. 기존 3중 discrepancy report 생성
2. official evidence conflict/support 적용
3. priority triage 계산
4. full report + priority queue artifact 생성
5. queue size가 mismatch/incomplete 수와 동일한지 검증
6. `triage_mutates_canonical=false`
7. `triage_selects_authority=false`
8. CI에서 Ruff / full pytest / empty DB migration 확인

Production snapshot의 실제 `P0/P1/P2/P3` 개수와 top queue는 PR runtime evidence에 기록한다.

## 10. Non-goals

이번 단계에서 하지 않는다.

- mismatch 자동 수정
- 공식 홈페이지 crawler
- source precedence 변경
- 영구 product alias registry
- unmatched/source-only identity 자동 merge
- Strategy UI 경고표시
- 자동 Issue 생성

다음 단계는 이 queue의 상위 항목부터 공식 evidence를 확장하는 것이다.
