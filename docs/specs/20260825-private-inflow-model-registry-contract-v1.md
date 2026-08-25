# Private Inflow Model Registry Contract v1

- Date: 2026-08-25
- Parent Issue: #167
- Depends on: PR #207 / `inflow-calibration-protocol-v1`
- Base main: `7236a309c104330d00924addf6609df826202afd`
- Scope: 내부자료 수령 전 고정 가능한 **model lifecycle / evidence binding / human approval contract**
- Actual internal data/model artifact: public Git/GitHub 반입 금지
- Strategy UI / public forecast: 변경 없음

---

## 1. 목적

PR #207까지 다음이 준비됐다.

1. 허용 feature / leakage 금지
2. time-based expanding OOS split
3. 공통 backtest metric
4. incumbent/challenger promotion gate
5. `eligible_for_human_review`까지만 자동 판정

하지만 실제 내부자료가 들어온 뒤 좋은 challenger가 나왔다고 해도 아직 하나의 중요한 공백이 남는다.

> 어떤 정확한 실험 결과를 근거로, 누가, 언제, 어떤 모델을 champion으로 승인했는가?

이 기록이 없으면 다음과 같은 문제가 생길 수 있다.

- 다른 promotion report를 보고 승인한 모델로 바뀜
- 최신 모델 artifact와 평가 report가 서로 다른 실험에서 생성됨
- 사람이 승인하지 않았는데 코드가 champion으로 간주함
- 같은 scope에 active champion이 둘 이상 존재함
- 새 champion이 기존 champion을 대체했지만 이전 모델 상태가 불명확함
- registry 파일에 실제 coefficient / raw row / training diagnostics를 섞어 저장함

이번 contract는 이 경계를 코드로 고정한다.

---

## 2. Registry는 무엇을 저장하는가

Registry는 **model artifact 자체가 아니라 governance metadata**만 저장한다.

필수 핵심 항목:

- `registry_id`
- `model_id`
- `candidate_key`
- `scope_key`
- `lifecycle_status`
- `protocol_version`
- `experiment_id`
- `model_artifact_sha256`
- `training_data_fingerprint_sha256`
- `feature_schema_sha256`
- `promotion_report_sha256`
- `promotion_status`
- `training_cutoff_date`
- `evaluation_cutoff_date`
- human approval metadata

실제 private workspace에서는 위 digest가 가리키는 artifact/report를 별도로 보관한다.

Registry에 다음을 직접 embed하지 않는다.

- calibrated coefficient
- feature importance
- training diagnostics
- raw/internal rows
- model binary
- 고객/계좌 식별정보

---

## 3. Model lifecycle

v1 lifecycle은 다음 네 상태다.

```text
candidate
   ↓
eligible_for_human_review
   ↓
champion
   ↓
retired
```

### candidate

- fitting 결과 artifact는 존재할 수 있음
- promotion은 아직 평가하지 않았거나 blocked일 수 있음
- human approval 없음
- `effective_from_date` 없음

### eligible_for_human_review

- promotion report status가 정확히 `eligible_for_human_review`
- 아직 champion 아님
- human approval 없음
- 자동 활성화 없음

### champion

아래를 모두 요구한다.

1. known challenger candidate
2. exact protocol version
3. model/data/feature/promotion evidence SHA-256
4. promotion report가 `eligible_for_human_review`
5. `human_review_required=true`
6. `auto_promote=false`
7. 명시적 human approval
8. approval 시점이 evaluation cutoff 이후
9. effective date가 approval 이후
10. approval timestamp에 timezone/UTC offset 명시

### retired

과거 champion의 승인 evidence는 유지한다.
추가로 다음 retirement audit metadata를 요구한다.

- `retired_at`
- `retired_by`
- `retirement_ref`
- `retirement_reason`

`retired_at`에도 timezone/UTC offset을 요구하며, human approval이나 `effective_from_date`보다 앞설 수 없다.

---

## 4. Exact promotion evidence binding

Registry가 단순히 다음 문자열만 저장하면 충분하지 않다.

`promotion_status = eligible_for_human_review`

누군가 문자열만 바꾸면 잘못된 모델도 champion처럼 보일 수 있다.

따라서 실제 promotion report 전체를 canonical JSON으로 직렬화한 뒤 SHA-256을 계산한다.

```text
promotion report
    ↓ canonical JSON
SHA-256 digest
    ↓
registry.promotion_report_sha256
```

Champion 활성화 시 실제 private promotion report를 다시 digest하고 registry digest와 정확히 비교한다.

한 글자라도 report가 바뀌면 activation을 차단한다.

---

## 5. Human approval은 promotion과 별개다

Promotion engine의 책임:

> 이 challenger가 사람의 검토를 받을 조건을 만족하는가?

Human approver의 책임:

> 이 결과와 위험을 검토한 뒤 실제 champion으로 사용할 것인가?

따라서 promotion report가 통과해도 자동으로 champion이 되지 않는다.

Champion에는 최소 다음 approval metadata가 필요하다.

