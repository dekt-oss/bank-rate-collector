# 기관별 수신잔액 관리·가공·표출 계약 — 2026-08-29

- 관련: Issue #222, #239
- 목적: 저축은행·농축협·신협 기관별 수신잔액을 수집 완료 직후 안정적으로 가공·표출할 수 있도록 데이터 계층과 UI 계약을 선고정한다.
- 상태: 구현 전 계약. 실제 전국 데이터 분포가 나오기 전 점수 임계값/등급 컷은 고정하지 않는다.

## 0. 결론

기관별 수신잔액은 별도 집계 테이블에 다시 복제하는 방식보다 다음 4계층으로 관리한다.

1. **L0 Raw evidence** — 원천 응답 원문, immutable provenance
2. **L1 Canonical observation** — `institution_funding_observations`의 현재/과거 revision
3. **L2 Derived read model** — 화면용 계산값. 초기에는 비영속 계산으로 두고 정의가 안정된 뒤에만 cache/materialization 검토
4. **L3 Strategy payload** — `analysis_month`, coverage, quality, peer metrics, rate/funding alignment를 포함한 UI 계약

원천과 canonical을 분리하고, 파생값은 재계산 가능하게 유지한다. 원천 수정·기관 identity 보정·집계행 제거가 발생해도 derived table을 수작업으로 정리하지 않도록 한다.

## 1. L0 — Raw evidence

원칙:

- 공식 source response bytes를 그대로 보존한다.
- source locator / request metadata / observed_at / checksum을 남긴다.
- aggregate pseudo-row도 원천에 있으면 raw에는 남긴다.
- quarantine된 공시도 raw evidence는 보존한다.
- raw를 dashboard query 대상으로 직접 사용하지 않는다.

이 계층은 "원천이 실제로 무엇을 줬는가"를 증명하기 위한 감사 계층이다.

## 2. L1 — Canonical observation

현재 `institution_funding_observations`를 기관별 수신잔액의 source-of-truth로 유지한다.

필수 계약:

- natural key: `source_id + source_institution_key + metric_code + source_effective_month`
- active row: `valid_to IS NULL`
- source value가 바뀌면 overwrite하지 않고 revision 증가
- 동일값 재수집은 revision을 만들지 않음
- institution identity가 검증된 row만 institution ranking/peer calculation에 사용
- aggregate/region/sector pseudo-row는 institution population에서 제외
- source collision이 발생하면 precedence를 임의 결정하지 않고 fail-closed
- unit은 canonical unit으로 정규화하되 `source_unit`/`source_value_text`를 유지

### 2.1 데이터 상태 분류

각 active observation은 read model에서 다음 중 하나로 해석한다.

- `usable_exact`: exact institution identity + 검증된 metric/basis
- `stale`: 값은 유효하나 해당 업권의 expected cadence보다 오래됨
- `quarantined_history`: raw는 있으나 기간/표/identity 충돌로 canonical 제외
- `unmapped`: source row는 있으나 institution identity 미확정
- `missing`: 해당 기준월에 검증된 observation 없음
- `source_collision`: 동일 모집단에 복수 source가 active하여 임의 합산 금지

## 3. 주기 차이를 숨기지 않는다

실제 원천 주기가 다르므로 모든 업권에 1M 성장률을 강제로 만들지 않는다.

### 저축은행

- 원천이 월별 관측을 제공하는 범위에서는 1M/3M/6M/12M 계산 가능
- Strategy 공통 비교에는 6M/12M 우선

### 농·축협

- 실제 수집 evidence상 반기 관측 중심
- 공통 지표: 6M/12M
- 1M/3M은 계산하지 않음

### 신협

- 정기/상반기 결산 공시 기반
- 공통 지표: 6M/12M
- 1M/3M은 계산하지 않음

따라서 UI에서 `1개월 성장률`을 업권 공통 KPI로 쓰지 않는다.

## 4. 분석 기준월 resolver

세 가지 월을 분리한다.

### `sector_latest_month`

업권별로 검증된 기관 observation이 충분한 가장 최근 월.

### `common_analysis_month`

비교 대상 업권들이 동시에 비교 가능한 가장 최근 공통월.

### `leading_signal_month`

ECOS 실현금리 또는 공시금리처럼 더 최신인 신호의 월.

UI에서 서로 다른 월을 같은 행의 동월 데이터처럼 표현하지 않는다.

## 5. Coverage gate

업권별 기관수 분모를 먼저 정한다.

예:

- `eligible_institutions`: exact identity로 비교 가능한 전체 기관
- `observed_institutions`: 기준월 observation 보유 기관
- `coverage_ratio = observed / eligible`

coverage가 기준 미만이면:

- sector ranking/percentile을 숨긴다.
- 합계 또는 성장률을 `부분집계`라고 표시한다.
- 특정 기관 값 자체는 provenance와 함께 보여줄 수 있다.

정확한 coverage threshold는 전국 실데이터 분포 확인 후 확정한다.

## 6. L2 — Derived read model

초기에는 별도 영속 테이블을 만들지 않고 active canonical observation에서 재계산한다.

기관별 기본 row:

```text
institution_id
sector
analysis_month
balance_million_krw
balance_6m_ago
balance_12m_ago
change_6m_amount
change_6m_pct
change_12m_amount
change_12m_pct
sector_balance_percentile
sector_growth_6m_percentile
sector_growth_12m_percentile
sector_median_growth_6m
relative_growth_6m_vs_peer_median
sector_total_growth_6m
relative_growth_6m_vs_sector_total
source_id
source_effective_month
observation_basis
population_scope
coverage_status
quality_status
```

### 6.1 성장률

