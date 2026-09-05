# Size Peer Current Eligibility Evidence — 2026-09-05

상태: **AUTHENTICATED PRODUCTION-COPY + LIVE SOURCE EVIDENCE — similarity cutoff/N 미확정**

## 1. 목적

`Strategy → 금리결정 시뮬레이터 → 유사 규모 peer`의 institution universe를 실제 가입가능성 근거로 제한한다.

재무규모는 PR #309에서 검증한 exact common vintage `2025-12`의 `deposit_liabilities_total + total_assets`를 사용한다. 가입가능성은 현재 선택상품 조건을 사용한다. 두 시점은 서로 다른 clock이며 한 시점으로 표현하지 않는다.

대표 검증 상품은 **12개월 정기예금**이다.

## 2. 실행/검증

- branch: `feat/strategy-size-peer-eligibility-evidence-v2-20260905`
- final evidence head: `19109272b6fef58942df7775e78bc1e946e63cde`
- full CI: run `33960235171` — **SUCCESS**
- eligibility evidence: run `33960235153`, rerun — **SUCCESS**
- artifact: `size-peer-current-eligibility-evidence`, id `9967816310`

첫 evidence attempt는 Data.go transport timeout으로 exact-common-vintage 재조회 단계에서 실패했다. 같은 head의 failed job rerun에서 동일 read-only 경로가 전부 성공했다. 계약 오류나 값 불일치가 아니라 transient transport failure로 분류한다.

검증 완료:

- full Ruff: PASS
- full pytest: PASS
- empty-DB migration: PASS
- eligibility targeted tests: `7 passed`
- production R2 → runner-local restore: PASS
- runner-local migration: PASS
- Data.go exact common-vintage rebuild: PASS
- live FSB `YN_Busan` 12개월 probe: PASS
- current eligibility overlay: PASS
- production R2 mutate/upload: **없음**

## 3. 시점 계약

- financial size as-of: **`2025-12`**
- eligibility evaluation date: **`2026-09-05`**
- NH current rate source effective max: **`2026-09-03`**
- FSB current rate source effective max: **`2026-09-04`**
- FSB live Busan query date: **`2026-09-05`**

따라서 UI/payload는 `financial_as_of`와 현재 가입가능성의 source/evaluation dates를 각각 표시해야 한다. `2025-12 당시 가입가능 peer`라고 표현하면 안 된다.

## 4. current selected-product gate

PR #309의 financial two-axis candidate는 `1,148`개였다.

현재 active institution은 `1,148`개 모두 유지됐다. 그러나 현재 12개월 정기예금 observation이 확인된 candidate는 **`1,147`개**다.

- savings bank: `66`
- NH local: `1,081`
- 현재 12개월 selected product 미확인: `1`
  - `다압농협`

`다압농협`은 financial candidate에서 지우지 않는다. 현재 selected product universe에서만 제외한다.

## 5. REMOTE universe

### 계약

- savings bank: selected 12개월 상품이 현재 확인되면 nationwide remote universe 허용
- NH local: 현재 selected 상품에 **source-derived `internet`/`mobile` variant가 실제 존재할 때만** 허용
- generic `JoinChannel.ANY`를 remote 근거로 사용하지 않는다.

### NH e-joy 근거 재검토

이번 production snapshot에서 NH 12개월 financial/product candidate `1,081`개 전부에 current `internet` variant가 실제 존재했다.

이 결과는 parser가 `unknown/any`를 임의로 internet으로 승격한 결과가 아니다. 기존 Stage G evidence가 다음을 이미 검증했다.

- 공식 `e-joy 인터넷예금 우대금리` source row: `19,472`
- official BRC: `4,868`
- 대상상품·기간·가산 문구 전수 일관
- 대상상품 deterministic linkage: `111,359 / 111,370`
- ambiguous: `0`
- 12개월 deterministic linkable: `19,362 / 19,364`
- implementation은 base unknown-channel variant를 유지하고 별도 `join_channel=internet` variant만 생성한다.

현재 production에서는 그 source-derived internet variant가 1,081 institution 모두에 최소 1개 존재한다. 따라서 현재 12개월 REMOTE gate 결과를 `1,081 NH + 66 savings`로 인정한다.

### 결과

- eligible: **`1,147`**
- excluded after selected-product gate: `0`

즉 current selected-product candidate 중 REMOTE eligibility가 추가로 탈락한 기관은 없다.

## 6. BRANCH_BUSAN universe

대면 universe는 동구/인접구가 아니라 **부산광역시 전체 16개 구·군**이다.

### NH local

- current 12개월 active rate row
- 공식 outlet address가 부산
- `region_sigungu`가 부산 16개 구·군 master에 포함

위 조건을 모두 만족하는 financial candidate institution: **`16`**

### savings bank

보수적으로 두 evidence를 동시에 요구한다.

1. live FSB `YN_Busan` 12개월 row의 raw `JOIN_LOCATION`에 branch member `1`이 직접 포함
2. exact FSB institution identity에 연결된 active official outlet 중 부산 16개 구·군 주소가 존재

live FSB Busan 12개월 evidence:

