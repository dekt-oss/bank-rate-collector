# Strategy Size Peer v1

작성: 2026-09-05  
상태: **IMPLEMENTATION LOCKED**

> 이 문서는 `docs/specs/20260904-strategy-rate-decision-simulator-v1.md` §9.2가 요구한 별도 규모-peer 계약이다. 금융 계산 의미를 바꾸려면 코드보다 이 문서를 먼저 수정한다.

## 1. 목적과 비목적

Size Peer는 **기관 규모가 비슷한 경쟁기관을 찾는 별도 분석축**이다.

다음과 구분한다.

- Relative Pricing R1 peer: 가입가능범위·대표금리·identity/freshness gate를 통과한 **가격 경쟁기관**
- Size Peer v1: 총자산·수신잔액의 2축이 동일 시점에 관측된 기관 중 **규모가 비슷한 기관**

Size Peer를 Relative Pricing R1의 peer membership, 대표금리, pricing decision gate에 섞지 않는다. Size Peer 결과가 R1 peer를 추가·제거하거나 R1 rank를 변경해서는 안 된다.

## 2. Eligibility universe — 규모 계산보다 먼저 적용

규모 유사도는 eligibility universe 안에서만 계산한다. `eligible → pair-complete → rank` 순서를 바꾸지 않는다.

### 2.1 비대면 / 원격 가입

- 저축은행: 전국 저축은행 전체를 institution universe로 둔다.
- 상호금융: 비대면 가입 가능성이 **사실 데이터로 확인된 기관만** 포함한다.
- `any`, `unknown`, 누락 channel을 비대면 가능으로 추정하지 않는다.
- 다중 가입채널을 하나의 `ANY`로 축약한 값만으로 remote eligibility를 승인하지 않는다. 가능한 경우 원시/정규화 channel set을 보존해 판정한다.

### 2.2 대면 가입

기준점은 부산 동구이며, 행정구역 경계 인접 그래프의 최대 2-hop을 사용한다. 거리(km), 직선반경, 이동시간으로 대체하지 않는다.

v1 대상 구:

`동구, 남구, 부산진구, 서구, 중구, 연제구, 수영구, 동래구, 사상구, 북구, 사하구`

기관 포함 근거는 지점/영업점 소재지 또는 해당 기관이 그 지역에서 영업·가입 가능하다는 factual source여야 한다. 단순 검색지역·기관명 추정으로 지점 주소를 만들어내지 않는다.

## 3. 규모축

반드시 아래 2개를 함께 사용한다.

1. `total_assets` — 총자산
2. `deposit_liabilities_total` — 수신잔액/예수부채의 canonical funding metric

규칙:

- 두 값 모두 `> 0`이어야 한다.
- missing/unknown을 `0`으로 대체하지 않는다.
- 단위는 canonical `million_krw`로 정규화한다.
- 같은 canonical institution identity에 귀속되어야 한다.
- 동일 `source_effective_month`의 두 metric이 모두 있는 **pair-complete snapshot**만 계산한다.
- 서로 다른 월의 자산과 수신잔액을 조합하지 않는다.
- 비교군 전체도 가능한 한 하나의 common comparison month를 사용한다. 공통월이 성립하지 않으면 definitive peer 결과를 만들지 않는다.

## 4. Distance contract

각 기관 `i`에 대해 당사 기준기관 `o`와 다음 값을 계산한다.

```text
asset_gap(i)   = abs(ln(total_assets_i / total_assets_o))
funding_gap(i) = abs(ln(deposit_liabilities_total_i / deposit_liabilities_total_o))
worst_axis_gap(i) = max(asset_gap(i), funding_gap(i))
sum_gap(i)        = asset_gap(i) + funding_gap(i)
```

정렬 순서:

1. `worst_axis_gap` 오름차순
2. `sum_gap` 오름차순
3. stable canonical institution identity 오름차순

의미:

- 비율의 방향에 대칭이다. 예: 2배와 1/2배의 gap이 같다.
- 두 축 중 더 멀리 떨어진 축을 먼저 최소화한다.
- 임의 가중치를 두지 않는다.

### 4.1 Membership cutoff 금지

