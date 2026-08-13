# FINLIFE product identity v1 — service namespace

- 작성일: 2026-08-13
- 대상 source: `finlife_savings_bank`, `finlife_bank`
- 성격: 데이터 identity / 수집 정합성 고위험 수정
- canonical 자동 보정: **하지 않음**
- production DB 직접 수정: **하지 않음**

## 1. 문제

FINLIFE의 상품 API는 `depositProductsSearch`와 `savingProductsSearch`가 각각
`fin_prdt_cd`를 제공한다. 기존 파서는 이 코드를 서비스 구분 없이 그대로
`ParsedRateRow.source_product_key`에 저장했다.

저장 계층의 product source link는 다음 키를 쓴다.

```text
institution_id + source_product_key
```

따라서 같은 금융회사에서 예금 API와 적금 API가 동일한 `fin_prdt_cd`를 재사용하면
두 서비스가 같은 canonical Product에 붙을 수 있다. 그 뒤 생성된 ProductVariant와
RateObservation도 잘못된 Product.product_type을 상속해 교차검증 결과를 오염시킨다.

## 2. 실제 반증 증거

2026-08-12 FINLIFE 저축은행 raw artifact
`collection-run-31511052013` / FINLIFE collection run
`5793a596-fd1a-4478-9d7d-65a96a6be392`에서 동일
`(fin_co_no, fin_prdt_cd)`가 deposit/saving 서비스 사이에 재사용되는 사례를 확인했다.

| 기관 | 코드 | depositProductsSearch | savingProductsSearch |
|---|---|---|---|
| 아산저축은행 | `240019` | `SB톡톡-정기예금` | `SB톡톡-정기예금` |
| 진주저축은행 | `240001` | `정기예금(진주,통영)` | `정기예금(진주)` |
| 하나저축은행 | `240010` | `비대면 하나더넥스트 시니어 회전예금` | `파란 하늘 정기적금` |

특히 하나저축은행 사례는 이름과 상품유형이 모두 다르므로 `fin_prdt_cd`가 두 서비스
전체에서 전역 유일하다는 가정을 반증한다.

## 3. Current state

### Raw response 내부 결합키

한 서비스 응답의 `baseList` ↔ `optionList` 결합은 기존대로 유지한다.

```text
fin_co_no + fin_prdt_cd
```

이 키는 **같은 API service 응답 안에서의 join key**다.

### Persisted source product identity

기존:

```text
fin_prdt_cd
```

문제: service family가 없어 cross-service collision 가능.

## 4. Target state

FINLIFE의 저장용 source product identity를 다음처럼 고정한다.

```text
{service}:{fin_prdt_cd}
```

예:

```text
depositProductsSearch:240010
savingProductsSearch:240010
```

`source_row_ref`도 service를 포함한다.

```text
{service}:{fin_co_no}/{fin_prdt_cd}/{save_trm}
```

`extra.finlife_service`에도 원천 service를 남긴다.

### 불변식

최신 확인 FINLIFE 실행에서:

```text
raw artifact = depositProductsSearch_*  -> Product.product_type = term_deposit
raw artifact = savingProductsSearch_*   -> Product.product_type = installment_savings
```

불일치 허용치: **0건**.

## 5. 왜 generic entity resolver를 바꾸지 않는가

충돌은 FINLIFE의 `fin_prdt_cd` namespace 의미에서 발생한다. 다른 source의 식별자 계약까지
`product_type` 등으로 일괄 변경하면 blast radius가 불필요하게 커진다.

따라서 source-specific parser에서 안정적인 source key를 만든 뒤 기존
`resolve_product()` / `make_variant_key()`가 그대로 그 키를 소비하게 한다.

## 6. 기존 데이터 전환 정책

이번 PR은 과거 canonical row를 파괴적으로 rewrite하지 않는다.

새 key를 쓰는 첫 FINLIFE 수집에서:

- 새 service-namespaced source product identity가 생성된다.
- 새 variant identity도 service namespace를 포함한다.
- 최신 실행을 기준으로 화면/감사에 쓰이는 observation은 새 identity로 전환된다.
- 과거 pre-fix observation과 old source link는 historical evidence로 보존된다.

즉 DB row 수가 일시적으로 증가할 수 있다. 이는 잘못된 과거 history를 억지로 재작성하는
것보다 안전한 forward-only 전환이다. 별도 historical repair/backfill은 증거와 사용자 승인
없이 수행하지 않는다.

## 7. 검증 계약

### 정적/단위

1. 동일 `fin_prdt_cd`를 deposit/saving으로 파싱하면 `source_product_key`가 달라야 한다.
2. 같은 금융회사·같은 raw code를 두 서비스에서 저장해도 Product가 2개로 분리되어야 한다.
3. 각 observation의 raw service와 Product.product_type이 일치해야 한다.

### production-copy runtime

1. 현재 production DB copy에서 `finlife_identity_audit.py --allow-mismatch`를 실행해 기존 오염을 재현한다.
2. 같은 DB copy에 branch code로 FINLIFE 저축은행을 **fresh collect**한다. production/R2에는 쓰지 않는다.
3. 새 latest run에 `finlife_identity_audit.py`를 실행해 mismatch=0을 강제한다.
4. source discrepancy audit를 다시 실행해 기존 16건 mismatch 목록이 어떻게 변하는지 비교한다.

## 8. 하지 않는 것

- production DB 직접 수정
- 과거 observation 삭제/merge
- canonical 금리 자동 보정
- source authority 자동 판정
- fuzzy product merge
- 전략 대시보드 Release Gate 변경

## 9. Rollback

코드 rollback은 service namespace 변경 commit을 revert하면 된다.
이미 branch/runtime-copy에서 생성된 새 identity는 production에 publish하지 않으므로 개발 검증 단계의
rollback은 DB copy 폐기로 끝난다.

production에 향후 merge되어 fresh collect가 수행된 뒤 rollback이 필요해도 과거 row를 삭제하지 않는다.
마지막 confirmed run 기준 화면 동작과 historical repair 필요성을 별도 판단한다.
