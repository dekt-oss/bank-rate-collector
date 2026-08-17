# 상호금융 최고금리 공통화 — Stage F Source Evidence

```yaml
document_type: source_evidence
status: complete
created_at: 2026-08-17
target_repository: dekt-oss/bank-rate-collector
base_commit: 89312caabe8caae7326a03028ef9d4c551ca1496
issue: 108
contract_pr: 116
owner_approval: 2026-08-17
scope:
  - kfcc_alternate_official_source
  - nh_local_preferential_channel_semantics
  - cu_6m_gap
code_change: false
db_change: false
release_gate_change: false
```

## 1. 결론

Stage F의 목적은 `kfcc`, `nh_local`, `cu`의 `max_rate` 의미를 공식 원천 기준으로 반증하고, Stage G 진입 여부를 결정하는 것이다.

최종 판정:

| 업권 | Stage F 판정 | Stage G | 이유 |
|---|---|---|---|
| 신협 `cu` | **GO — reference 유지** | 기존 계약 유지 | 공식 비교공시가 기본금리와 최고우대금리를 같은 상품·기간·조합 조회 차원에서 직접 제공 |
| 새마을금고 `kfcc` | **NO-GO** | **G1 BLOCKED** | 우대이율 상품의 존재는 공식 자료로 확인되지만, 개별 금고 코드·상품·기간에 연결되는 현재 최고금리 공개 원천을 찾지 못함 |
| 농·축협 `nh_local` | **CONDITIONAL EVIDENCE / G2 BLOCKED** | **G2 BLOCKED** | 공식 원본에 e-joy 인터넷 우대금리 행이 있으나 기존 창구 variant의 max가 아니라 별도 channel component이며, 전 점포 적용·대상상품 linkage를 아직 결정론적으로 증명하지 못함 |

따라서 이 PR에서는 collector/DB/UI를 변경하지 않는다.

`max_rate ?? base_rate` fallback은 계속 금지한다.

---

## 2. 검증 기준

`max_rate`를 canonical에 넣기 위해 최소 다음을 요구한다.

1. 공식 또는 승인된 1차 원천
2. stable product 또는 결정론적 product key
3. 가입기간
4. 기관/점포 및 rate scope
5. 채널이 한정되면 join channel
6. 최고금리 직접 필드 또는 원천이 명시한 계산 계약
7. 공시/조회 기준시점
8. raw evidence 재현 가능성

원천이 공식 최고금리 필드를 직접 제공하면 우대조건 세부 구성이 비어 있어도 사용할 수 있다. 반대로 우대금리 문구만 별도로 존재하면 동일 product/term/scope/channel 연결이 증명되기 전에는 합산하지 않는다.

---

# 3. KFCC / 새마을금고

## 3.1 현재 collector 계약

현재 parser는 개별 금고 `gmgo_cd` 단위의 공식 금리표에서 `base_rate`를 읽고 다음을 유지한다.

- `rate_scope = institution`
- `base_rate = 공시 기본이율`
- `max_rate = None`
- 금고별 금리를 점포에 복제하지 않음

관련 코드:

- `src/rate_monitor/collectors/kfcc/adapter.py`
- `src/rate_monitor/collectors/kfcc/parser.py`

현재 코드의 `max_rate=None`은 데이터 누락을 임의 보정하지 않는 올바른 상태다.

## 3.2 현재 중앙 금리조회

공식 금리조회:

- `https://www.kfcc.co.kr/goods/goods_19.do?OPEN_TRMID=<gmgoCd>`

2026-08-17 재확인 결과 화면은 `기본이율`을 중심으로 제공한다. 기존 Claude review에서 상품 설명의 `기본이율(우대이율 제외)` 문구도 직접 확인했다.

이 원천만으로는 `base_rate`를 `max_rate`로 정규화할 수 없다.

## 3.3 대체 공식 원천 탐색 결과

MG새마을금고 공식 금융상품몰:

- `https://www.kfcc.co.kr/goods/goods01_main.do`

공식 상품몰에서 다음을 확인했다.

