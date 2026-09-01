# Pricing Availability Scope Coverage — R0 production evidence

```yaml
document_type: runtime_evidence
status: verified_from_pinned_published_artifacts
as_of: 2026-09-01
scope: pricing_peer_availability_scope
source_of_truth:
  - published_rate_data
  - repository_contract
code_change: none
```

## 1. 결론

현재 published production 데이터는 `availability_scope`까지는 제공하지만, R0의 신규 계약인 `availability_match_key`는 아직 제공하지 않는다.

따라서 **현재 production artifact에서 evidence-backed `availability_match_key`를 직접 만들 수 있다고 검증된 pricing peer population은 0개**다.

이 결론을 약하게 만들기 위해 raw/display scope를 match key로 승격하지 않는다.

- `전국` / normalized `nationwide`는 **nationwide 후보 라벨**이지 그 자체로 R0 match-key evidence가 아니다.
- `미상` / normalized `unknown`은 fail-closed한다.
- `지역금고` / normalized `local_members`는 어느 지역의 common bond인지 식별하지 않는다.
- `직장금고` / normalized `workplace_members`는 어느 직장/common bond인지 식별하지 않는다.
- institution의 `region`/`district`는 기관 소재지/표시용 geography이며 상품 가입가능범위를 자동 증명하지 않는다.

특히 현재 published `rate-data`에서는 CU source가 아예 없고, bank는 raw published data에는 있으나 Strategy table에는 0행이다. 이 둘을 이전 census 숫자로 보충하거나 추정 population으로 사용하지 않는다.

---

## 2. Provenance

측정 대상은 2026-09-01 현재 `rate-data`의 실제 published artifact다.

```text
rate-data commit
6154a60fafea758d57041b8064031b322ec28fc1

commit message
data: NH 독립 수집 갱신 (run 33439208473, attempt 1)

site-public/data/rates.csv.gz
blob 2ba83c665b1842cd5484664272ae2b7af55ec892

site-public/data/rates.json.gz
blob b371d40fa8152e23fbc1983a373388ce57fcf25e

site-public/data/strategy-table.json
blob e66bc17052b9e186b6de251e6a3c1490fa8eaa48
```

`site-public/site-manifest.json`의 생성 시각은 `2026-09-01T10:34:44.624021+09:00`, published main-table row count는 407,551행이다.

### 재현 run

current SHA 전체 파일을 GitHub runner에서 read-only checkout하여 파싱했다.

```text
Strategy census run   33464561523   success
raw CSV census run    33464751343   success
```

두 run 모두 `rate-data` HEAD와 입력 blob SHA를 먼저 assert한 뒤 계산했다. 계산 결과를 만들기 위해 production DB를 수정하거나 source identity를 변경하지 않았다.

---

## 3. 측정 기준

### Raw published census

입력:

```text
site-public/data/rates.csv.gz
```

업권 매핑:

```text
fsb + finlife_savings_bank  -> savings_bank
nh_local                    -> nh_local
kfcc                        -> kfcc
cu                          -> cu
finlife_bank                -> bank
```

12개월 정기예금 structural filter:

```text
상품유형 == 예금
가입기간(개월) == 12
기본금리 또는 최고금리 중 하나 이상 존재
```

### Strategy census

입력:

```text
site-public/data/strategy-table.json
```

12개월 정기예금 structural filter:

```text
product_type == term_deposit
term_months == 12
base_rate 또는 max_rate 중 하나 이상 존재
```

Strategy source precedence는 `config/presentation.yaml`의 현재 계약을 따른다.

```text
db_only_sources:
  - finlife_savings_bank
```

실제 current Strategy table의 savings-bank 12개월 표본은 `source_id=fsb` 322행뿐이며 `finlife_savings_bank`는 남아 있지 않다. 따라서 같은 저축은행 상품을 보조 source가 덮어쓰는 population을 pricing peer로 사용하지 않는다.

### Special offer 한계

현재 published `rates.csv.gz`와 `strategy-table.json`에는 R0의 `special_offer_flag`가 없다.

따라서 아래 표의 `12개월 structural rows`는 **특판 제외까지 완료한 최종 R0 eligible rows가 아니다.**

R0 서비스 계약은 `special_offer_flag=False`를 기본 요구로 하고 명시적 opt-in 없이는 특판을 제외하지만, current production artifact만으로 그 flag를 재구성했다고 주장하지 않는다. 상품명 휴리스틱으로 특판 여부를 추정하지 않는다.

---

## 4. Raw published population

| sector | raw rows | institutions | 12개월 structural rows | 12개월 institutions | raw source |
| --- | ---: | ---: | ---: | ---: | --- |
| savings_bank | 3,793 | 79 | 633 | 79 | fsb 3,772 + finlife_savings_bank 21 |
| nh_local | 310,093 | 4,822 | 29,214 | 4,821 | nh_local |
| kfcc | 93,332 | 1,153 | 8,349 | 1,151 | kfcc |
| cu | 0 | 0 | 0 | 0 | 없음 |
| bank | 333 | 18 | 38 | 18 | finlife_bank |

