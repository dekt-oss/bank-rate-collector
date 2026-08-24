# DH저축은행 source discrepancy forensic v1

기준일: 2026-08-24

## 1. 목적

Post-Merge 개선 통합 명세 v3 Phase 1 A2의 대상인 DH저축은행 12개월 정기예금 4개 variant를 read-only로 재현한다.

현재 triage baseline은 다음과 같다.

- 정기예금 12m / branch / simple: FSB 3.70, FINLIFE 3.85
- 정기예금 12m / branch / compound: FSB 3.70, FINLIFE 3.85
- 정기예금(비대면) 12m / any / simple: FSB 3.60, FINLIFE 3.70
- 정기예금(비대면) 12m / any / compound: FSB 3.60, FINLIFE 3.70
- classification: `freshness_gap`
- FSB effective 2026-08-21 / FINLIFE effective 2026-08-20

이 값은 조사 우선순위일 뿐 authority 판정이 아니다.

## 2. 핵심 질문

1. 같은 시점에 FINLIFE와 FSB를 fresh capture하면 위 차이가 유지되는가.
2. DH저축은행 bank-direct 상품공시는 같은 시점에 어떤 12개월 금리를 노출하는가.
3. 차이가 단순 publication lag인지, source payload disagreement인지 설명 가능한가.
4. 어떤 결론도 canonical/source precedence 자동 변경으로 이어지지 않는가.

## 3. Evidence contract

workflow는 production R2 DB를 runner-local로 복원한 뒤 별도 `forensic.sqlite3` 복사본에만 fresh collection을 수행한다.

보존 대상:

- latest fresh FINLIFE savings-bank raw
- latest fresh FSB raw
- DB current rows
- latest run raw artifact path / SHA-256 / captured_at
- fresh raw 안의 DH target record
- DH bank-direct 정기예금 page `rnum=17`
- DH bank-direct 비대면 정기예금 page `rnum=18`
- 각 bank-direct HTML/headers/SHA-256

`rate_observations.raw_artifact_id`는 값의 first-seen raw를 가리킬 수 있으므로, current row provenance와 이번 fresh-run raw evidence를 별도 필드로 보존한다.

## 4. Safety

다음은 금지한다.

- production R2 upload/write
- rate-data push
- canonical rate 수정
- FSB/FINLIFE precedence 변경
- bank-direct evidence를 canonical write source로 승격
- product identity 자동 merge
- DB/schema/migration 변경
- Strategy 또는 Production Strategy Release Gate 변경

## 5. Acceptance

- general CI lint / full test / empty DB migration SUCCESS
- isolated workflow extractor lint/test SUCCESS
- production R2 restore to runner-local copy SUCCESS
- FINLIFE fresh capture SUCCESS
- FSB fresh capture SUCCESS
- 두 bank-direct page HTTP capture SUCCESS
- latest run raw artifacts 모두 local resolve + SHA-256 match
- fresh raw에서 DH target record 확인
- report scope가 `production_state_mutated=false`, `canonical_mutated=false`, `source_precedence_changed=false`, `authority_selected=false`
- artifact를 열어 4개 variant root cause를 설명 가능

## 6. 판정 원칙

- bank-direct와 한 source가 같아도 해당 source를 자동 canonical로 선택하지 않는다.
- 기준일 차이만으로 stale/authority를 단정하지 않는다.
- fresh capture에서도 차이가 유지되면 source payload disagreement로 남긴다.
- fresh capture에서 수렴하면 publication lag/refresh timing으로 분류 후보를 좁힌다.
- bank-direct 내부의 단리/복리 표기가 연수익률인지 약정이율인지 source 필드와 섞지 않는다. 비교는 각 source가 실제로 제공한 nominal variant 의미를 보존한다.