- rows: `57`
- institutions: `14`
- explicit branch-capable institutions: `14`
- unknown channel rows: `0`

financial candidate와 exact identity/outlet evidence까지 모두 충족한 savings bank: **`10`**

### 최종 부산 전체 candidate

- NH local: `16`
- savings bank: `10`
- total: **`26`**

26개 기관:

```text
농·축협 16
가락농협
강동농협
금정농협
남부산농협
녹산농협
대저농협
동래농협
동부산농협
명지농협
부경원예농협
부산우유농협
부산축산농협
북부산농협
서부산농협
중부산농협
해운대농협

저축은행 10
고려저축은행
국제저축은행
대신저축은행
동원제일저축은행
솔브레인저축은행
애큐온저축은행
우리저축은행
웰컴저축은행
진주저축은행
흥국저축은행
```

현재 구현은 부산 밖 점포를 비교군에 포함하지 않는다. 다만 `SizePeerUniverseCandidate`가 `sigungu`만 받고 `sido`를 받지 않는 기존 contract 때문에, 부산 외 점포가 있는 기관의 exclusion reason을 `outside_busan`으로 세밀하게 분리하지 않고 `local_outlet_evidence_missing`으로 보수적으로 처리한다. eligibility 결과 자체에는 영향이 없지만 reason taxonomy 개선은 별도 contract change로 남긴다.

## 7. eligibility 적용 후 two-axis 거리 분포

시험 metric은 아직 **selection policy가 아니라 evidence metric**이다.

```text
funding_gap = abs(peer_funding / anchor_funding - 1)
asset_gap   = abs(peer_assets / anchor_assets - 1)
worst_axis_gap = max(funding_gap, asset_gap)
tie_breaker = funding_gap + asset_gap
```

이 방식은 자산이 매우 가까운데 수신잔액이 멀거나 그 반대인 경우, 가까운 한 축이 큰 불일치를 가리지 못하게 한다.

### REMOTE

고려저축은행 제외:

- worst-axis ≤ 2%: `3`
- ≤ 5%: `9`
- ≤ 7.5%: `16`
- ≤ 10%: `22`
- ≤ 15%: `32`
- ≤ 20%: `43`

가장 가까운 상위 사례:

| 기관 | 업권 | 수신 gap | 자산 gap | worst-axis |
|---|---|---:|---:|---:|
| 청주축산농협 | 농·축협 | 0.32% | 0.17% | **0.32%** |
| 천안농협 | 농·축협 | 0.63% | 0.91% | **0.91%** |
| NH저축은행 | 저축은행 | 1.09% | 0.16% | **1.09%** |
| 평택농협 | 농·축협 | 2.49% | 2.75% | **2.75%** |
| 서부농협 | 농·축협 | 1.01% | 3.16% | **3.16%** |

### BRANCH_BUSAN

고려저축은행 제외:

- worst-axis ≤ 2%: `0`
- ≤ 5%: `1`
- ≤ 7.5%: `1`
- ≤ 10%: `2`
- ≤ 15%: `2`
- ≤ 20%: `3`

가장 가까운 사례:

| 기관 | 업권 | 수신 gap | 자산 gap | worst-axis |
|---|---|---:|---:|---:|
| 북부산농협 | 농·축협 | 1.76% | 3.99% | **3.99%** |
| 대신저축은행 | 저축은행 | 5.50% | 8.61% | **8.61%** |
| 금정농협 | 농·축협 | 14.78% | 18.68% | **18.68%** |
| 동부산농협 | 농·축협 | 35.58% | 36.83% | **36.83%** |

부산 universe에서는 3번째와 4번째 사이 worst-axis gap이 약 `18.7% → 36.8%`로 크게 벌어진다. 그러나 이것만으로 `TOP3`, `20%`, `10%`를 영구 정책으로 자동 고정하지 않는다.

## 8. 정책 판단

Evidence가 지지하는 부분:

- **distance metric**으로 `max(relative funding gap, relative asset gap)`를 사용하는 것은 설명 가능하고 두 축 중 한 축의 큰 mismatch를 숨기지 않는다.
- tie-breaker는 두 gap 합을 사용할 수 있다.

Evidence가 아직 지지하지 않는 부분:

- 고정 `±5/10/20%` cutoff
- 고정 `TOP3/TOP5/N`
- 업권별 다른 threshold

따라서 이 PR에서는 distance 계산과 distribution evidence까지만 유지하고 **peer membership cutoff/N은 lock하지 않는다.**

## 9. 남은 gate

1. similarity ranking policy를 별도 pure contract로 고정하되 cutoff/N을 사실처럼 숨기지 않는다.
2. `total_assets` production persistence를 구현하기 전에 metric-aware aggregate / revision / source precedence를 current collector execution path에 통합 검증한다.
3. CU/KFCC는 total-assets exact source contract가 완성되기 전까지 ready cohort에 포함하지 않는다.
4. Strategy payload/UI에서 financial vintage와 current eligibility evidence date를 분리 표시한다.
5. official Relative Pricing peer와 size peer를 별도 label/policy로 유지한다.
6. 최종 UI 연결 후 production-data desktop/mobile browser QA를 수행한다.