v1은 ±20%, z-score band, percentile band 같은 임의 membership cutoff를 두지 않는다.

Eligibility와 Evidence Gate를 통과한 전체 universe는 유지하고 **유사도 순위만** 계산한다. UI의 TOP 5/TOP 10 등은 표시 개수일 뿐 금융정책상 peer membership cutoff가 아니다.

## 5. Evidence / identity gate

- 공식 source의 raw identity → canonical identity mapping을 사용한다.
- 이름 유사도만으로 다른 기관에 붙이지 않는다.
- 저축은행 Data.go는 exact `fncoCd`, 필요 시 exact `crno` 계약을 따른다.
- 농축협은 기존 검증된 exact reconciliation 경로를 재사용하며, 총자산 reconciliation은 `metric_code=total_assets`와 대상월에 scope하여 기존 funding history를 변경하지 않는다.
- aggregate/sector-total/regional-total pseudo-row는 institution peer 후보가 아니다.
- revision persistence에서 metric code가 다르면 서로 current revision을 닫지 않는다.

## 6. Source coverage와 fail-closed

v1 구현 시점에 total-assets source 계약이 실제로 검증된 업권만 계산 대상으로 사용할 수 있다.

현재 검증 대상으로 허용하는 경로:

- 저축은행: Data.go 금융회사 재무현황의 `자산총계`
- 농축협: Data.go 금융회사 재무현황의 `자산총계`

신협/CU, 새마을금고/KFCC 등에서 total-assets의 exact source/identity/pagination 계약이 아직 production-grade로 검증되지 않았다면:

- 해당 업권의 값을 추정하지 않는다.
- 다른 업권 값으로 대체하지 않는다.
- 전체 상호금융을 포함한 definitive size-peer라고 표시하지 않는다.
- UI/API에는 지원 업권, 공통 기준월, pair-complete coverage를 함께 노출한다.

사용자 선택 universe에 미지원 업권이 포함되어 완전한 비교가 불가능하면 결과를 `부분 커버리지`로 명시하거나 definitive 결과를 fail closed한다. 숨은 제외는 금지한다.

## 7. Persistence / pagination contract

- `InstitutionFundingObservation`의 기존 `metric_code` 자연키를 사용해 `total_assets`를 별도 metric으로 저장한다.
- 별도 DB schema가 필요하지 않으면 추가하지 않는다.
- target asset table은 Data.go의 실제 table-level `totalCount`를 기준으로 pagination한다.
- 기존 funding collector의 `MAX_PAGES=20`을 asset table에 재사용해 전체 coverage를 잘라내지 않는다.
- aggregate 검출 수와 institution row 수를 검증한다.
- 동일 source/month/value 재수집은 idempotent해야 한다.
- production-copy validation에서 기존 `deposit_liabilities_total` row set/hash가 변하지 않아야 한다.

## 8. Strategy UI contract

Size Peer는 R1 pricing peer와 별도 섹션으로 표시한다.

필수 표시:

- 섹션명: `유사규모 기관` 또는 동등한 명확한 표현
- 기관명/업권
- 총자산
- 수신잔액
- 공통 기준월
- 비교 근거 또는 similarity rank
- source coverage 상태

금지:

- Size Peer를 `공식 pricing peer`로 표기
- 부분 coverage를 전국/전체 상호금융 definitive peer로 표현
- 서로 다른 월의 metric을 화면에서 하나의 동시점 비교처럼 표현
- missing 값을 0으로 보여주어 순위에 포함

## 9. Validation gate

merge 전 최소 검증:

1. unit/contract tests
2. production R2 **복사본**에서 migration 적용
3. 기존 funding rows sealing/hash
4. 실제 Data.go 대상월 total-assets 전량 pagination
5. aggregate 제외 및 institution row count 검증
6. exact identity reconciliation 검증
7. same-month pair-complete coverage 산출
8. 같은 데이터를 두 번 저장한 idempotency 검증
9. 기존 funding rows가 불변임을 재검증
10. Strategy 연결 시 desktop/mobile runtime smoke 및 실제 render screenshot 검토

Production DB에 validation용 값을 쓰는 것으로 gate를 대체하지 않는다.
