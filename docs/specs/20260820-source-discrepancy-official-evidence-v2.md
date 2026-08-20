# 저축은행 원천 교차검증 v2 — 공식 홈페이지 evidence 정책

기준일: 2026-08-20

관련 Issue: #98

## 1. 목적

v1의 `FSB ↔ 금융상품한눈에(finlife_savings_bank)` read-only 교차검증에
**개별 저축은행 공식 홈페이지 evidence를 실제 운영 감사 입력으로 연결**한다.

이번 단계도 canonical 금리를 수정하지 않는다. 목표는 어느 원천을 자동으로
승자로 고르는 것이 아니라 다음 질문에 근거를 남기는 것이다.

1. FSB와 FINLIFE가 현재 같은 상품/기간에 같은 금리를 말하는가.
2. 개별 저축은행 공식 페이지는 어느 쪽과 일치하는가.
3. 개별 은행의 공식 페이지들끼리도 일관적인가.
4. 공식 evidence가 충돌하면 authority 판정을 즉시 중단할 수 있는가.

## 2. 이번 Evidence Gate에서 확인한 사실

2026-08-20 11:30 KST에 공식 사이트를 직접 확인해
`docs/evidence/source-discrepancy/20260820-official-savings-bank.json`으로 고정했다.

### 청주저축은행 — 정기적금

공식 상품공시:
`https://www.cheongjubank.com/ProdList_001.act?rnum=15`

- 금리 기준일: 2026-06-18
- 6개월 이상~12개월 미만: 2.10%
- 12개월 이상~24개월 미만: 3.80%

과거 #98 mismatch queue의 6/12개월을 다시 확인할 수 있는 직접 evidence다.

### 키움예스저축은행 — e-회전yes정기예금

공식 상품공시:
`https://www.kiwoomyesbank.com/ProdList_001.act?rnum=55`

- 12개월 단리 약정이율: 3.90%
- 복리 연수익률: 3.97%

공식 금리변경 공지:
`https://www.kiwoomyesbank.com/CstInfo_001.act`

- 게시일: 2026-08-07
- 시행일: 2026-08-10
- e-회전yes정기예금 / SB톡톡회전yes정기예금 변경 후: 4.05%

즉 같은 은행의 공식 surface 두 곳이 현재 서로 다른 nominal rate를 말한다.
따라서 **개별 저축은행 홈페이지를 단일 truth source로 자동 승격하면 안 된다.**

production source에는 같은 상품이
`e-회전yes정기예금(1년단위 변동금리상품) (인터넷뱅킹, 스마트뱅킹)`으로 저장되어 있다.
공식 페이지의 상품개요가 1년 회전주기 변동금리 상품임을 명시하고 인터넷/스마트뱅킹
variant와 의미가 일치하므로 이 dated evidence에만 해당 문자열을 `comparison_product`로
지정한다. 이 alias는 official evidence를 현재 source 행에 붙이는 데만 사용한다.

### 대백저축은행 — 애플정기예금복리식(인터넷뱅킹)

공식 상품공시:
`https://www.debecbank.co.kr/bbs/ProdList_001.act?rnum=27`

- 12개월 단리식 약정이율: 4.00%
- 복리식 연평균수익률: 4.07%

교차검증의 nominal `base_rate/max_rate`에는 4.00%만 사용한다.
4.07%는 복리 수익률이며 동일 의미의 nominal rate로 취급하지 않는다.

공식 페이지의 상품명이 source의 비교 상품명과 다를 수 있어,
이 evidence에만 수동 `comparison_product=애플정기예금`을 지정한다.

## 3. v2 evidence 계약

각 record는 v1 필수 필드에 더해 다음 메타데이터를 사용할 수 있다.

- `evidence_id`: evidence record 고유 식별자
- `evidence_group`: 동일 truth question을 묶는 그룹
- `evidence_kind`: `product_disclosure`, `rate_change_notice` 등
- `comparison_product`: official evidence를 FSB/FINLIFE 행에 붙이기 위한
  **수동 검증 alias**
- `join_channel`, `interest_method`, `note`: 원문 의미 보존용 메타데이터

`comparison_product`는 오직 **official evidence → source 감사 매칭**에만 쓴다.

금지:

- FSB ↔ FINLIFE 자동 상품 alias로 사용
- `products` identity 변경
- canonical product merge
- source precedence 변경