- `MG더뱅킹정기예금`은 MG더뱅킹에서만 가입 가능한 거치식 정기예금이며 **거래실적에 따른 우대금리**를 제공한다.
- 공식 사이트는 각 새마을금고가 개별법인이므로 **금고별 상품 취급여부·조건이 일부 상이할 수 있음**을 명시한다.

공식 수신업무 안내:

- `https://www.kfcc.co.kr/business/receivingDeposits.do`

여기서도 MG더뱅킹정기예금이 거래실적에 따른 우대금리를 제공하는 상품임을 확인했다.

### 의미

우대금리 자체가 존재한다는 것은 증명됐다. 그러나 Stage G에 필요한 것은 상품 일반 설명이 아니라 다음의 동시 linkage다.

```text
gmgo_cd
+ current product
+ term
+ current base rate
+ current preferential/high rate
+ effective date
```

이번 조사에서 이 구조를 제공하는 공식 공개 웹/API 원천은 확인하지 못했다.

MG더뱅킹 앱은 공식 채널이지만, 공개 웹에서 금고별 현재 최고금리를 안정적으로 재현할 수 있는 machine-readable/public contract는 확인하지 못했다.

## 3.4 판정

**KFCC Stage F = NO-GO**

**PR-G1 = BLOCKED**

다음 중 하나가 추가로 확보되기 전 collector를 변경하지 않는다.

- 금고별 최고금리 공식 API/공시
- 개별 금고 공식 페이지에서 stable 금고키·상품·기간·최고금리를 재현할 수 있는 구조
- MG더뱅킹의 공식 공개 contract로 동일 linkage를 증명할 수 있는 자료

금고별 조건이 다를 수 있으므로 중앙 상품설명서의 우대폭을 모든 금고 base rate에 더하는 구현도 금지한다.

---

# 4. NH local / 농·축협

## 4.1 현재 공식 원천 계약

현재 source recon과 collector는 농협 공식 `wmall.nonghyup.com`의 점포별 화면을 사용한다.

- 전국 점포 목록: `SFDPW0161R.view`
- 거치식 상세: `SFDPW0163R.view?brc=<점포코드>`
- 적립식 상세: `SFDPW0164R.view?brc=<점포코드>`

관련 코드:

- `src/rate_monitor/collectors/nh_local/adapter.py`
- `src/rate_monitor/collectors/nh_local/parser.py`
- `docs/source-recon/nh-local.md`

현재 parser 계약:

- `source_institution_key = source_outlet_key = brc`
- `rate_scope = outlet`
- `base_rate = 표의 금리`
- `max_rate = None`
- `e-joy`/`인터넷` 상품명은 `join_channel=internet`
- `우대금리` 행은 삭제하지 않지만 warning을 남김

## 4.2 공식 원본에서 확인된 e-joy 우대행

저장소의 공식 raw fixture/정찰 문서에서 다음 실물 구조가 확인돼 있다.

강릉농협 강동지점 거치식 예시:

| 원천 행 | 기간 | 금리 | 의미 |
|---|---|---:|---|
| 정기예탁금 | 12개월 이상~24개월 미만 | 3.0% | 기본 상품 행 |
| 복리식정기예탁금 | 12개월 이상~24개월 미만 | 3.0% | 기본 상품 행 |
| e-joy 인터넷예금 우대금리 | 12개월 이상~24개월 미만 | 0.1% | `상품별 금리 + 우대금리 적용` |
| 만기자유정기예탁금 | 12개월 이상~24개월 미만 | 3.0% | 기본 상품 행 |

이 구조는 다음을 의미한다.

1. 우대금리 행은 독립 가입상품의 완성된 최고금리가 아니다.
2. `e-joy 인터넷예금`이라는 채널 제약이 있다.
3. 기존 `join_channel=unknown`인 창구/일반 variant에 0.1%p를 더하면 채널 의미가 섞인다.
4. 안전하게 구현하려면 `join_channel=internet`인 별도 variant 또는 별도 source-declared adjustment 계약이 필요하다.

## 4.3 추가 검색 결과의 취급

