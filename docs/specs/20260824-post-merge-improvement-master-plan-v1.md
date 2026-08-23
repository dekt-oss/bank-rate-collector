# 금리수집기 Post-Merge 개선 통합 명세 v1

- 기준일: 2026-08-24
- 상태: `draft / external-review-ready`
- 기준 `main`: `1325d54e9d28bf05040c4f6c51e92bc45bd69253`
- 관련 핵심 Issue: #98
- 목적: 2026-08-24 시점 이후의 개선 작업을 **하나의 실행 순서와 검증 계약**으로 묶는다.

> 이 문서는 향후 작업의 **coordination spec**이다. 기존 데이터·계산·제품 계약을 임의로 대체하지 않는다.
> 충돌 시 실제 `main` 코드/runtime, `docs/specs/CURRENT.md`, 해당 기능의 최신 세부 spec과 Issue/PR 결정이 우선한다.
> 특히 canonical 금리, source authority, stable identity, Strategy Release Gate를 이 문서만으로 변경하지 않는다.

---

## 0. 한 줄 결론

지금부터의 최우선 과제는 새 기능을 더 얹는 것이 아니라 **금리 데이터의 남은 불일치를 설명 가능한 상태로 만들고, 그 증거 수집을 반복 가능한 운영 절차로 만든 뒤, Strategy 공개 여부를 별도 Release Gate에서 판단하는 것**이다.

권고 순서:

1. **#98 잔여 discrepancy 6건 forensic closure**
2. **payment-method ambiguity 51건 운영화**
3. **공식 홈페이지 evidence 수집·추적 자동화**
4. **Strategy release-readiness 패키지 완성** — Release Gate는 계속 OFF
5. **우대조건 구조화 / 관리자 편집 / 성능 / 보존성 등 제품·운영 개선**

---

# 1. 이 문서가 필요한 이유

현재 저장소에는 기능별 세부 spec과 과거 roadmap이 충분히 존재한다. 문제는 2026-08-11의 `docs/roadmap.md` 이후 다음이 크게 진전됐다는 점이다.

- Strategy Public Structural v2 및 Factual Rate Finder 구현/QA 완료
- production-data Strategy runtime E2E 구축
- FSB ↔ FINLIFE ↔ bank-direct 3중 source discrepancy audit 고도화
- FINLIFE product identity namespace 교정
- join channel / interest method 기반 6D 비교
- payment-method ambiguity fail-closed
- 공식 evidence freshness/provenance 및 P0~P3 triage 도입
- post-merge adversarial review를 통한 runtime/test contract 추가 강화

따라서 과거 roadmap의 미완료 목록을 그대로 순서대로 구현하면 이미 끝난 작업을 중복하거나, 현재 가장 중요한 데이터 신뢰성 문제보다 편의 기능을 먼저 개발할 위험이 있다.

이 문서는 **현재 검증된 기준점에서 남은 작업만 다시 정렬**한다.

---

# 2. 현재 검증된 기준점

## 2.1 Main / Strategy

현재 기준 `main`:

`1325d54e9d28bf05040c4f6c51e92bc45bd69253`

PR #190 / #192까지 반영되어 Strategy runtime smoke는 다음을 실제 렌더링 기준으로 검증한다.

- Public Structural cockpit host visible
- Factual Rate Finder host visible
- mobile candidate pseudo-label content/display/visibility/rendered box
- Response Surface SVG display/visibility/non-zero rendered box
- desktop/mobile Chrome smoke

PR #192 merge 후 main production Strategy runtime E2E:

- run: `32673974893`
- conclusion: `SUCCESS`
- artifact: `9502219346`
- artifact digest: `sha256:68776554b3a80b1a7646d11733cb5a64056324dc63a698fb4b495b8125566725`

Strategy decision evidence contract main run:

- run: `32673974873`
- conclusion: `SUCCESS`

**그러나 Production Strategy Release Gate는 계속 OFF다.**
구현·테스트 성공과 공개 승인은 별개의 결정이다.

## 2.2 Source discrepancy audit

