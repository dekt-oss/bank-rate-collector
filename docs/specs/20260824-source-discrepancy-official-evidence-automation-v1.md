# Source discrepancy official evidence automation v1

기준일: 2026-08-24

## 1. 목적

Post-Merge 개선 통합 명세 v3 Track C를 구현한다.

공식 홈페이지를 모든 저축은행에 대해 상시 크롤링하거나 canonical source로 승격하지
않는다. 현재 discrepancy 조사 queue와 명시적으로 review 대상으로 지정한 dimension
ambiguity에 대해서만 bank-direct supporting evidence를 read-only로 캡처한다.

이 작업은 다음을 하지 않는다.

- canonical 금리 수정
- FSB / FINLIFE precedence 변경
- bank-direct authority 승격
- product identity 자동 교정
- DB/schema/migration 변경
- collector/scheduler 변경
- production R2 upload
- Strategy / Production Strategy Release Gate 변경

## 2. Source of Truth / 선행 evidence

현재 source-source automatic key는 6D를 유지한다.

`institution + normalized product + product_type + term + join_channel + interest_method`

B2 strict-7D 영향도 분석은 별도 Draft PR에서 검증 중이며, 현재 Track C는 해당 decision과
독립적이다. official evidence는 source-source identity를 변경하지 않는다.

기존 A1/A2 forensic에서 실제 read-only HTTP capture가 검증된 surface만 초기 config에
등록한다.

### 대신저축은행

- 공식 상품공시: `https://bank.daishin.com/sub.do?code=02_prod02`
- 대상: `정기적금` 24/36개월
- parser는 `정기적금(정액식) 약정이율` 표의 nominal rate만 읽는다.
- 페이지의 `기준일`은 `page_reference_date`로 보존하고 `effective_at`으로 자동 승격하지
  않는다.

### DH저축은행

- branch product disclosure: `rnum=17`
- non-face-to-face product disclosure: `rnum=18`
- 대상: 12개월 정기예금
- 단리식 열은 nominal contractual rate로 보존한다.
- 복리식 열은 페이지가 `연평균수익률`로 명시하므로 `annualized_yield`로만 보존한다.
- 복리 nominal rate는 다른 열이나 source에서 추정하지 않는다.

## 3. Queue-targeted contract

입력은 이미 생성된 read-only source discrepancy report다.

1. `triage.queue`의 P0~P3 mismatch item
2. `config/source_discrepancy_official_targets.json`의
   `review_ambiguity_selectors`에 명시된 dimension ambiguity

각 item은 config target selector와 exact institution/product/product_type/term 기준으로
연결한다.

config에 없는 queue item은 삭제하거나 무시하지 않고 `unconfigured`로 결과에 남긴다.
따라서 configured coverage와 미지원 coverage를 동시에 볼 수 있어야 한다.

같은 공식 URL이 simple/compound 등 여러 queue variant에 연결돼도 HTTP capture는
한 번만 수행한다. variant별 evidence record는 같은 raw response SHA를 공유한다.

## 4. Evidence record 최소 계약

각 자동 evidence record는 최소 다음을 보존한다.

- `institution`
- `product`
- `product_type`
- `term_months`
- `join_channel`
- `interest_method`
- 필요한 경우 `payment_method`
- `url`
- `evidence_kind`
- `evidence_surface`
- `base_rate` / `max_rate` — nominal rate가 명시된 경우만
- `annualized_yield` — 페이지가 annualized yield를 별도로 제공하는 경우
- `rate_semantics`
- `captured_at`
- `effective_at` 또는 null
- `page_reference_date` 또는 null
- `capture_method`
- `capture_run_id`
- `capture_artifact_id`
- `capture_artifact_sha256`
- `raw_response_sha256`
- `raw_response_path`
- HTTP status / final URL / content type
- queue rank / priority / classification provenance

`annualized_yield`를 nominal `base_rate/max_rate`로 복사하지 않는다.