`growth_h = current / prior_h - 1`

조건:

- prior period가 정확히 존재할 때만 계산한다.
- 월 간격이 맞지 않으면 근접월로 보간하지 않는다.
- 값 0 또는 비정상 분모는 fail-closed.

### 6.2 규모 percentile

같은 `sector + analysis_month + usable_exact population` 안에서만 계산한다.

다른 업권의 절대규모를 섞어 percentile을 만들지 않는다.

### 6.3 성장 percentile

동일한 horizon을 실제로 계산할 수 있는 기관만 모집단에 포함한다.

예: 6M 성장률이 없는 기관을 0% 성장으로 취급하지 않는다.

### 6.4 상대성장

두 개를 분리한다.

- `vs_peer_median`: 기관 성장률 - 동일 업권 기관 중앙값
- `vs_sector_total`: 기관 성장률 - 동일 업권 전체 합계 성장률

둘을 하나의 점수로 섞지 않는다.

## 7. 금리와 수신잔액 결합

목적은 "금리를 올렸더니 예금이 늘었다"는 인과 주장이 아니다.

표현은 **rate/funding response association**으로 제한한다.

### 공통 정렬

- institution identity exact match
- advertised rate는 동일 업권/상품/기간 scope로 제한
- funding balance는 해당 기관의 검증된 reporting month
- monthly funding이 없는 업권은 월별 T+1/T+2 반응을 만들지 않음

### 저축은행

월별 funding이 충분하면:

- T0 / T+1 / T+2
- 3M / 6M / 12M

### 농·축협 / 신협

반기 공시 기반에서는:

- 직전 6M 금리 변화
- 다음 6M balance change
- 12M 변화

즉 같은 chart를 쓰더라도 response window label은 업권별 cadence를 따른다.

## 8. 실제 화면 구성

### A. 오늘의 수신 브리핑

최상단에서는 숫자를 많이 보여주지 않는다.

- 업권 자금 방향: ECOS sector total
- 실현 신규취급금리: ECOS
- 공시금리 경쟁 강도: 기존 collector
- 기관 funding coverage 상태

기관별 D1이 완성되면 당사/peer funding position을 추가한다.

### B. 업권별 수신시장 흐름

기본 차트:

- 절대 잔액 small multiple 또는 index=100
- 6M/12M 변화 heat row
- 업권별 latest month와 coverage badge

은행/저축은행/신협/새마을금고/광의 상호금융의 population 차이는 metadata로 노출한다.

### C. 기관별 수신 포지션

표 기본 컬럼:

| 기관 | 잔액 | 규모 백분위 | 6M 증감 | 12M 증감 | 동종 6M 대비 | 데이터 기준월 |
|---|---:|---:|---:|---:|---:|---|

정렬:

- 잔액 규모
- 6M 성장률
- 12M 성장률
- peer-relative growth

### D. Peer matrix

가장 실무적인 비교화면 후보:

- x축: 12개월 대표 공시금리
- y축: 6M 수신잔액 증감률
- bubble size: 수신잔액 규모
- 색/그룹: 업권 또는 선택 peer group

해석 예:

- 고금리 + 고성장
- 고금리 + 저성장
- 저금리 + 고성장
- 저금리 + 저성장

이 사분면은 설명용 분류이며 성과의 인과판정으로 사용하지 않는다.

### E. 기관 Detail drawer

기관을 클릭하면:

- 수신잔액 history
- 6M/12M 변화
- 공시 대표금리 history
- rate/funding overlay
- source / basis / 기준월 / coverage / warning

를 보여준다.

### F. Action Center

실데이터 분포 확인 후 아래와 같은 rule-based candidate를 만들 수 있다.

- 수신 감소 + 금리 상위권
- 수신 증가 + 금리 중하위권
- 수신규모 대형 + 성장 둔화
- peer 대비 성장률 급변

하지만 임계값은 전국 데이터의 percentile/IQR 분포를 본 뒤 확정한다.

## 9. 하지 않을 것

- 합계행을 기관처럼 ranking에 포함
- missing 값을 0으로 채움
- 반기 데이터를 월별로 선형보간
- 6월 balance와 7월 rate를 동월 값처럼 조합
- 농협 광의 업권 ECOS를 개별 농·축협 합계와 동일 모집단으로 간주
- 이름 fuzzy match만으로 institution funding 연결
- 공시금리와 수신잔액 상관을 `금리 인상 효과`라고 표현
- 데이터 분포 확인 전 종합점수 0~100과 임계값을 고정

## 10. 수집 완료 직후 실행 순서

1. source별 active row count / distinct institution / month coverage
2. aggregate pseudo-row active=0 검증
3. duplicate natural-key=0 검증
4. source collision=0 검증
5. exact identity coverage
6. month-by-month eligible/observed coverage matrix
7. sector total reconciliation with ECOS where population is comparable
8. 6M/12M growth availability 분포
9. outlier / revision / stale population 조사
10. L2 read-model 구현 및 fixture/runtime 검증
11. Strategy payload 추가
12. desktop/mobile 화면 구현
13. production-data runtime smoke 후 publish

## 11. 첫 UI release 범위

첫 버전은 과도한 지표를 만들지 않는다.

1. 기관별 잔액
2. 6M 증감액/증감률
3. 12M 증감액/증감률
4. 동일 업권 규모 percentile
5. 동일 업권 6M 성장 percentile
6. peer median 대비 상대성장
7. 대표 공시금리와 6M funding change peer matrix
8. 데이터 기준월/coverage/source badge

이 8개가 실사용에 충분히 유효한지 확인한 뒤 종합 score나 조달압력지수를 검토한다.