PR #191 merge commit:

`a2f13e5d0ea47b37594434895edc7704304c4e51`

#191 이후 audit의 핵심 안전장치:

1. official evidence의 `join_channel=any`가 payment-method ambiguity를 우회하지 못함
2. 한 source가 ambiguity로 차단되어도 반대편 정상 source provenance를 `counterpart`로 보존
3. 대백저축은행 live HTTP evidence 4건에 artifact SHA-256 보존

검증된 production R2 read-only audit:

- run: `32648131602`
- artifact: `9495439357`
- artifact digest: `sha256:91deac81bb1f6f5ae39c82b0c9782ea115adef011b7edd69a66ef1583d39f097`
- snapshot: `state/snapshots/20260824T000342-3e7439f3.sqlite3.gz`

snapshot 규모:

- `rate_observations`: 3,475,002
- `institutions`: 7,125
- `products`: 81,623
- `product_variants`: 333,713
- `collection_runs`: 181

현재 audit 결과:

- exact comparable matches: **3,681**
- mismatch/incomplete queue: **6**
- P0: **0**
- P1: **2**
- P2: **0**
- P3: **4**
- official contradiction queue: **0**
- payment-method ambiguity: **51**

51건은 현재 artifact 재검사상 모두 `installment_savings`이며, 41건은 ambiguity 반대편의 정상 source representative가 `counterpart` provenance로 보존된다.

## 2.3 현재 남은 mismatch queue

### P1

1. 대신저축은행 정기적금 24개월
   - classification: `stale_source`
   - delta: `1.00%p`
2. 대신저축은행 정기적금 36개월
   - classification: `stale_source`
   - delta: `1.00%p`

### P3

1. DH저축은행 정기예금 12개월 `branch/compound`
   - `freshness_gap`, `0.15%p`
2. DH저축은행 정기예금 12개월 `branch/simple`
   - `freshness_gap`, `0.15%p`
3. DH저축은행 정기예금(비대면) 12개월 `any/compound`
   - `freshness_gap`, `0.10%p`
4. DH저축은행 정기예금(비대면) 12개월 `any/simple`
   - `freshness_gap`, `0.10%p`

이 6건은 **오류 확정 목록이 아니라 조사 queue**다.

---

# 3. 절대 보존할 불변식

향후 개선 PR은 아래를 기본 불변식으로 취급한다.

## 3.1 데이터 신뢰성

- canonical 금리를 discrepancy 결과만으로 자동 덮어쓰지 않는다.
- `FSB primary / FINLIFE secondary` 현행 precedence를 별도 승인 없이 변경하지 않는다.
- bank-direct official evidence는 read-only supporting third axis이며 자동 authority가 아니다.
- freshness는 observational metadata다. 더 최신이라는 이유만으로 authority가 되지 않는다.
- source가 제공하지 않는 variant dimension을 추정하지 않는다.
- payment method가 여러 개이고 rate pair가 다르면 현재처럼 fail-closed한다.
- raw/source locator/artifact hash/effective date/captured date provenance를 보존한다.

## 3.2 운영 안전성

- discrepancy 조사 과정에서 production R2 canonical write를 하지 않는다.
- `rate-data`를 감사 결과만으로 수정하지 않는다.
- schema/migration이 필요하면 별도 high-risk 작업으로 분리한다.
- collector/scheduler 변경은 source evidence와 retry/partial-failure 검증 없이 섞지 않는다.

## 3.3 Strategy 공개

- Production Strategy Release Gate는 기본 OFF다.
- CI/runtime 성공은 Release Gate ON 승인이 아니다.
- Release Gate ON은 사용자의 별도 명시적 승인으로만 수행한다.

---

# 4. 개선 Track A — #98 잔여 discrepancy 6건 forensic closure

**우선순위: 최우선 / High-risk data**

## 4.1 목표

P1 2건을 먼저, 이후 P3 4건을 실제 raw/source/official evidence로 설명 가능한 상태까지 조사한다.