12개월 raw scope / join-channel:

| sector | availability_scope | join_channel |
| --- | --- | --- |
| savings_bank | 전국 633 | branch 250 / any 213 / mobile 134 / internet 36 |
| nh_local | 미상 29,214 | internet 14,607 / unknown 14,607 |
| kfcc | 지역금고 8,020 / 직장금고 329 | branch 8,349 |
| cu | 데이터 없음 | 데이터 없음 |
| bank | 전국 38 | any 30 / mobile 8 |

이 raw census는 source 존재 여부를 보여주기 위한 것이다. R0 peer population은 raw rows를 직접 사용하지 않고 Strategy source-precedence 및 R0 계약을 통과해야 한다.

---

## 5. Strategy source-precedence 적용 후 population

| sector | Strategy rows | institutions | products | 12개월 structural rows | 12개월 institutions | 12개월 products |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| savings_bank | 958 | 79 | 395 | 322 | 79 | 322 |
| nh_local | 58,428 | 4,821 | 14,607 | 14,607 | 4,821 | 14,607 |
| kfcc | 18,340 | 1,151 | 6,363 | 6,363 | 1,151 | 6,363 |
| cu | 0 | 0 | 0 | 0 | 0 | 0 |
| bank | 0 | 0 | 0 | 0 | 0 | 0 |

### 12개월 join_channel

```text
savings_bank
  branch    126
  any       109
  mobile     69
  internet   18

nh_local
  internet  9,738
  unknown   4,869

kfcc
  branch    6,363

cu
  없음

bank
  없음
```

### 12개월 normalized availability_scope

```text
savings_bank
  nationwide         322  (79 institutions)

nh_local
  unknown         14,607  (4,821 institutions)

kfcc
  local_members    6,130
  workplace_members  233
  합계              6,363  (1,151 institutions)

cu
  없음

bank
  없음
```

---

## 6. Region / district 분포

아래 region/district는 가입가능범위 key가 아니라 현재 published geographic metadata의 분포다. **지역 값만으로 `availability_match_key`를 만들지 않는다.**

### savings_bank — 12개월 322행

Region:

```text
서울 106 / 경기 78 / 부산 31 / 인천 19 / 대구 15 / 충남 15 / 충북 14
경남 12 / 경북 11 / 광주 9 / 전북 4 / 강원 3 / 대전 3 / blank 2
```

District는 35개 값이며 blank 4행. 상위 10개:

```text
강남구 61 / 중구 40 / 성남시 29 / 부천시 17 / 동구 15
미추홀구 14 / 연제구 12 / 천안시 12 / 부산진구 10 / 청주시 9
```

### nh_local — 12개월 14,607행

Region:

```text
경기 2,583 / 경남 1,659 / 경북 1,599 / 전남광주통합특별시 1,398
충남 1,344 / 전북 1,008 / 강원 864 / 서울 735 / 충북 723
대구 480 / 대전 372 / 인천 372 / 부산 360 / 제주 357 / 전남 336
울산 276 / 세종 138 / 광주 3
```

District는 210개 값이며 blank 138행. 상위 10개:

```text
천안시 273 / 북구 258 / 서구 243 / 창원시 240 / 진주시 225
고양시 201 / 제주시 201 / 청주시 198 / 화성시 189 / 동구 186
```

`전남광주통합특별시`는 current published 값 그대로 기록한 것이며, 이 evidence 작업에서 명칭을 교정하거나 availability evidence로 재해석하지 않는다.

### kfcc — 12개월 6,363행

Region:

```text
서울 1,187 / 부산 677 / 경기 608 / 경북 544 / 대구 453 / 경남 401
강원 309 / 전북 302 / 충남 301 / 인천 296 / 충북 284 / 전남 234
제주 207 / 대전 192 / 광주 176 / 울산 146 / 세종 29 / 전남광주통합특별시 17
```

District는 200개 값이며 blank 29행. 상위 10개:

```text
동구 256 / 남구 219 / 중구 213 / 북구 194 / 서구 146
제주시 128 / 포항시 128 / 청주시 124 / 창원시 121 / 부산진구 119
```

CU와 bank는 current Strategy table에 12개월 row가 없으므로 Strategy region/district 분포를 만들지 않는다.

---

## 7. availability resolution 판정

R0에서 중요한 숫자는 raw scope label의 비율과 **실제로 evidence-backed match key가 존재하는 비율을 분리**하는 것이다.

| sector | 12개월 Strategy institutions | nationwide-labeled candidate | unknown | local/common-bond needs resolver | materialized evidence-backed match key |
| --- | ---: | ---: | ---: | ---: | ---: |
| savings_bank | 79 | 79 (100%) | 0 | 0 | **0 (0%)** |
| nh_local | 4,821 | 0 | 4,821 (100%) | 0 | **0 (0%)** |
| kfcc | 1,151 | 0 | 0 | 1,151 (100%) | **0 (0%)** |
| cu | 0 | 0 | 0 | 0 | **0** |
| bank | 0 | 0 | 0 | 0 | **0** |