- `human_approved=true`
- `human_approver`
- `human_approval_at`
- `human_approval_ref`

`human_approval_at`은 timezone/UTC offset이 포함된 timestamp여야 한다. 승인·적용·퇴역의 순서를 모호한 로컬 시각으로 남기지 않는다.

`human_approval_ref`는 향후 내부 결재번호, 승인 기록 ID, 의사결정 문서 ID 등으로 연결할 수 있는 opaque reference다.

Public repository에는 실제 private registry row를 commit하지 않는다.

---

## 6. Scope당 active champion은 하나

`scope_key`는 모델이 담당하는 예측 범위를 나타내는 opaque identifier다.

예:

- `portfolio:all`
- 향후 충분한 데이터가 있는 경우 `channel:online`
- 향후 충분한 데이터가 있는 경우 특정 상품군 scope

Registry snapshot에서 같은 `scope_key`에 `champion`이 둘 이상 있으면 invalid다.

이 규칙은 private inference가 어느 모델을 호출할지 모호해지는 것을 막는다.

---

## 7. Champion 교체

새 champion이 기존 champion을 대체할 때는:

1. 이전 model을 `retired`로 기록
2. 새 champion의 `supersedes_model_id`에 이전 model ID 기록
3. 두 model의 `scope_key`가 동일해야 함
4. retirement timestamp는 이전 model의 승인·적용 이후여야 함

새 champion이 아직 active인 기존 champion을 직접 가리키는 상태는 invalid다.

즉 replacement는 다음 순서로 처리한다.

```text
old champion
   ↓ explicit retirement
old retired
   ↓
new champion --supersedes--> old retired
```

---

## 8. Public / Private 경계

이 contract의 **코드와 schema 정의**는 public repository에 둘 수 있다.

실제 값은 private/local runtime에만 둔다.

### Public 가능

- registry field 이름
- lifecycle 규칙
- digest 알고리즘
- human approval 요구조건
- synthetic tests

### Public 금지

- 실제 internal data fingerprint와 그것이 연결되는 원본
- 실제 trained model artifact
- 실제 coefficient
- 실제 feature importance
- 실제 training diagnostics
- 실제 private promotion report
- 실제 내부 승인 문서 내용

공개 Strategy에는 registry 자체를 전달하지 않는다.
기존 `inflow-public-forecast-v1` allowlist를 통과한 예측 결과만 전달한다.

---

## 9. 이번 범위에서 하지 않는 것

- 실제 내부자료 mapping
- 실제 feature table 생성
- 실제 모델 fitting
- 실제 model artifact 생성
- 실제 promotion report 생성
- 실제 private registry 생성/저장
- private inference endpoint 배포
- Strategy UI 변경
- public forecast schema 변경
- β/γ 변경
- DB/schema/migration
- 자동 model activation

---

## 10. 내부자료 도착 후 실제 사용 순서

```text
internal source files
   ↓
private adapter / E0 intake
   ↓
as-of feature table
   ↓
model fitting
   ↓
expanding OOS backtest
   ↓
promotion report
   ↓ digest binding
registry eligible_for_human_review
   ↓
human review
   ↓ explicit approval
registry champion
   ↓
private inference
   ↓
public forecast allowlist
   ↓
Strategy
```

새 모델이 기존 champion을 대체할 때는 old champion retirement를 먼저 기록한다.

---

## 11. Acceptance criteria

- registry field allowlist가 fail-closed로 고정됨
- unknown/private embedded field가 차단됨
- `structural_v2_reference`는 private calibrated challenger로 등록되지 않음
- promotion report digest가 deterministic함
- champion activation 시 exact promotion report digest가 일치해야 함
- blocked/tampered promotion report는 activation 불가
- human approval 없는 champion은 invalid
- approval이 evaluation cutoff보다 빠르면 invalid
- approval/retirement timestamp는 timezone 명시가 필수
- retirement가 approval/effective date보다 빠르면 invalid
- same scope에 active champion 2개 이상이면 invalid
- replacement target은 same scope의 retired model이어야 함
- 실제 coefficient/raw data/diagnostics/model artifact는 포함하지 않음
- public Strategy/public forecast/DB/schema/collector 계산은 변경하지 않음
- targeted Inflow Engine Contract + General CI 통과

---

## 12. 다음 남은 실제 작업

### 내부자료 없이 추가 가능

이 contract 이후 남는 pre-data 작업은 많지 않다.

- synthetic end-to-end private research rehearsal
  - fake schema fixture로 `intake → as-of gate → backtest evaluator → promotion → registry` 연결성 검증
- private runtime 운영 runbook 정리
  - actual data 위치
  - artifact/report/registry 보관 구조
  - backup/rollback 절차

다만 실제 모델 성능 개선과 calibration correctness는 synthetic rehearsal로 증명할 수 없다.

### 실제 내부자료 필요

- source-specific mapping
- 실제 feature coverage / missingness audit
- 실제 model fitting
- 실제 OOS backtest
- governance threshold 재검토
- 실제 champion 선정
- private inference 연결
- forecast drift / error 운영 모니터링