웹 검색에서는 여러 비공식 비교 사이트에서도 서로 다른 농·축협 점포에 e-joy 우대행이 0.05%, 0.10%, 0.20% 등으로 노출되는 사례가 확인됐다.

그러나 이 자료는 **공식 원천이 아니므로 Stage G GO 근거로 사용하지 않는다.**

다만 점포별 우대폭이 동일하다고 가정해서는 안 된다는 탐색 신호로만 취급한다.

## 4.4 아직 증명되지 않은 것

- 전국 또는 충분한 대표표본에서 e-joy 우대행 구조가 동일한가
- 우대행의 산문 대상상품 목록을 stable product에 결정론적으로 연결할 수 있는가
- 각 기간의 우대폭이 모든 대상상품에 동일하게 적용되는가
- 인터넷 채널 외 별도 우대가 존재하는가
- 공식 `smartmarket.nonghyup.com` 계열에 더 구조화된 현재 최고금리 source가 있는가

이번 환경에서는 공식 NH 상세 페이지를 웹 도구로 직접 열지 못했고, 저장소의 공식 raw fixture와 기존 실측 계약을 Source of Truth로 사용했다.

## 4.5 판정

**NH Stage F = CONDITIONAL EVIDENCE, 그러나 Stage G Entry Gate는 미충족**

**PR-G2 = BLOCKED**

향후 G2를 열려면 최소 다음이 필요하다.

1. 충분한 점포 범위에서 우대행 구조/대상상품/기간을 read-only census
2. `join_channel=internet` 별도 variant 설계 확정
3. source-declared 산문 대상상품 → stable product 매칭 규칙의 deterministic test
4. 기존 창구 variant에 우대금리를 더하지 않는 cross-join guard
5. Stage G downstream consumer audit

---

# 5. CU / 신협

## 5.1 공식 최고금리 계약 재확인

공식 비교공시:

- `https://www.cu.co.kr/cu/ad/inrstCmpr/findInrst15CmprList.do?mi=201001`

공식 화면은 거치식 예금에 대해 다음을 명시한다.

- 기간 선택: 1/3/6/12/24/36개월
- 가입방식: 전체/창구/인터넷/모바일
- 기본금리: 우대금리를 포함하지 않은 상품의 기본이율
- 최고 우대금리: 우대조건을 모두 충족한 경우 제공하는 금리

현재 adapter도 공식 AJAX 응답의 `baseRate`, `highRate`, `monTy`, `cuIngno`, `stockCode`, `prefCondMemo`, `pubiBeginDate`를 같은 조회 차원에서 사용하며 `provides_max_rate=True`다.

따라서 CU는 공통 `max_rate` reference contract로 계속 사용할 수 있다.

## 5.2 6개월 0건

기존 source recon 실측은 부산 기준:

- 12개월: 566건
- 24개월: 453건
- 36개월: 404건
- 6개월: **0건**

이번에 공식 비교공시 화면을 재확인했으며 **6개월은 현재도 선택 가능한 검색 조건**이다.

또한 공식 신협 상품 페이지 및 개별 신협 공식 페이지에는 6개월 가입 가능한 거치식 상품이 실제 존재한다.

예:

- 파워정기예탁금 I: 계약기간 3개월 이상 36개월 이하
- 개별 신협 정기예탁금: 3/6/12/24/36개월 등

따라서 `6개월 0건`을 "신협 상품에 6개월 계약이 없어서"라고 설명할 수 없다.

그러나 이번 환경에서는 AJAX POST 결과를 직접 재실행해 원인까지 확정하지 못했다.

가능한 원인을 추정하지 않는다.

### 계약

- 6개월 데이터는 현재 `0건/원인 미확정` 상태로 노출
- 12개월 데이터를 6개월로 보간/복제하지 않음
- 6개월이 필요한 UI에서는 명시적 no-data 상태 사용
- 다음 CU source probe에서 POST 실호출과 요청 body를 재검증

## 5.3 판정

**CU Stage F = GO, existing reference 유지**

단 6개월은 **supported query / zero disclosed rows / cause unverified** 상태다.

---

