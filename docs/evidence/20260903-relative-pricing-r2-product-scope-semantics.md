# Relative Pricing R2 — FSB product-scope field semantics

```yaml
date: 2026-09-03
scope: savings_bank / term_deposit / historical product scope
source: FSB official ratedepo historical endpoint and public screen assets
workflow_run: 33703963004
workflow_job: 100488996513
artifact: relative-pricing-r2-product-scope-33703963004
artifact_id: 9874563217
artifact_zip_sha256: c6841b02f0560e19e275b7f12b4170f4f19871384dd6aad3f29e818ccc968ef3
production_write: false
decision: semantics_unresolved
historical_special_offer_gate: blocked
```

## 결론

FSB raw row의 `STATUS`, `START_DATE`, `FINISH_DATE`는 관측되는 source fact지만,
이번 evidence만으로 각 필드의 공식 비즈니스 의미를 확정할 수 없다.

- `STATUS`의 `U`/`N`은 값과 전이가 관측되지만 공식 화면·스크립트에서 의미 정의를
  찾지 못했다.
- `START_DATE`는 모든 조사 row에 존재하지만 같은 product key에서도 조회일 사이에
  반복 변경된다. 이를 상품 최초 판매 시작일이나 특판 시작일로 해석하지 않는다.
- `FINISH_DATE`에는 해석 가능한 종료일이 한 건도 없었다. 유일한 비공백 값은
  `99999999` sentinel이었다.
- 특판 관련 텍스트 신호는 진단용 표본일 뿐 classification contract가 아니다.

따라서 이 세 필드를 product lifecycle, sale period 또는 special-offer 분류로
canonical model에 승격하지 않는다. 기존 historical special-offer fail-closed gate를
유지하며 DB, collector/parser, Relative Pricing reducer, Strategy UI를 변경하지 않는다.

---

## 1. Evidence method

Evidence workflow는 FSB official ratedepo endpoint를 다음 기준일로 조회했다.

- 2026-07-31
- 2026-08-15
- 2026-08-30
- 2026-08-31
- 2026-09-01

각 snapshot에서 exact `FINAN_COMP_CODE:FINAN_PROD_CODE` product key로 row를 비교하고,
필드 분포·status 전이·product presence 전이·날짜 경계 표본을 기록했다. 또한 공식
ratedepo 화면과 동일 origin의 script assets에서 필드 토큰의 UI/behavioral 의미를
찾았다.

Evidence run은 read-only였고 production DB write를 수행하지 않았다. Workflow 성공은
조회와 artifact 생성 성공만 뜻하며 필드 의미 증명을 뜻하지 않는다.

---

## 2. Snapshot distribution

| 기준일 | rows | `STATUS=U` | `STATUS=N` | `START_DATE` populated | `FINISH_DATE` |
|---|---:|---:|---:|---:|---|
| 2026-07-31 | 395 | 366 | 29 | 395 | 전부 blank |
| 2026-08-15 | 394 | 357 | 37 | 394 | `99999999` 1건, 나머지 blank |
| 2026-08-30 | 395 | 367 | 28 | 395 | `99999999` 1건, 나머지 blank |
| 2026-08-31 | 395 | 367 | 28 | 395 | `99999999` 1건, 나머지 blank |
| 2026-09-01 | 395 | 367 | 28 | 395 | `99999999` 1건, 나머지 blank |

모든 snapshot에서 duplicate product key는 0건이었다. 그러나 exact key의 안정성은
필드 의미의 안정성을 증명하지 않는다.

---

## 3. Counter-evidence

### `STATUS`

서로 다른 `STATUS`가 관측된 product key는 30개였다.

| observed pattern | products |
|---|---:|
| `U → N → U → U → U` | 8 |
| `U → N → N → N → N` | 6 |
| `N → N → U → U → U` | 6 |
| `N → U → N → N → N` | 6 |
| `N → U → U → U → U` | 2 |
| `N → U → U → U` | 2 |