해석:

1. **savings_bank** — 79개 모두 normalized `nationwide` 후보지만 current artifact에 `availability_match_key`가 없으므로 R0 peer로 자동 승인하지 않는다. 공식/source-level evidence resolver가 `nationwide`를 발행해야 한다.
2. **nh_local** — 4,821개 모두 `unknown`; 현재 상태에서 pricing peer에 포함하면 안 된다.
3. **kfcc** — 1,151개 모두 local/workplace common-bond 추가 resolution이 필요하다.
4. **cu** — current published raw와 Strategy table 모두 0행이다. 이전 834개 census를 current population으로 가져오지 않는다.
5. **bank** — raw에는 18개/12개월 38행이 있으나 current Strategy table에는 0행이다. 이 gap의 원인이 확인되기 전에는 pricing peer population으로 사용하지 않는다.

따라서 **현재 production에 바로 적용 가능한 R0 pricing peer population은 0**이라는 것이 fail-closed 결론이다. 이는 R0 계약이 잘못됐다는 뜻이 아니라, 다음 단계에서 evidence-backed availability resolver/payload wiring이 필요하다는 뜻이다.

---

## 8. `지역금고` 문자열을 peer key로 쓰면 실제로 깨지는 예

current KFCC 12개월 rows에는 동일 normalized scope `local_members`가 서울과 부산에 동시에 존재한다.

실제 sample:

```text
부산 / 금정구 / 금정중앙 / local_members / MG주거래우대정기예금
부산 / 해운대구 / 해운대 / local_members / Block예금
서울 / 송파구 / 잠실 / local_members / 자유자재정기예금Ⅱ
서울 / 용산구 / 이태원2동 / local_members / Block예금
```

이 네 기관을 단지 raw `지역금고` 또는 normalized `local_members`가 같다는 이유로 하나의 peer population으로 합치면, 실제 가입가능 common bond를 확인하지 않은 전국적 widening이 된다.

또한 부산/서울이라는 기관 소재지가 다르다는 사실만으로 각각 `local:busan`, `local:seoul`을 부여하는 것도 금지한다. **가입가능범위의 공식 evidence가 있어야 key를 만든다.**

---

## 9. Current data gaps 발견

이번 exact census는 R0 계약 외에 current published data의 두 경계를 확인했다.

### CU source absence

```text
rates.csv.gz cu rows      0
Strategy cu rows          0
```

이는 `CU 기관이 0개다`라는 의미가 아니라 **현재 pinned published artifact에 CU source가 없다는 의미**다. 별도 수집 운영 이슈의 원인분석 없이 이전 census나 추정값으로 보충하지 않는다.

### Bank raw → Strategy gap

```text
raw finlife_bank
  institutions             18
  rows                    333
  12m term-deposit rows    38

Strategy bank
  institutions              0
  rows                      0
```

R0-A에서 이 gap을 임의로 고치지 않는다. bank raw rows를 Strategy pricing peer로 우회 투입하지 않고, presentation/execution-path 원인을 별도 follow-up으로 남긴다.

---

## 10. R0 acceptance에 대한 판정

현재 R0 계약은 production evidence와 같은 방향이다.

- raw `availability_scope`를 peer key로 직접 사용하지 않는다.
- evidence-backed `availability_match_key`를 별도 필수 입력으로 요구한다.
- `unknown`, `미상`, 빈 값 등을 nationwide로 widen하지 않는다.
- 같은 raw `지역금고`라도 서로 다른 evidence key가 아니면 비교 가능하다고 가정하지 않는다.
- pricing peer는 resolved scope 내 eligible institution 전수를 사용하고 임의 N cap을 두지 않는다.
- funding observation 부재는 pricing peer 탈락 사유가 아니다.
- known funding은 `funding_as_of` 없이는 허용하지 않는다.
- `rate_as_of`와 `funding_as_of`를 별도로 보존한다.
- 특판은 명시적 opt-in 없이는 제외하는 서비스 계약을 유지한다.

단, current production artifact에는 아직 `availability_match_key`와 `special_offer_flag`가 없으므로 **R0 계약이 production data에 end-to-end wiring 완료됐다고 주장하지 않는다.**

---

## 11. 금지 해석

이 evidence로 다음을 주장하면 안 된다.

- `nationwide` scope label이 있는 모든 institution은 이미 R0 match key 검증이 끝났다.
- NH의 `unknown`은 전국가입이다.
- 모든 `지역금고`/`local_members`는 서로 직접 경쟁한다.
- 기관 소재지 region/district가 곧 가입가능지역이다.
- current CU population이 실제 0개다.
- raw bank 18개를 current Strategy peer에 바로 넣어도 된다.
- current availability를 historical 시점으로 carry-back할 수 있다.
- published data에서 특판을 정확히 제외했다.

R0의 목적은 **불완전한 가입범위·source·시점 데이터가 조용히 잘못된 경쟁군으로 변환되는 경로를 차단하는 것**이다.