## 5. Raw artifact finalization

workflow는 두 단계 artifact를 사용한다.

1. bank-direct raw HTML + provisional evidence를 먼저 업로드한다.
2. `actions/upload-artifact`가 돌려준 artifact ID/digest를 final evidence의 모든 record에
   주입한다.

따라서 final evidence는 자신이 근거로 삼는 raw capture artifact를 기계적으로
추적할 수 있다.

## 6. Canonical-write machine guard

산문 규칙만으로 안전성을 주장하지 않는다.

### Import boundary

다음 module에는 canonical write path import를 금지한다.

- `scripts/source_discrepancy_official_capture.py`
- `src/rate_monitor/services/official_evidence_policy.py`

금지 prefix:

- `rate_monitor.collectors`
- `rate_monitor.db`
- `rate_monitor.services.collection_service`
- `rate_monitor.services.entity_service`
- `sqlalchemy`

금지 writer symbol도 AST test로 검사한다.

### Runtime DB hash guard

production R2 snapshot은 runner-local copy로 restore만 한다.

1. local copy에 migration 적용
2. SHA-256 seal
3. current audit 생성
4. official HTTP capture
5. final evidence를 audit에 재주입
6. DB SHA-256 재계산
7. before/after exact equality assertion

Evidence workflow에는 R2 upload / rate-data write 명령을 두지 않는다.

## 7. Failure semantics

### Configured target capture/parser 실패

- `capture_failures`에 원인을 기록
- workflow failure
- evidence를 정상 완료로 표시하지 않음

### Queue item에 config 없음

- workflow failure가 아님
- `unconfigured`에 item provenance를 남김
- coverage count에 포함

MVP가 일부 surface만 지원한다는 사실을 숨기지 않기 위한 정책이다.

## 8. Existing audit integration

final evidence는 기존 `scripts/source_discrepancy_audit.py --official-evidence` 입력 계약을
그대로 사용한다.

기존 policy를 유지한다.

- `official_evidence_authority=read_only_support_only`
- official internal conflict는 authority를 차단
- freshness는 observational metadata
- triage priority는 investigation order일 뿐 source authority가 아님

## 9. Initial target scope

초기 target registry:

1. 대신저축은행 정기적금 24/36개월
2. DH저축은행 정기예금 12개월 branch
3. DH저축은행 정기예금(비대면) 12개월 mobile surface

다른 현재 queue institution은 자동으로 `unconfigured` coverage에 남는다.
새 금융사 surface는 URL/parser semantics를 evidence로 검증한 뒤 config/parser를 별도
추가한다.

## 10. Acceptance / DoD

- General CI lint/test/migration SUCCESS
- dedicated official-evidence workflow SUCCESS
- current production R2 restore SUCCESS
- queue-targeted configured surface live HTTP capture SUCCESS
- raw HTTP response SHA-256 보존
- raw capture artifact ID/digest final evidence에 주입
- current queue 전체 수와 configured/unconfigured coverage 출력
- simple nominal rate 파싱 성공
- compound annualized yield를 nominal rate로 추정하지 않음
- final evidence를 기존 source discrepancy audit에 재주입 성공
- official evidence authority가 read-only support only임을 assertion
- AST canonical-write import boundary SUCCESS
- runner-local DB before/after SHA-256 exact match
- production R2 upload/write 없음
- rate-data write 없음
- canonical/source precedence/identity 변경 없음
- Production Strategy Release Gate OFF 유지

## 11. 후속

Track C v1은 모든 저축은행 공식 페이지를 수집하는 범용 crawler가 아니다.

후속 확장은 `unconfigured` coverage와 current triage priority를 보고 우선순위를 정한다.
각 추가 surface는 다음을 확인한 뒤에만 registry에 넣는다.

- URL이 실제 공식 bank-direct surface인지
- nominal / annualized 의미 구분
- channel / method / payment variant 의미
- effective/reference date 의미
- parser fixture + live runtime evidence