report에는 `official_product`를 별도로 남겨 실제 공식 페이지 이름을 보존한다.

## 4. 공식 evidence group 판정

동일 `evidence_group`의 non-null 금리를 비교한다.

### `consistent`

같은 group의 공식 evidence가 같은 금리를 말한다.

이 경우에만 각 source와의 일치 여부를 참고 신호로 계산한다.

### `conflict`

같은 group에서 `base_rate` 또는 `max_rate`가 서로 다르다.

이 경우 source 매칭 성공 여부보다 conflict gate가 우선한다.

- `source_support.primary = blocked_by_official_conflict`
- `source_support.secondary = blocked_by_official_conflict`
- `reconciliation_signal = official_conflict`

으로 고정한다.

**공식 evidence 충돌 상태에서 source authority를 자동 판정하지 않는다.**

### `incomplete`

공식 evidence에 비교 가능한 금리 자체가 없다.

## 5. Source support 신호

공식 group이 `consistent`일 때만 계산한다.

- `supported`
- `not_supported`
- `partial`
- `not_matched`
- `insufficient`

이를 조합한 report 신호:

- `both_supported`
- `primary_supported`
- `secondary_supported`
- `mixed_support`
- `neither_supported`
- `insufficient_official_evidence`
- `official_conflict`

이 신호는 **감사 참고용**이다.

`scope.official_evidence_authority = read_only_support_only`를 계약으로 두며,
어떤 신호도 canonical 자동 수정이나 source precedence 변경을 유발하지 않는다.

## 6. captured_at와 effective_at

두 시각을 혼동하지 않는다.

- `captured_at`: 해당 URL을 실제로 확인한 시각
- `effective_at`: 공식 문서가 명시한 금리 시행/기준일

상품공시 페이지에 시행일이 없으면 `effective_at`을 추정하지 않는다.
`captured_at`이 최근이라는 이유만으로 그 금리가 같은 날 시행됐다고 해석하지 않는다.

## 7. 운영 감사 경로

`source-discrepancy-audit.yml`은 production R2 DB를 **runner-local copy로만 복원**한다.

실행 경로:

`production R2 restore → local migration → FSB/FINLIFE discrepancy →
dated official evidence → official group conflict/support → artifact`

변경하지 않는 것:

- production DB
- R2 canonical state
- `rate-data`
- Vercel
- source precedence
- strategy calculation
- collection schedule

감사 artifact에는:

- `work/source-discrepancy-report.json`
- 사용한 dated official evidence JSON

을 함께 보존한다.

## 8. 왜 자동 홈페이지 crawler를 이번 PR에 넣지 않는가

세 은행만 확인해도 페이지 구조가 동일하지 않고,
키움예스 사례처럼 **같은 공식 사이트 안에서도 상품공시와 시행 공지가 충돌**한다.

따라서 crawler를 먼저 만들면:

1. 어느 페이지를 우선할지 근거 없이 정해야 하고
2. 최신 공지와 stale 상품공시를 잘못 합칠 수 있으며
3. 결과를 canonical에 쓰지 않더라도 잘못된 authority signal을 만들 수 있다.

이번 PR은 먼저 evidence schema와 conflict gate를 고정한다.
자동 evidence 수집은 이 계약 위에서 별도 단계로 진행한다.

## 9. Acceptance

이번 v2 완료 조건:

- 3개 이상 저축은행의 공식 evidence를 dated JSON으로 보존
- FSB/FINLIFE 현재 production snapshot과 함께 read-only audit 실행
- official evidence 내부 충돌을 별도 상태로 surfaced
- 수동 evidence alias가 source-source identity를 변경하지 않음을 테스트
- canonical observation count/값을 수정하지 않음
- Ruff / pytest / migration / production R2 audit 통과
- 결과 artifact와 Issue #98 코멘트에 실제 runtime evidence 기록

## 10. 다음 단계

v2 결과를 보고 다음을 별도 판단한다.

1. 현재 mismatch queue에서 공식 evidence가 필요한 우선순위 자동 생성
2. 안전한 product alias registry
3. 개별 저축은행 공식 evidence 수집 adapter/crawler
4. freshness/authority ADR
5. Strategy의 `원천 일치 / 기준일 차이 / 공식 evidence 충돌` 경고 UI

canonical 자동 보정은 별도 명시적 승인 전까지 범위 밖이다.
