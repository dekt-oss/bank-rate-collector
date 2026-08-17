# 전략 대시보드 상호금융 확장 Evidence Gate

```yaml
document_type: evidence_gate
status: decision
created_at: 2026-08-17
target_repository: dekt-oss/bank-rate-collector
base_commit: 33583cb8203deea22ca8dbec3fbaae4d0c1e2e4d
issue: 108
runtime_change: false
release_gate_change: false
```

## 1. 결론

### 판정

- **신협 + 새마을금고 + 농·축협을 하나의 `최고금리` TOP5/TOP10으로 합치는 안: NO-GO**
- **상호금융이라는 선택 UI 자체: CONDITIONAL GO**
- **현재 전략 Release Gate에 세 업권을 즉시 추가: NO-GO**

이유는 두 가지다.

1. 세 업권의 `max_rate` 의미와 제공 범위가 동일하지 않다.
2. 현재 전략 stable product identity key로는 새마을금고와 농·축협의 일부 행이 매칭되지 않는다.

따라서 `max_rate ?? base_rate` 같은 fallback으로 하나의 “최고금리” 랭킹을 만드는 것은 금지한다. 값이 존재한다는 이유만으로 서로 다른 의미의 금리를 같은 축에 놓지 않는다.

## 2. Evidence 범위

2026-08-17 production DB snapshot을 **로컬 read-only copy**로 복원해 검사했다.

- snapshot: `state/snapshots/20260817T130521-e43ff2e2.sqlite3.gz`
- snapshot timestamp: `2026-08-17T04:05:21.527989+00:00`
- canonical table: 326,699 rows
- Evidence 대상:
  - `kfcc` 새마을금고
  - `cu` 신협
  - `nh_local` 농·축협
  - `product_type=term_deposit`
  - 6 / 12 / 24 / 36개월
- 금리/coverage evidence run: GitHub Actions `31993793485` — success
- identity evidence run: GitHub Actions `31994072146` — success

DB나 외부 원천은 수정하지 않았다.

## 3. Production 금리 계약 비교

| 업권 | 대상 행 | base_rate | max_rate | rate_scope | geo_basis | district |
|---|---:|---:|---:|---|---|---:|
| 새마을금고 (`kfcc`) | 24,464 | 24,464 (100%) | **0 (0%)** | institution | outlet_address | 24,358 |
| 신협 (`cu`) | 15,178 | 15,178 (100%) | **15,178 (100%)** | institution | source_query_region | 0 |
| 농·축협 (`nh_local`) | 73,020 | 73,020 (100%) | **0 (0%)** | outlet | outlet_address | 72,330 |

### 해석

#### 새마을금고

공식 금리표와 현재 adapter 계약은 기본이율 중심이다. `provides_max_rate=False`다. Production canonical에서도 대상 24,464행의 `max_rate`는 전부 비어 있다.

#### 신협

공식 원천이 기본금리와 최고 우대금리를 함께 제공하며 현재 adapter도 `provides_max_rate=True`다. Production 대상 15,178행에서 `max_rate`가 100% 존재한다.

#### 농·축협

점포별 기본금리를 수집하고 별도 우대금리 행이 상품 형태로 존재할 수 있으나, 현재 adapter의 공통 `max_rate` 필드는 제공하지 않는다. `provides_max_rate=False`이며 Production 대상 73,020행의 `max_rate`는 전부 비어 있다.

### 금지되는 구현

아래는 사용하지 않는다.

```text
score = max_rate if max_rate is not null else base_rate
```

이 방식은 신협에서는 최고 우대금리, 새마을금고·농축협에서는 기본금리가 되어 같은 숫자 열 안에 서로 다른 금융 의미를 섞는다.

실제 12개월 데이터에 이 fallback을 적용하면 새마을금고 `Block예금 6.0%` 같은 **기본금리**가 신협의 **최고 우대금리**와 같은 랭킹에 올라간다. 이는 전략 화면의 의사결정 의미를 훼손한다.

## 4. 기간 coverage

| 업권 | 6개월 | 12개월 | 24개월 | 36개월 |
|---|---:|---:|---:|---:|
| 새마을금고 | 7,555 | 8,355 | 4,464 | 4,090 |
| 신협 | **0** | 6,414 | 4,645 | 4,119 |
| 농·축협 | 14,604 | 19,472 | 19,472 | 19,472 |

신협 6개월은 현재 production canonical에 대상 행이 없다. UI에서 빈 기간을 조용히 숨기지 말고 `공시/수집 0건`으로 구분해야 한다.

## 5. 지역·지도 의미

세 업권을 한 지도로 바로 합치면 안 된다.

| 업권 | 지역 의미 | 지도 해석 |
|---|---|---|
| 새마을금고 | `outlet_address` | 실제 주소 기반 지역 |
| 신협 | `source_query_region` | 원천 조회조건 지역; 점포 주소가 아님 |
| 농·축협 | `outlet_address` | 실제 점포 주소 기반 지역 |

특히 신협은 district가 0건이다. 새마을금고·농축협의 구·군 주소 분포와 같은 세밀도로 비교해서는 안 된다.

향후 지도는 최소한 `geo_basis`를 UI/집계 계약에 포함하고, 서로 다른 basis를 같은 지역 평균으로 섞지 않아야 한다.

## 6. availability / 가입범위 의미

- 새마을금고: `local_members` 23,429행 / `workplace_members` 1,035행
- 신협: `local_members` 15,178행
- 농·축협: `unknown` 73,020행