목표는 특정 source를 정답으로 선언하는 것이 아니라 각 mismatch를 다음 중 하나로 근거 있게 분류할 수 있게 하는 것이다.

- 정상 publication/freshness lag
- stale carry-forward
- variant mismatch
- source payload mismatch
- official evidence ambiguity/conflict
- 기타 재현 가능한 원인

## 4.2 조사 순서

각 queue item마다 최소 다음을 함께 비교한다.

1. FSB raw payload / source locator / artifact provenance
2. FINLIFE raw payload / source locator / artifact provenance
3. `source_effective_at`
4. `last_seen_at`
5. 가입채널 `join_channel`
6. 이자방식 `interest_method`
7. 적금이면 `payment_method`
8. 개별 저축은행 공식 상품공시
9. 금리변경/시행 공지
10. official `captured_at` / `effective_at`
11. nominal rate와 연평균수익률의 구분

## 4.3 실행 순서

### A1 — 대신저축은행 P1 24/36개월

두 건이 같은 기관/상품에서 동시에 1.00%p 차이를 보이므로 먼저 조사한다.

완료 조건:

- 두 source raw provenance 확보
- 어느 값이 언제부터 관찰됐는지 시계열 설명
- direct-bank product disclosure와 change notice 확보 또는 `미확보`를 명시
- `stale_source` 분류가 실제 evidence와 맞는지 재판정
- authority를 선택하지 않은 상태에서도 mismatch 원인을 설명 가능

### A2 — DH저축은행 P3 4건

완료 조건:

- branch/비대면 × simple/compound variant를 섞지 않음
- 0.10~0.15%p 차이가 정상 publication lag인지 검증
- official evidence가 variant별로 유일하게 연결되는지 확인
- 모호하면 fail-closed 상태 유지

## 4.4 산출물

- 날짜가 고정된 official evidence record
- raw/source provenance가 포함된 audit artifact
- #98에 현재 queue와 판정 근거 기록
- 필요할 경우 **별도** source-discrepancy PR

## 4.5 금지

- 홈페이지 값 하나만 보고 canonical overwrite
- 검색 snippet/cache만으로 현재 truth 확정
- 채널/이자방식/적립방식이 다른 행을 최고금리 기준으로 병합

---

# 5. 개선 Track B — payment-method ambiguity 51건 운영화

**우선순위: 높음 / Data-model decision gate**

## 5.1 현재 사실

현재 51건 모두 `installment_savings`다.
현행 6D source key는:

`institution + normalized product + product_type + term + join_channel + interest_method`

FINLIFE가 같은 6D 안에서 서로 다른 `payment_method`와 서로 다른 rate pair를 제공하면 최고값을 대표로 고르지 않고 `ambiguous_variant_dimension`으로 차단한다.

이 방식은 현재 false positive를 방지하는 안전장치로 검증됐다.

## 5.2 다음 목표

51건을 단순 예외 숫자로 두지 않고 다음을 알 수 있게 만든다.

- 어느 기관/상품에 집중되는가
- 정액/자유적립 등 어떤 payment method 조합인가
- rate pair가 실제로 얼마나 다른가
- 반대편 source는 payment method 차원을 제공하는가
- 시간이 지나며 ambiguity 수가 증가/감소하는가

## 5.3 중요한 설계 결정

`payment_method`를 지금 즉시 canonical/stable identity의 7번째 strict key로 올리지 않는다.

먼저 source coverage census를 통해 다음을 확인한 뒤 별도 decision PR/spec에서 결정한다.

- FSB가 payment method를 제공하는 비율
- FINLIFE가 제공하는 비율
- 같은 base product 안에서 실제 상품 의미가 갈리는 비율
- 7D strict key 적용 시 source-only가 얼마나 증가하는지

## 5.4 완료 조건

- 51건 전체 census artifact 생성
- ambiguity 유형별 breakdown
- counterpart provenance completeness 검증
- 6D 유지 vs 조건부 7D 전환의 영향 분석
- identity 변경 필요 시 별도 승인 대상으로 분리

---