예를 들어 동일한 일반 `정기예금` product key가 `U → N → U`로 변하면서 계속
endpoint에 존재했다. 따라서 `N=판매 종료`, `U=판매 중`이라고 이름만으로 확정할 수
없고, 어느 값도 특판 여부를 직접 나타낸다고 볼 근거가 없다.

### `START_DATE`

`START_DATE`는 전 행에 채워졌지만 5개 기준일 사이 날짜 경계 표본이 80개였다.
동일 product key가 계속 존재하는 동안 값이 예를 들어
`20260727 → 20260811 → 20260820`으로 바뀌었다. 이는 적어도 immutable product launch
date가 아님을 반증한다. 금리 적용일, 제출/변경일 또는 다른 내부 의미일 가능성은
있지만 공식 계약 없이 그중 하나로 승격하지 않는다.

### `FINISH_DATE`

해석 가능한 date boundary sample은 0개였다. 한 product에서만 `99999999`가 반복됐고,
`STATUS=N` 28~37개 row는 모두 `FINISH_DATE`가 blank였다. 그러므로 종료일을
직접 제공하는 신뢰 가능한 lifecycle field라고 판정할 수 없다.

### Presence와 텍스트 신호

6개 product key가 snapshot 사이에 등장하거나 사라졌다. 이 변화는 source response의
presence fact일 뿐 실제 판매 시작·종료 시각을 증명하지 않는다.

2026-08-31 snapshot에서 `한정` 또는 `소진` text signal이 있는 row는 7개였고 모두
`STATUS=U`, `FINISH_DATE=blank`였다. 단어가 상품명 일부인 사례도 있으므로 text match를
특판 분류나 lifecycle 사실로 사용하지 않는다.

---

## 4. Official screen contract search

공식 ratedepo 화면과 19개 same-origin script source를 조사했다.

- `START_DATE` token의 의미 있는 화면/스크립트 참조: 0
- `FINISH_DATE` token의 의미 있는 화면/스크립트 참조: 0
- `STATUS` 검색 결과: 12개였으나 일반 JavaScript 상태/XHR status 문자열로,
  FSB row의 `STATUS` 코드 정의가 아니었다.

따라서 public screen assets에서도 `U`/`N`, `START_DATE`, `FINISH_DATE`의 비즈니스
정의를 확인하지 못했다.

---

## 5. Decision and enforcement

```text
STATUS_semantics = unresolved
START_DATE_semantics = unresolved
FINISH_DATE_semantics = unresolved
product_lifecycle_promotion = prohibited
special_offer_classification = prohibited
current_product_flag_carryback = prohibited
historical_special_offer_gate = blocked
```

이 결론은 기존 `relative_pricing_historical_service.py`의 계약과 일치한다.
historical `special_offer_flag=None`은 false가 아니며, explicit source provenance가 없으면
representative-rate reduction을 차단한다.

## 6. Reopen conditions

다음 중 하나가 확보될 때만 의미 결정을 다시 연다.

1. FSB가 제공한 공식 API schema/data dictionary로 각 코드와 날짜 의미가 명시됨
2. 동일 product key의 공식 UI 판매 상태·기간과 raw field를 다수 시점에서 직접 연결한
   behavioral evidence가 확보됨
3. 은행 또는 FSB의 explicit special-offer field와 historical version이 제공됨

재검토 시에도 source provenance, source-effective date, null/unknown fail-closed,
historical no-carryback을 별도로 검증해야 한다.

## 7. Not verified / not activated

- `STATUS=U/N` 공식 의미: **미검증**
- `START_DATE` 공식 의미: **미검증**
- `FINISH_DATE` 공식 의미: **미검증**
- historical special-offer classification: **차단 유지**
- 2026-08-31 representative rate / peer rank / analogue UI: **미활성**
- causal interpretation: **주장하지 않음**
