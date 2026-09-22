# 저축은행 원천 교차검증 v5 — 공식 evidence current-support freshness gate

- 작성일: 2026-09-22
- 대상: Issue #98
- 범위: read-only FSB ↔ FINLIFE ↔ 개별 저축은행 공식 공시 audit
- 비범위: canonical overwrite, source precedence 변경, collector/scheduler 변경, DB/schema 변경

## 1. Current state

v3/v4에서 공식 공시의 `captured_at` / `effective_at`과 age metadata를 보존하지만,
freshness는 observational-only였다.

그 결과 오래된 bank-direct evidence도 report가 다시 생성될 때마다
`primary_supported` / `secondary_supported` / `neither_supported` 같은
현재 source support 신호에 계속 참여할 수 있었다.

이는 canonical 값을 직접 바꾸지는 않지만 조사 우선순위와 reconciliation 해석을
오래된 캡처가 왜곡할 수 있다.

현재 production audit가 사용하는 dated evidence 파일은
`docs/evidence/source-discrepancy/20260823-official-savings-bank.json`이다.

## 2. Target state

공식 evidence는 계속 삭제하지 않고 historical evidence로 보존한다.

다만 `captured_at` 기준 age가 **30일 이상**이면 현재 source support 계산에
사용하지 않는다.

- `captured_age_days < 30`: current-support eligible
- `captured_age_days >= 30`: stale / historical-only
- `captured_at` 파싱 불가 또는 없음: unknown / current-support ineligible

30일은 새 금리/authority 규칙이 아니다.
기존 discrepancy triage가 source freshness에서 이미 사용하는 첫 age 경계
(`source_effective_age_ge_30d`)를 official evidence current-support에도
동일하게 적용하는 운영 freshness gate다.

## 3. Group semantics

모든 evidence record는 historical report에 그대로 남는다.

group은 두 상태를 병렬로 가진다.

- `status`: 전체 historical evidence의 일관성
- `current_status`: current-support eligible record만의 일관성

예를 들어 오래된 3.90% 공지와 새 4.00% 상품공시가 같은 group에 있으면:

- historical `status=conflict`는 보존
- 새 캡처만 current이면 `current_status=consistent`
- stale record는 현재 source support/contradiction 신호를 만들지 않는다

current record가 하나도 없으면:

- 모두 stale: `reconciliation_signal=stale_official_evidence`
- freshness unknown만 존재: `reconciliation_signal=insufficient_official_evidence`

## 4. Invariants

변경하지 않는다.

- FSB primary / FINLIFE secondary presentation precedence
- canonical rate 값
- source authority
- product / variant identity
- join_channel / interest_method / payment_method 계약
- discrepancy source-to-source matching
- DB/schema/migration
- collector 및 scheduler
- production publication

stale evidence는 삭제하지 않으며 URL, rate, captured/effective date, artifact provenance를
계속 report에 보존한다.

## 5. Triage contract

`stale_official_evidence`는 official support 점수를 부여하지 않는다.

따라서 stale bank-direct 캡처만으로:

- P0로 승격하지 않는다.
- `official_evidence_discrepancy`로 분류하지 않는다.
- official contradiction queue를 만들지 않는다.

source-source mismatch 자체의 delta/effective-date/source-age evidence는 기존 규칙대로
계속 점수화한다.

## 6. Verification

필수:

1. unit
   - 29일 캡처는 current-support 유지
   - 정확히 30일 캡처는 stale
   - stale record가 mixed group의 current conflict를 만들지 않음
2. repository CI
   - Ruff
   - full pytest
   - empty DB migration
3. production-data read-only discrepancy audit
   - current production R2 runner-local restore
   - canonical mutation 없음
   - dated official evidence가 age에 따라 current/stale/unknown으로 분류
   - stale signal이 official triage score/contradiction queue를 만들지 않음
4. adversarial review
   - boundary off-by-one
   - invalid captured_at
   - mixed current/stale evidence
   - historical evidence provenance 보존

## 7. Rollback

코드 및 audit contract만 변경한다.
DB/R2/canonical data를 쓰지 않으므로 rollback은 해당 commit revert로 끝난다.
