# 농·축협 기관별 수신잔액 identity 운영복구 명세 — 2026-08-30

## 1. 목적

Strategy의 기관 수신 포지션·Rate × Funding Peer Matrix·Direct Peer는 **동일 업권의 exact canonical institution**만 비교할 수 있다.

2026-08-30 R2 production DB 실측에서 `nh_local` funding 원천 관측은 존재하지만 `institution_id`가 전부 비어 있어, 농·축협 기관별 분석을 fail-closed로 숨기고 있었다. 본 문서는 이 상태의 원인·실측 복구 가능량·운영 수정 계약을 고정한다.

## 2. production-copy 실측

R2 authoritative DB를 runner-local copy로 restore한 뒤, production DB 자체는 수정하지 않고 현재 exact reconciliation을 실행했다.

### 실행 전

- active NH funding observations: **11,273**
- mapped observations: **0**
- mapped institutions: **0**
- active `nh_local` institution links: **4,870**
- BRC형 active links: **4,870**
- source name이 있는 BRC links: **4,870**
- identity status: `unmapped_no_exact_cross_source_code` **11,273**

### exact reconciliation 결과

- scanned: **11,273**
- 실기관 key eligible: **11,119**
- exact mapped: **10,783**
- `no_brc_link`: **0**
- `name_mismatch`: **336**
- `invalid_link`: **0**
- 비실기관/aggregate 계열 key: **154** (`11,273 - 11,119`)

### 실행 후 production-copy

- exact mapped observations: **10,783**
- mapped canonical institutions: **1,082**
- unmapped observations: **490**
  - name mismatch 336
  - 실기관 key가 아닌 row 154
- `PRAGMA integrity_check`: **ok**
- `PRAGMA foreign_key_check`: **0 violations**

따라서 현재 exact BRC + 공식 source name reconciliation 자체는 유효하다. 문제는 매핑 알고리즘의 부재가 아니라 **이미 적재된 과거 관측을 운영상 재처리할 독립 경로가 없었던 것**이다.

## 3. 원인

`collect_operational()`은 농·축협 source의 새 수집 결과가 정확히 `success`인 경우에만 `reconcile_agri_funding_identity()`를 실행한다.

그 결과:

1. reconciliation 도입 전 적재된 과거 관측은 자동 재처리되지 않는다.
2. exact `nh_local` BRC link가 나중에 보강돼도 과거 funding row는 그대로 unmapped일 수 있다.
3. `partial` 수집은 R2 authoritative publish 자체가 차단되므로 그 실행에서 생긴 신규 row를 production으로 승격시키면 안 된다.

운영 해결은 **수집 시작 전 과거분 exact reconciliation + 정상 NH 수집 성공 후 기존 post-reconciliation 유지**로 한다.

## 4. identity 안전계약

변경하지 않는다.

- BRC exact match 필수
- 공식 `source_name`의 normalized exact match 필수
- 이름 fuzzy match 금지
- 기존 다른 canonical institution에 연결된 row 발견 시 transaction fail-closed
- amount / revision / validity / raw provenance 수정 금지
- `name_mismatch`는 자동 흡수하지 않고 미매핑 검토 대상으로 유지

즉 336건을 coverage를 높이기 위해 억지로 합치지 않는다.

## 5. coverage 분모 수정

기존 Strategy position service는 업권별 active rate-directory `source_entity_links` 수를 funding coverage 분모로 사용했다.

production-copy에서 농·축협은:

- exact mapped funding institutions: 1,082
- `nh_local` active rate-directory institution links: 4,870

이 둘은 entity grain/population contract가 다르므로 `1,082 / 4,870 = 22.2%`는 funding 동월 관측률이 아니다.

### 새 계약

coverage denominator는 **해당 funding analysis month에 해당 funding source가 보고한 실기관 source-key 모집단**으로 계산한다.

- 저축은행: sector-total pseudo key `030350S` 제외
- 농·축협: 검증된 local-coop institution key shape만 포함하고 central/aggregate row 제외
- 신협: 현재 canonical source contract의 비어 있지 않은 institution source key 사용; 향후 aggregate shape가 도입되면 source-specific 검증 규칙을 먼저 추가
- source/month/metric은 analysis row와 동일해야 함
- missing exact identity는 observed에는 들어가지 않지만 eligible에는 들어가므로 identity coverage 손실이 그대로 드러남
- 임의 품질 threshold는 만들지 않음

이 정의는 수집 성공률과도 별개다.

## 6. 구현

### CLI

`python -m rate_monitor.collectors.data_go_funding.cli reconcile-nh-identity`

- 기존 production DB 복사본 또는 운영 writer working copy에 독립 실행 가능
- JSON evidence 출력 지원
- 기존 exact reconciliation 함수만 호출

### 정기 collection

`collect` 진입 시 네트워크 fan-out 전에 historical NH reconciliation을 1회 실행한다.

- 이후 NH source가 `success`면 기존 `collect_operational()`의 post-reconciliation이 신규 row를 처리한다.
- required NH source가 `partial/failed`면 기존 publish fail-closed를 그대로 유지한다.
- 따라서 partial 신규 row를 억지로 production으로 승격시키지 않는다.

## 7. production 반영 절차

1. feature branch에서 production-copy restore
2. standalone reconcile 실행
3. mapping counts / mismatch counts 측정
4. Strategy position coverage를 새 funding-source denominator로 재계산
5. SQLite integrity / FK 검증
6. 전체 CI 통과
7. 코드 merge
8. **merged main 코드로** authoritative R2 DB restore
9. standalone reconcile 1회 실행
10. integrity / FK / Strategy payload 검증
11. 새 canonical R2 snapshot publish + readback verify
12. 그 뒤 Direct Peer calibration 진행

feature branch 코드로 production DB를 직접 publish하지 않는다.

## 8. Peer/Matrix 선행조건

농·축협 Direct Peer calibration은 production canonical에 exact identity repair가 반영된 뒤 진행한다.

- 동일 업권만 비교
- analysis month exact population
- 6M primary / 12M secondary
- 지역 fallback은 기존 `sigungu → sido → nationwide`만 사용
- 규모 유사성은 log(balance) distance
- N은 12/16/20 등 후보를 production distribution으로 calibration한 뒤 결정
- 금리와 수신 증감 관계는 association으로만 표현하고 causal effect로 표현하지 않음