단순 금리순 정렬만으로 “실제 가입 가능한 경쟁상품”을 뜻한다고 볼 수 없다. 상호금융 mode에서는 availability scope를 필터 또는 최소한 배지/coverage 설명으로 노출해야 한다.

## 7. Freshness / 수집 안정성

Evidence 당시 최신 정상 수집:

- 새마을금고: 2026-08-16 시작 run, valid 93,367 / errors 0
- 신협: 2026-08-16 시작 run, valid 30,541 / warnings 46 / errors 0
- 농·축협: 2026-08-16 시작 run, valid 198,670 / warnings 19,472 / errors 0

최근 5회에서 새마을금고·신협은 모두 success였다. 농·축협은 2026-08-11 run 1회가 failed였고 이후 정상 수집이 이어졌다.

상호금융 mode를 만들 경우 업권별 `last successful effective date`, coverage, warning 상태를 화면에서 분리해 보여야 한다.

## 8. Stable identity Gate

### source_entity_links

현재 active source key 중 중복은 세 업권 모두 0건이었다.

- 새마을금고: institution 1,232 / outlet 3,133 / product 18,369
- 신협: institution 848 / product 7,906
- 농·축협: institution 4,869 / outlet 4,869 / product 53,170

이는 source-level active identity uniqueness가 깨진 상태는 아니라는 뜻이다.

### 현재 strategy `_row_key`로 product_id 재매칭

현재 `strategy_contract_service`의 identity key를 production canonical 대상 행에 그대로 적용한 결과:

| 업권 | 대상 행 | matched | unmatched | unique product_id |
|---|---:|---:|---:|---:|
| 신협 | 15,178 | **15,178** | **0** | 3,260 |
| 새마을금고 | 24,464 | 22,289 | **2,175** | 5,834 |
| 농·축협 | 73,020 | 71,685 | **1,335** | 19,116 |

따라서 현재 저축은행 전략 build의 “target universe는 product_id 미매칭 0건이어야 한다”는 Gate를 세 업권 전체에 그대로 확대하면 새마을금고와 농·축협은 실패한다.

이 미매칭을 이름 fallback으로 조용히 통과시키지 않는다. 원인을 별도 identity 작업에서 해소하거나, 대상 universe를 명시적으로 제한해야 한다.

## 9. 권고 Target Architecture

### 9.1 UI mode

향후 다음 mode 자체는 허용할 수 있다.

```text
저축은행
상호금융
저축은행 + 상호금융
```

단, **mode와 metric basis를 분리**해야 한다.

### 9.2 상호금융 mode의 공통 metric

현재 세 업권 모두 100% 제공하는 공통 금리 필드는 `base_rate`다.

따라서 세 업권을 한 랭킹으로 합치려면 이름부터 명시적으로:

```text
기본금리 비교
```

로 해야 한다.

`최고금리 비교`는 신협만 현재 공통 계약이 있고 새마을금고/농·축협에는 없다. 이 경우에는 업권별 panel을 분리하거나 지원 업권만 표시해야 한다.

### 9.3 저축은행 + 상호금융 mode

현재 PR에서는 구현하지 않는다.

혼합 mode를 만들기 전 아래를 추가 Evidence Gate로 고정한다.

1. 저축은행과 상호금융 전 업권에 공통인 metric basis 선택
2. 해당 metric의 source semantics 및 NULL coverage 확인
3. product representative denominator 정의
4. 업권별 availability scope 차이 표출
5. geo_basis가 다른 행을 지도에서 어떻게 처리할지 정의

이 Gate 없이 기존 저축은행 `최고금리` KPI/TOP5에 상호금융을 단순 append하지 않는다.

## 10. 구현 전 필수 작업

### A. Identity

- 새마을금고 2,175행 미매칭 원인 분류
- 농·축협 1,335행 미매칭 원인 분류
- sector별 target identity contract 정의
- target universe unmatched=0 build Gate 유지

### B. Metric contract

- `metric_basis = base_rate | max_rate`를 화면/집계 계약에 명시
- 공통 비교에서는 fallback 금지
- 지원하지 않는 metric은 업권별 `미제공`으로 표출

### C. Coverage contract

- sector별 분모·상품 대표 단위 정의
- CU 6개월 0건 상태 정의
- last-success/freshness badge
- `availability_scope` 표시

### D. Geography

- `geo_basis`별 지도 의미 분리
- query-region과 outlet-address를 같은 district drill-down으로 합치지 않음

## 11. 이번 Evidence PR 범위

포함:

- Production Evidence 결과 문서화
- 향후 구현 Gate/계약 정의

제외:

- 전략 universe 확대
- 화면에 상호금융 selector 추가
- 금리 계산 변경
- DB/schema/migration 변경
- source adapter 변경
- identity fallback 추가
- Release Gate 변경

## 12. 최종 의사결정

현재 바로 구현 가능한 것은 **“상호금융을 선택할 수 있는 UI의 설계”**까지다.

하지만 실제 데이터 universe를 켜기 위해서는 먼저:

1. 새마을금고·농축협 identity 미매칭 해소
2. `기본금리`와 `최고금리`를 명확히 분리하는 metric contract
3. sector-aware geography/coverage contract

가 필요하다.

즉, 이번 Gate의 핵심은 **상호금융 확장을 포기하는 것이 아니라 잘못된 하나의 숫자로 섞는 것을 차단하고, 안전하게 확장할 수 있는 경계를 확정하는 것**이다.
