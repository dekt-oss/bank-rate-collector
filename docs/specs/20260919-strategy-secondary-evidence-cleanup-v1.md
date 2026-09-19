# Strategy Secondary Evidence Cleanup v1

작성일: 2026-09-19  
대상: `dekt-oss/bank-rate-collector` Strategy production surface  
선행 의존: PR #338 Lean IA v3

## 1. 목적

Lean IA v3 이후 남은 Issue #303의 최소 잔여 범위를 처리한다.

핵심은 기능 추가가 아니라 다음 두 가지다.

1. 1차 판단에 필요하지 않은 큰 상세표는 기본 접힘한다.
2. 사용자 화면에 남은 개발/계약 용어를 업무용 표현으로 바꾸되 machine contract는 보존한다.

## 2. 변경

### 2.1 금리별 수신반응 상세표

`#rate-response-wrap`은 계산/DOM을 그대로 유지하되 기본 접힌 `<details>` 안으로 이동한다.

summary:
- 금리별 수신반응 상세
- +5bp · +10bp · +15bp · 제안금리 비교

사용자가 같은 세션에서 직접 펼친 뒤 입력값이 바뀌거나 재계산돼도 자동으로 다시 접지 않는다.

### 2.2 visible terminology

아래 사용자 visible copy를 정리한다.

- `CANONICAL` → `공식 비교기준`
- `D1 Structure Evidence` → `조건 구조 근거`
- `actual forecast` 성격의 영문 표현 → `실제 예측치`
- `Stage E` → `별도 보정 단계`

원 계약 식별자는 `data-contract-label`에 보존한다.

## 3. 비범위

변경하지 않는다.

- 예측식 / β·γ / 금리별 수신반응 계산
- TOP5 ranking population / tie
- preference intelligence 계산
- source precedence
- identity/dedupe
- DB/schema/migration/API
- Strategy production publication
- PR #338의 Lean IA 순서/중복 suppression 계약

## 4. 테스트

- owner presentation unit tests
- business label + machine marker contract tests
- browser smoke:
  - 수신반응 상세 기본 closed
  - 클릭 후 open
  - 입력/재계산 후 open 유지
  - 업무용 visible label
  - 기존 machine marker 유지
- Ruff
- full pytest
- empty DB migration
- production-data Strategy runtime E2E

## 5. Merge boundary

이 작업은 PR #338에 쌓는 stacked follow-up이다.

PR #338이 main에 merge되기 전에는 main 기준 독립 merge하지 않는다.
자동 merge하지 않는다.