# 6. 개선 Track C — 공식 홈페이지 evidence 운영 자동화

**우선순위: 높음 / Track A·B 안정화 후**

## 6.1 목표

현재처럼 중요한 사례를 수동 forensic capture하는 능력은 유지하되, mismatch queue가 생길 때 반복적으로 확인할 수 있는 **queue-targeted evidence capture**로 발전시킨다.

처음부터 모든 저축은행 전체 페이지를 상시 크롤링하는 대규모 crawler로 확장하지 않는다.

## 6.2 권고 MVP

입력:

- P0~P3 mismatch queue
- dimension ambiguity 중 review 대상으로 지정한 항목

각 evidence record 최소 필드:

- institution/product/term
- `join_channel`
- `interest_method`
- 필요한 경우 `payment_method`
- source URL
- evidence surface 유형
- nominal rate
- annualized yield가 있으면 별도 필드
- `captured_at`
- `effective_at` 또는 unknown
- capture method
- workflow/run ID
- artifact ID
- raw response artifact hash

## 6.3 안전 규칙

- direct-bank evidence가 canonical을 직접 쓰지 않는다.
- URL이 공식 도메인이라는 이유만으로 최신 authoritative surface라고 가정하지 않는다.
- product page, rate-change notice, FSB-hosted bank surface가 충돌하면 `official_conflict` 또는 ambiguity로 남긴다.
- 자동화 실패가 기존 canonical publish를 막을지 여부는 별도 운영 결정으로 둔다. 기본 권고는 **audit path와 canonical collection path 분리**다.

## 6.4 확인된 교훈

### 키움예스저축은행

- 은행 직접 공식 기준: 2026-08-19 게시 / 2026-08-20 시행
- e-회전yes / SB톡톡회전yes: 3.70%
- FSB-hosted bank surface는 일정 시점 4.05%를 표시

따라서 “공식처럼 보이는 페이지” 하나만으로 authority를 자동 선택하면 안 된다.

### 대백저축은행

2026-08-23 live HTTP capture에서 인터넷/모바일 × 단리/복리 12개월 nominal rate가 모두 4.10%로 재현됐다.

- forensic run: `32635180304`
- artifact: `9492104054`
- artifact SHA-256: `27fac90b077761ed4a04475b45452acf878574d4c7ef89fd92cb152e21747a6a`

이 사례는 **raw response + capture time + artifact digest**를 함께 남겨야 historical truth를 재검토할 수 있음을 보여준다.

---

# 7. 개선 Track D — Strategy release-readiness 패키지

**우선순위: 데이터 신뢰성 Track A~C 이후 / Release decision**

## 7.1 목표

Strategy를 더 개발하는 것과 실제 production에 공개하는 결정을 분리한다.

현재 runtime contract는 충분히 강화됐으므로 다음 단계는 새 시각효과 추가가 아니라 **공개 의사결정에 필요한 증거 묶음**을 만드는 것이다.

## 7.2 Release-readiness 패키지에 포함할 것

1. 현재 main SHA
2. General CI 결과
3. production-data Strategy runtime E2E 결과
4. desktop/mobile evidence artifact
5. current source discrepancy summary
   - P0/P1/P2/P3
   - ambiguity count
   - official contradiction count
6. Strategy가 사용하는 canonical/source contract 설명
7. 알려진 limitation 및 사용자 표시 문구 확인
8. rollback/disable 경로
9. Release Gate ON 전 최종 수동 체크리스트

## 7.3 Gate 조건

Release Gate ON은 다음과 논리적으로 분리한다.

- `implementation_ready`
- `runtime_verified`
- `data_risk_reviewed`
- `user_approved_release`

앞의 세 조건이 모두 충족되어도 마지막 `user_approved_release`가 없으면 OFF 유지다.

## 7.4 다음 UI 개선 판단

source discrepancy를 Strategy에 경고/배지로 직접 노출할지는 별도 제품 결정으로 둔다.

먼저 다음을 확인해야 한다.

