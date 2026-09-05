# Strategy Size Peer / Total Assets v1

상태: **IMPLEMENTATION LOCKED — persistence/release는 Evidence Gate 통과 전 fail-closed**  
작성일: 2026-09-05

## 0. 목적

금리결정 시뮬레이터에서 `규모가 비슷한 금융기관`을 공식 Relative Pricing pricing peer와 분리해 제공한다.

size peer는 금리순위 비교군이 아니다. 먼저 실제 가입 가능성이 있는 institution universe를 정하고, 그 안에서 **수신잔액 + 총자산**이 모두 검증된 기관만 규모 비교 대상으로 사용한다.

## 1. 불변 계약

1. 공식 Relative Pricing pricing peer와 size peer는 별도 policy / payload / UI label을 사용한다.
2. size-peer eligibility와 금융규모 similarity는 분리한다.
3. size axis는 정확히 두 개다: `deposit_liabilities_total`, `total_assets`.
4. 어느 한 축이 없으면 size peer 후보가 아니다. 0으로 대체하거나 funding-only peer로 fallback하지 않는다.
5. institution identity는 canonical institution id에 exact official identifier를 연결한다. 이름 유사도만으로 결합하지 않는다.
6. 금액은 canonical `million_krw`로 정규화하되 source value/unit을 보존한다.
7. 서로 다른 reporting vintage를 동시점처럼 표시하지 않는다.
8. sector/region aggregate pseudo row를 기관 observation으로 승격하지 않는다. aggregate 의미를 검증하지 못하면 해당 source/month를 fail closed한다.
9. 가입채널 `any` / `unknown`을 비대면 가입 가능으로 추정하지 않는다.
10. size peer가 unavailable이면 UI는 이유를 표시한다. 다른 peer 정책을 자동 대체하지 않는다.

## 2. 가입 가능 universe

### 2.1 `REMOTE`

선택 상품/시나리오에 비대면 가입 조건이 있을 때:

- **저축은행:** 전국 전체 institution universe를 허용한다.
- **신협 / 새마을금고 / 농·축협:** 해당 기관/상품의 인터넷·모바일·스마트폰 등 비대면 가입 가능성이 공식 source evidence로 확인된 경우만 허용한다.
- normalized `JoinChannel.ANY`만으로는 비대면 근거가 아니다. 원 source의 channel set을 복원·보존해야 한다.
- `unknown`, 이름 패턴, 상품명 추정만으로 remote eligibility를 만들지 않는다.

### 2.2 `BRANCH_BUSAN`

대면 가입 조건일 때 비교 universe는 **부산광역시 전체**다.

- 동구 인접구/2-hop 경계 규칙은 사용하지 않는다.
- 후보 기관은 부산광역시 16개 구·군 중 하나에 공식 점포/영업점 주소 또는 동등한 구·군 단위 가입가능 evidence가 있어야 한다.
- 시도 단위 조회근거만 있고 실제 점포/구·군 근거가 없는 row는 자동 포함하지 않는다.
- FSB 금리는 본점기준 공시라는 원래 의미를 유지한다. 부산 점포가 있다는 사실과 금리 적용범위를 혼동하지 않는다.
- 부산시 전체 범위는 다음 16개 구·군으로 고정한다.

```text
강서구
금정구
기장군
남구
동구
동래구
부산진구
북구
사상구
사하구
서구
수영구
연제구
영도구
중구
해운대구
```

부산 밖 주소는 `outside_busan`으로 fail closed한다.

행정구역 변경 시 이 상수와 contract test를 함께 version-up한다.

## 3. 재무 metric source contract

### 3.1 저축은행 — Data.go

- source: existing `data_go_savings_bank_funding` finance endpoint / dataset `15061316`.
- total assets: code `A`, label `자산총계`, amount field `astSmryStfnpsAcitCdAmt`.
- source unit: KRW integer; canonical unit: `million_krw`.
- identity: existing exact FSS `fncoCd`, secondary `crno` policy를 유지한다.
- `030350S` sector-total 등 aggregate는 **total-assets metric 자체로** identity + exact-sum 검증 후 제외한다. funding metric에서 통과했다는 이유로 asset aggregate 의미를 가정하지 않는다.

2026-09-05 authenticated read-only evidence:

- 최신 확인 가능 기준월: `2026-03` (`2026-06`, `2026-09`은 no rows)
- raw finance rows: `52,240`
- `A / 자산총계` rows: `80`
- 실제 기관: `79`, unique official key도 `79`
- `030350S` aggregate: `1` row
- 실제 기관 총자산 합계 = sector total = `119,269,920.000000 million_krw`
- 고려저축은행: `fncoCd=0010390`, `crno=1801110015304`, 총자산 `2,094,142.000000 million_krw`

### 3.2 농·축협 — Data.go

- source: existing `data_go_agri_coop_funding` finance endpoint / dataset `15061344`.
- total assets: code `A`, label `자산총계`, amount field `astSmryBlnshClsfAmt`.
- source unit: KRW integer; canonical unit: `million_krw`.
- actual local coop / regional aggregate / sector aggregate partition을 total-assets 기준으로 별도 검증한다.
- 중앙회/aggregate는 local institution peer로 승격하지 않는다.

2026-09-05 authenticated read-only evidence에서 **funding aggregate 의미와 total-assets aggregate 의미가 다름**이 확인됐다.

