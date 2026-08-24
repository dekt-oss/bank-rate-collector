# 대신저축은행 P1 Source Discrepancy Forensic v1

- 기준일: 2026-08-24
- 관련 Issue: #98
- 상위 coordination spec: Post-Merge 개선 통합 명세 v3 / Phase 1 A1
- 기준 main: `1325d54e9d28bf05040c4f6c51e92bc45bd69253`
- 범위: 대신저축은행 `정기적금` 24/36개월
- 상태: read-only forensic

## 1. 현재 관찰

A0 final-head production audit에서 대신저축은행은 계속 P1 `stale_source` 2건으로 남았다.

- 24m `any/simple`: FSB 3.00 / FINLIFE 4.00
- 36m `any/simple`: FSB 3.00 / FINLIFE 4.00
- FSB `source_effective_at`: 2025-11-03
- FINLIFE `source_effective_at`: 2026-08-20
- absolute delta: 1.00%p

그러나 같은 상품/기간의 `compound` variant는 FSB=FINLIFE=3.00으로 일치한다.
따라서 단순히 `FSB가 오래돼서 틀렸다`고 결론내리면 안 된다.

현재 핵심 질문은 다음이다.

> FINLIFE의 simple 4.00 행과 compound 3.00 행이 실제로 같은 FINLIFE source product의
> 이자방식 variant인지, 서로 다른 `fin_prdt_cd`를 가진 동명이상품/중복 공시인지?

## 2. 직접 은행 공시의 현재 제3축

대신저축은행 직접 상품 페이지는 현재 정기적금 정액식의 24/36개월을 3.00%로 표시한다.

이 사실은 forensic evidence로만 사용한다.

- bank-direct가 자동 canonical authority가 되지 않는다.
- 공식 페이지가 더 최근이라는 이유만으로 FSB/FINLIFE precedence를 바꾸지 않는다.
- raw FINLIFE identity를 확인하기 전에는 FINLIFE 4.00을 오류라고 확정하지 않는다.

## 3. 필요한 evidence

### 3.1 Production baseline

현재 production DB의 최신 FSB/FINLIFE run에서 다음을 보존한다.

- source_id
- internal Product ID/name/type
- active `source_entity_links.source_entity_key`
- term / join_channel / interest_method / payment_method
- base/max rate
- source_effective_at / last_seen_at
- raw artifact path / SHA-256
- base/option locator
- source_record_hash

### 3.2 Fresh source capture

runner-local production DB copy에서 새로 다음만 수집한다.

1. FINLIFE savings-bank (`030300`)
2. FSB

수집 결과는 production R2/rate-data에 쓰지 않는다.

Fresh raw artifact에서 대신 `정기적금` 24/36개월 locator를 실제로 dereference하여:

- FINLIFE base object
- FINLIFE option object
- FSB locator value
- raw artifact whole-file SHA-256

를 forensic JSON에 포함한다.

### 3.3 FINLIFE identity

FINLIFE parser의 source product identity는:

`{service}:{fin_prdt_cd}`

이다.

따라서 simple / compound 행 각각에 active source product key를 붙여 다음을 직접 판정한다.

- 같은 key인가
- 다른 key인가
- raw `fin_prdt_cd`가 source entity key와 일치하는가
- base record의 `fin_prdt_nm`, `join_way`, `dcls_strt_day`, `dcls_month`가 무엇인가
- option의 `intr_rate_type`, `intr_rate`, `intr_rate2`, `rsrv_type`가 무엇인가

## 4. Isolated forensic workflow

`.github/workflows/source-discrepancy-daishin-forensic.yml`

절차:

1. current production DB를 R2에서 runner-local로 restore
2. `work/forensic.sqlite3`로 복사
3. migrations는 복사본에만 적용
4. FINLIFE savings-bank fresh collect → 복사본 + local raw
5. FSB fresh collect → 복사본 + local raw
6. 대신저축은행 직접 금리 페이지를 HTTP GET으로 raw capture
7. `scripts/source_discrepancy_daishin_forensic.py` 실행
8. provenance/whole-file hash/read-only invariant assertion
9. JSON + official HTML/headers + fresh raw를 Actions artifact로 보존

## 5. 안전경계

Workflow/스크립트는 다음을 하지 않는다.

- `storage upload`
- production DB mutation
- rate-data push
- canonical 금리 수정
- source precedence 변경
- official evidence authority 승격
- product identity 자동 merge
- DB/schema/migration 변경
- collector parser 변경

외부 source에는 기존 collector의 읽기 요청과 공식페이지 GET만 수행한다.

## 6. 판정 규칙

### Case A — simple / compound가 서로 다른 FINLIFE source product key

동일 normalized product name이지만 upstream product code가 다른 것이므로,
`stale_source` 하나로 설명하지 않는다.

후속 확인:

- 두 source product가 모두 현재 공시인지
- 한쪽이 종료/대체/중복된 상품인지
- source discrepancy match key에 upstream duplicate/product-generation dimension이 필요한지

canonical/stable identity 변경은 별도 decision gate로 분리한다.

### Case B — 같은 FINLIFE source product key

동일 product 안 interest_method별 rate 차이일 수 있다.

후속 확인:

- official disclosure가 이자방식별 별도 rate를 실제 제공하는지
- FINLIFE option parsing이 정확한지
- FSB가 interest_method 값을 정확히 보존하는지

### Case C — Fresh FINLIFE에서 4.00 행이 사라짐

publication lag / stale observation 가능성이 커진다.
단, historical raw가 있었던 사실은 지우지 않는다.

### Case D — Fresh FINLIFE에서도 4.00 유지 + bank-direct 3.00

source-to-official disagreement로 분류하되 source authority를 자동 선택하지 않는다.
FINLIFE raw product code/시행일/공시월과 bank-direct effective context를 추가 확인한다.

## 7. Acceptance

- synthetic extractor test 통과
- General CI lint/full test/migration 통과
- isolated forensic workflow 성공
- FINLIFE simple/compound source product key 판정 가능
- raw locator가 실제 object/value로 resolve됨
- raw whole-file SHA가 DB provenance와 일치
- official page raw artifact hash 보존
- production/canonical/source authority mutation 0
- 결과를 #98 또는 PR evidence에 기록

검증하지 못한 항목은 `미검증`으로 남긴다.