- 실제 사용자 의사결정에 필요한 경고 수준인가
- 단순 audit-only noise가 되는가
- canonical 값을 “틀린 값”처럼 오해하게 만들지 않는가

따라서 이번 master plan은 Strategy warning UI를 자동 착수 항목으로 확정하지 않는다.

---

# 8. 개선 Track E — 제품 기능 후속

**우선순위: 중기 / 데이터 신뢰성·release readiness 이후**

## E1. 우대조건 구조화 완성

현재 `base_rate`, `max_rate`, raw preference text, preference taxonomy/filter는 존재하지만 조건 단위 구조화는 완결되지 않았다.

후속 후보:

- 조건 문장 분해
- 표준 condition code 매핑
- 조건별 `add_rate`
- `mandatory`
- `stackable`
- 원천 미제공 / 명시적 없음 / 조건 있음 분리 유지

주의:

- 원천에 없는 우대금리를 추정하지 않는다.
- `base_rate`로 `max_rate`를 채우지 않는다.

## E2. Manual Override / 관리자 편집

현재 정적 사이트 구조에서는 입력/충돌/감사 흐름이 완결되지 않았다.

구현 전에 먼저 결정할 것:

- 서버 runtime을 둘지
- GitHub/config 기반 운영으로 유지할지
- 원천값과 수동값을 화면에서 어떻게 구분할지
- override history/audit trail을 어떻게 보존할지

이 결정 전에는 관리자 UI부터 만들지 않는다.

## E3. Excel export

CSV/JSON이 이미 존재하므로 XLSX는 편의 기능이다.
데이터 신뢰성보다 우선하지 않는다.

## E4. KFCC/NH 추가 상품 영역

- KFCC 요구불예탁금 금액구간 파싱
- NH local 입출금식 surface

둘 다 실제 source fixture/contract를 먼저 확보한 뒤 parser를 설계한다.

---

# 9. 개선 Track F — 운영·성능·복구

**우선순위: 병행 가능하나 측정 우선**

## F1. repo-wide production smoke coverage 감사

Strategy에는 production-data runtime E2E가 이미 존재한다.
따라서 새 smoke를 무조건 추가하지 않고 먼저 검색/메인 화면/API/Strategy 중 어디가 실제 production runtime evidence 없이 남는지 coverage gap을 감사한다.

gap이 확인된 영역만 자동화한다.

## F2. payload/browser 성능 baseline

Strategy runtime에서 현재 `strategy-table.json`은 약 21.2MB / 326,703 rows 수준이다.

구조를 sharding/lazy loading으로 복잡하게 만들기 전에 측정한다.

- fetch/decompress
- JSON parse
- first meaningful render
- 필터 latency
- peak memory
- desktop/mobile 차이

측정값이 실제 문제를 보일 때만 구조 변경을 한다.

## F3. collector reliability

NH/KFCC 등 장시간 외부 수집은 병렬화를 먼저 하지 않는다.

순서:

1. latency/timeout/retry 분포 측정
2. transient failure 분류
3. bounded retry + jitter/backoff 검토
4. source-friendly pacing 확인
5. 병렬화가 필요하면 근거 확보 후 제한 적용

## F4. retention / restore drill

과거 roadmap의 “raw 1년 보존” 요구는 아직 장기 정책으로 확정되지 않았다.

결정 필요:

- raw 1년 보존을 계속 필수 요구로 둘 것인가
- 현재 artifact retention과 R2 snapshot이 어떤 요구를 충족/미충족하는가
- restore 무결성을 얼마나 자주 drill할 것인가

정책 확정 전 대규모 archive 비용을 발생시키지 않는다.

## F5. 문서 hygiene

이 master spec이 승인/merge되면 `docs/roadmap.md`와 `docs/specs/CURRENT.md`에서 미래 작업 링크를 최신화한다.

단, 과거 spec/정찰 기록은 삭제하지 않는다. 뒤집힌 판단의 history를 보존한다.

---

# 10. 권고 실행 순서와 PR 경계

## Phase 1 — Data Trust Closure

### PR/작업 A1
대신저축은행 P1 2건 forensic evidence