# 6. Evidence Matrix

| 항목 | KFCC | NH local | CU |
|---|---|---|---|
| 공식 source | KFCC 중앙 금리조회 + 상품몰 | NH wmall 점포별 상세 | CU 전자공시 비교 API |
| product key | 현재 parser product identity | 점포 상세 상품명 → stable identity | `stockCode` |
| institution/outlet key | `gmgo_cd` | `brc` (institution=outlet) | `cuIngno` |
| term key | 공시 기간 | 표의 기간 범위 | `monTy` |
| base rate | 직접 제공 | 직접 제공 | `baseRate` 직접 제공 |
| preferential component | 상품 일반 설명에는 존재, 금고별 현재 값 미확보 | e-joy 별도 행 | `highRate`와 preference memo |
| max rate | unsupported | unsupported | `highRate` 직접 제공 |
| join channel | 상품별 상이 | e-joy = internet | `tretYn`/조회조건 |
| rate scope | institution | outlet | institution |
| effective date | 조회기준일 | 조회일 | `pubiBeginDate` |
| raw reproducibility | base만 가능 | fixture/current collector 가능 | API artifact 가능 |
| Stage G | BLOCKED | BLOCKED | 기존 구현 유지 |

---

# 7. Stage H에 미치는 영향

현재 상태에서 상호금융 전체를 하나의 `최고금리` 랭킹으로 활성화하면 안 된다.

최고금리 mode의 최소 동작은 다음이어야 한다.

- CU: 선택 가능
- KFCC: `최고금리 미지원/미수집`으로 disabled
- NH local: `최고금리 계약 미확정`으로 disabled
- 기본금리를 최고금리 대신 사용하는 fallback 없음

단 이것은 Stage H 구현 허가가 아니다. Stage H는 별도 PR-H1에서 coverage/missing classification, denominator, geography, availability/freshness, payload 크기를 먼저 계약해야 한다.

---

# 8. 다음 작업 Gate

## PR-G1 KFCC

**진행 금지.** 대체 공식 per-MG 최고금리 source가 발견되기 전까지 BLOCKED.

## PR-G2 NH local

**진행 금지.** 우대행 census + channel variant linkage가 결정론적으로 증명되기 전까지 BLOCKED.

## PR-H1

Stage F 결과를 입력으로 data-contract 설계는 다음 순서의 후보 작업이다.

다만 Stage H에서도 unsupported sector를 최고금리 랭킹에 포함시키지 않는다.

---

# 9. Adversarial self-review

이 Stage F가 틀렸다고 가정하고 다음을 재검토했다.

### "KFCC 상품설명서에 우대금리가 있으니 base+우대를 계산하면 되지 않는가?"

불가. 공식 상품몰 자체가 금고별 취급여부·조건 차이를 명시한다. 금고별 current preferential value와 term linkage가 없으므로 중앙 일반조건을 `gmgo_cd`별 base에 합치면 추정값이다.

### "NH e-joy 행이 '상품별 금리 + 우대금리'라고 쓰였으니 바로 합치면 되지 않는가?"

불가. 인터넷 채널 조건이며 대상상품/기간/점포별 적용범위를 stable identity에 연결하는 별도 계약이 필요하다. 현재 일반 variant에 합치면 channel cross-join이 된다.

### "CU 6개월 상품이 존재하니 6개월 API 0건은 collector bug인가?"

증거 부족. UI는 6개월을 지원하고 상품도 존재하지만, API 결과 0건의 원인이 collector body/공시 universe/현재 조합 취급 여부 중 무엇인지는 이번 조사로 확정하지 못했다. bug로 단정하지 않는다.

---

# 10. 완료 판정

Stage F는 다음 상태로 완료한다.

```text
KFCC: NO-GO → G1 BLOCKED
NH local: CONDITIONAL EVIDENCE → G2 BLOCKED
CU: GO reference, 6m cause unverified
collector/DB/UI change: none
Release Gate: OFF
```

이 문서는 다음 구현 단계가 안전하지 않은 부분을 억지로 구현하지 않는 것을 완료 조건에 포함한다.