- 최신 확인 가능 기준월: `2025-12` (`2026-06`은 no rows)
- raw finance rows: `177,908`
- `A / 자산총계` rows: `1,126`
- 실제 local institutions: `1,109`, unique official key도 `1,109`
- current aggregate rows: `17` = 16 regional totals + `030801S` sector total
- 실제 기관 총자산 합계 = `563,075,215.088950 million_krw`
- 16 regional totals 합계 = `563,075,215.088950 million_krw`
- `030801S` sector total = `563,075,215.088950 million_krw`
- 따라서 total-assets current hierarchy는 `regional_total == institution_total` 및 `sector_total == institution_total`이다.
- funding에서 검증된 `sector_total == institution_total + regional_total` 규칙을 total-assets에 재사용하면 안 된다.
- 17 aggregate rows를 단순 합산하면 기관 실총액의 2배가 되므로 기관 규모 계산에는 절대 포함하지 않는다.
- legacy aggregate key의 total-assets 의미는 아직 실증하지 않았으므로 fail closed한다.

### 3.3 신협 — 신협중앙회 경영공시

- current main에는 production-enabled CU funding collector가 없으므로 과거 미머지 구현을 자동 승격하지 않는다.
- 과거 공식 경영공시 artifact 196개를 다시 검사한 결과 **196/196**에서 `자산합계`와 `예수부채`가 각각 정확히 1행 존재하고 duplicate/missing이 0건이었다.
- 향후 collector는 active `cu:<cuIngno>` identity와 동일 공시기간을 사용해 `자산합계` / `예수부채`를 metric-aware하게 읽는다.
- production persistence는 current-main integration / coverage / identity를 새 Evidence Gate에서 재검증한 뒤 활성화한다.

### 3.4 새마을금고

- 중앙회 공식 금융통계/재무통계 source 존재는 확인했다.
- exact request / field / pagination / institution-key contract는 아직 미확정이다.
- 검증 전에는 `total_assets_unverified_source`로 fail closed한다.

## 4. 가입채널 evidence 보존

FSB 원문 `JOIN_LOCATION`은 `1,2,3`처럼 복수 채널을 직접 준다. 현재 generic parser의 `JoinChannel.ANY`는 이 집합을 압축하므로 size-peer eligibility에 그대로 쓰면 안 된다.

v1 원칙:

- source-declared channel set을 factual evidence로 별도 보존한다.
- canonical remote member는 `internet` 또는 `mobile`이 **명시적으로** 포함될 때만 true다.
- `any`는 remote=true의 동의어가 아니다.
- CU/KFCC/NH도 source가 제공하는 실제 가입채널 evidence만 동일 정책으로 normalise한다.

## 5. temporal alignment

- 한 institution의 두 size axis는 같은 reporting period를 우선 요구한다.
- 최신 원천 기준월은 현재 저축은행 `2026-03`, 농·축협 `2025-12`로 다르다.
- 서로 다른 latest vintage를 동시점 cross-sector 규모 비교에 바로 사용하지 않는다.
- 업권 간 exact common month를 먼저 측정하고, common vintage가 존재하지 않는 경우에만 허용 lag 정책을 별도 evidence로 검토한다.
- lag policy 확정 전에는 cross-sector size ranking을 `ready`로 생성하지 않는다.
- UI에는 `funding_as_of`와 `assets_as_of`를 각각 보존한다.

## 6. size similarity

- eligibility universe와 two-axis completeness를 먼저 결정한다.
- 실제 고려저축은행 및 eligible population의 `(funding, assets)` 분포를 evidence artifact로 산출하기 전에는 ±20%, Euclidean, z-score, 임의 N을 정책으로 고정하지 않는다.
- 기존 `institution_funding_direct_peer`의 same-sector / log-balance / N=16 정책은 재사용하지 않는다.
- 최종 similarity policy는 두 축 모두에서 왜 peer인지 사람이 설명할 수 있어야 한다.
- policy id/version, 각 축 distance, total distance를 payload에 남긴다.

## 7. Evidence Gate

read-only diagnostic Action은 production R2를 **절대 upload/mutate하지 않는다**.

필수 artifact:

- source / period별 raw row count
- total-assets contract row count
- unique official institution key count
- aggregate candidate key / name / value
- institution-only sum vs aggregate validation
- canonical mapped / unmapped count
- 고려저축은행 total assets + funding + 각각의 as-of
- eligible `REMOTE` / `BRANCH_BUSAN` universe count by sector
- complete two-axis candidate distribution
- missing reason histogram

현재 B-source gate에서 저축은행·농축협 total-assets source/aggregate 검증은 통과했다. 그러나 canonical mapping, two-axis distribution, CU/KFCC source completion은 아직 남아 있으므로 persistence / similarity selection / UI `ready` 상태를 만들지 않는다.

## 8. UI contract

시뮬레이터의 `유사 규모 peer` 블록은 다음을 표시한다.

- 상태: `ready` / `insufficient_data`
- peer institution / sector
- 수신잔액 / 총자산
- 각 기준월
- 규모 유사성 근거
- 가입가능 universe mode (`REMOTE` / `BRANCH_BUSAN`)
- 공식 pricing peer와 별도 정책임을 명시

unavailable reason 예:

- `total_assets_missing`
- `remote_eligibility_unverified`
- `local_outlet_evidence_missing`
- `outside_busan`
- `temporal_alignment_unresolved`
- `institution_identity_unmapped`
- `aggregate_validation_failed`
- `total_assets_unverified_source`

## 9. 구현 순서

A. eligibility universe pure service + 부산 전체 branch contract  
B. source/evidence total-assets parser + read-only evidence workflow  
C. two-axis read model + temporal gate  
D. real production distribution 기반 similarity policy 확정  
E. Strategy payload/UI 연결  
F. production-data browser QA 및 운영 수집 활성화