### PR/작업 A2
DH저축은행 P3 4건 forensic evidence

### PR/작업 B1
payment-method ambiguity 51건 census + impact report

**Phase 1 종료 조건**

- 현재 queue 6건 각각에 재현 가능한 근거가 있음
- ambiguity 51건의 구조를 설명할 수 있음
- P0/P1/P2/P3가 단순 숫자가 아니라 artifact/provenance와 연결됨
- canonical/source authority는 임의 변경되지 않음

## Phase 2 — Evidence Automation

### PR C1
queue-targeted direct-bank evidence capture MVP

### PR C2
historical queue trend / evidence freshness reporting

**Phase 2 종료 조건**

- 중요한 mismatch가 발생하면 같은 절차로 evidence를 다시 캡처 가능
- raw response artifact + digest + capture/effective time을 재현 가능
- audit 실패와 canonical collection failure가 의도대로 분리됨

## Phase 3 — Strategy Release Decision

### PR/문서 D1
release-readiness package 생성

### 사용자 결정 D2
Production Strategy Release Gate ON/OFF

**Phase 3 종료 조건**

- implementation/runtime/data risk를 한 화면 또는 한 문서에서 확인 가능
- 사용자가 Release Gate를 별도로 승인하거나 보류할 수 있음

## Phase 4 — Product / Operations

우대조건 구조화, 관리자 편집, 추가 상품, XLSX, 성능, retention 등을 사용자 우선순위에 따라 개별 Issue/PR로 진행한다.

---

# 11. 공통 Definition of Done

향후 각 구현 PR은 최소 다음을 만족해야 완료로 판정한다.

## Targeted

- 해당 요구를 직접 깨뜨리는 regression test 또는 재현 가능한 evidence 존재

## Regression

- repository가 요구하는 lint/test/build/migration contract 통과

## Runtime / Data

- UI면 가능한 browser runtime
- 데이터면 production R2 read-only 또는 동등한 actual-data evidence
- 외부 source면 실제 source response/evidence

## Adversarial

- “내 구현이 틀렸다고 가정”한 self-review
- 새 P0/P1 blocking review 0
- unresolved review thread 확인

## Safety

- canonical mutation 여부 명시
- source authority 변경 여부 명시
- DB/schema/migration 여부 명시
- production write 여부 명시
- Release Gate 변경 여부 명시

## Report

검증하지 못한 항목은 반드시 `미검증`으로 남긴다.

---

# 12. 외부 리뷰 패키지

이 문서는 외부 리뷰어가 저장소 전체 history를 처음부터 읽지 않아도 핵심 의사결정을 검토할 수 있게 한다.

## 12.1 추천 리뷰 관점

가능하면 다음 3개 관점을 분리해서 받는다.

1. **Data Engineering / Identity**
   - 6D source identity와 payment-method fail-closed가 안전한가
2. **Financial Data Governance / Auditability**
   - freshness와 authority의 분리가 적절한가
   - provenance가 업무상 추적 가능성에 충분한가
3. **Release / Runtime Engineering**
   - Strategy runtime evidence와 Release Gate 분리가 충분한가

한 사람이 모두 볼 수 있으나, 결론을 섞지 않고 분야별 finding을 남기는 것을 권고한다.

## 12.2 리뷰어가 먼저 읽을 문서

10~15분 빠른 리뷰 순서:

1. 이 문서
2. `docs/specs/CURRENT.md`
3. `docs/specs/20260823-source-discrepancy-payment-ambiguity-v4.md`
4. `docs/specs/20260820-source-discrepancy-priority-triage-v1.md`
5. `docs/data-trust.md`
6. `docs/specs/20260822-public-structural-v2-decision-cockpit-final.md`
7. `docs/specs/20260819-strategy-main-production-data-runtime-e2e.md`

관련 change history:

- PR #191 — source discrepancy post-merge hardening
- PR #190 — Strategy runtime host/mobile pseudo-label hardening
- PR #192 — Strategy Response Surface rendered-box hardening

## 12.3 외부 리뷰 핵심 질문

리뷰어는 최소 아래 질문에 답해 달라고 요청한다.

1. **6D identity + conditional payment-method ambiguity**가 서로 다른 금융상품 surface를 잘못 합칠 위험을 충분히 막는가?
2. `payment_method`를 즉시 7D strict key로 올리지 않는 현재 판단에 반례가 있는가?
3. freshness를 authority와 분리하고, bank-direct evidence도 자동 우선하지 않는 원칙이 적절한가?
4. raw locator / artifact hash / effective time / capture time이 source dispute를 재현하기에 충분한가?
5. P0~P3가 “정답 점수”가 아니라 “조사 우선순위”로만 사용되는가?
6. queue-targeted direct-bank capture가 전체 crawler보다 안전한 첫 단계인가?
7. canonical을 조용히 변경할 수 있는 숨은 execution path가 남아 있는가?
8. Strategy Release Gate 전에 추가로 필요한 runtime/data evidence가 있는가?
9. Phase 1~4 순서에서 위험도가 높은 작업이 편의 기능 뒤로 밀려 있지 않은가?
10. 이 문서에서 P0/P1 수준으로 수정해야 할 모순·누락은 무엇인가?

## 12.4 리뷰 finding 형식

외부 리뷰는 다음 형식으로 받으면 바로 구현 backlog로 전환하기 쉽다.

```text
Severity: P0 / P1 / P2 / P3
Section: 문서 절 또는 코드 경로
Finding: 무엇이 잘못됐거나 위험한가
Evidence: 반례 / 코드 / 데이터 / source
Required change: 반드시 바꿔야 하는 최소 범위
Optional improvement: 있으면 별도
```

P0/P1이 있으면 해당 Phase 구현 전에 먼저 해소한다.

---

# 13. 아직 결정하지 않은 사항

다음은 이 문서에서 임의 결정하지 않는다.

1. `payment_method`를 canonical/stable identity에 영구 편입할지
2. bank-direct evidence를 어떤 조건에서 source authority 판단에 사용할지
3. discrepancy warning을 Strategy 사용자 UI에 직접 노출할지
4. raw 원본 1년 보존을 의무화할지
5. Manual Override를 서버형으로 만들지 GitHub/config 운영으로 만들지
6. Production Strategy Release Gate를 언제 ON 할지

이 항목들은 evidence와 사용자 결정 후 별도 spec/PR에서 확정한다.

---

# 14. 이 문서 자체의 범위

이번 문서 PR에서 **하는 것**:

- 현재 검증 상태를 기준점으로 고정
- 향후 개선 우선순위 정렬
- 각 Track의 안전 경계/Acceptance 정의
- 외부 리뷰 질문과 finding format 준비

이번 문서 PR에서 **하지 않는 것**:

- 코드 변경
- canonical 금리 변경
- source precedence/authority 변경
- DB/schema/migration 변경
- collector/scheduler 변경
- production R2/rate-data write
- Strategy 기능 변경
- Production Strategy Release Gate 변경
- Issue #98 종료

---

# 15. 최종 성공 기준

이 master plan이 성공적으로 소진됐다고 말하려면 다음 상태가 되어야 한다.

- #98의 현재 high-priority discrepancy가 evidence로 설명 가능하다.
- ambiguity가 단순 예외가 아니라 측정·추적 가능한 데이터 품질 상태다.
- 공식 홈페이지 evidence가 재현 가능한 artifact로 수집된다.
- source authority를 자동 추정하지 않아도 운영자가 왜 값이 다른지 판단할 근거가 있다.
- Strategy 공개 여부를 구현 완료와 분리된 Release Gate에서 결정할 수 있다.
- 이후 우대조건/관리자/성능 등 편의·제품 개선을 데이터 신뢰성 훼손 없이 진행할 수 있다.

핵심 원칙은 변하지 않는다.

> **더 많은 기능보다 먼저, 어떤 숫자가 어디서 왔고 왜 다른지 설명할 수 있어야 한다.**
