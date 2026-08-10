# NH 지역농축협 이자방식 Evidence — 2026-08-10

## 목적

P0-3에서 기존 `복리 문구가 없으면 simple` 규칙을 수정하기 전에 실제 NH 원천이
단리·복리를 어떻게 표현하는지 확인한다. 원천이 직접 말하지 않은 이자방식은
추정하지 않는다.

## 증거 원본

- 공식 원천: `wmall.nonghyup.com`
- 기존 전국 성공 수집: GitHub Actions `Collect rates` run `31326136819`
- 수집 artifact: `collection-run-31326136819` / artifact ID `9044402286`
- 대상 상세 화면:
  - `SFDPW0163R` 거치식
  - `SFDPW0164R` 적립식
- 상세 HTML: **9,742개**
- 파싱 행: **198,670행**
- Evidence 재검증 run: `31380434894`
- Evidence artifact: `p0-interest-nationwide-31380434894` / ID `9059641596`

## 전수 결과

| 분류 | 행 수 | 근거 |
|---|---:|---|
| 직접 복리 | 29,100 | 상품명에 `복리` 또는 비고에 `월복리` 직접 명시 |
| 직접 단리 | **0** | 전국 원본에서 `단리` 직접표현 없음 |
| 복리 언급만 존재 | 19,472 | `e-joy 인터넷예금 우대금리` 대상상품 목록에 `복리식 정기예탁금` 언급 |
| 직접 근거 없음 | 150,098 | 단리·복리 계산방식 직접표현 없음 |

주요 패턴:

- `복리식정기예탁금` 19,472행 — `정기예탁금 이자를 월복리로 계산` → `compound`
- `더불어자유적립적금` 9,628행 — `약정이율을 월복리로 적용` → `compound`
- `정기예탁금` 38,944행 — `만기이자지급식 기준`만 있음 → `unknown`
- `만기자유정기예탁금` 38,944행 — 계산방식 직접표현 없음 → `unknown`
- `정기적금` 28,884행 — 계산방식 직접표현 없음 → `unknown`
- `자유적립적금` 24,070행 — 계산방식 직접표현 없음 → `unknown`
- `e-joy 인터넷예금 우대금리` 19,472행 — 대상상품 목록에 복리식 상품을 언급할 뿐
  우대금리 행 자체의 계산방식은 아님 → `unknown`

## 기존 DB와 대조

Evidence 확인 당시 운영 R2 DB 복사본의 NH 현재 variant 분포:

- `compound`: **48,572**
- `simple`: **150,098**
- `unknown`: 0

이 값은 원본 패턴과 정확히 대응한다.

```text
48,572 compound
= 29,100 직접 복리
+ 19,472 복리 언급만 있는 e-joy 우대금리

150,098 simple
= 150,098 직접 근거 없음
```

따라서 기존 parser가 만든 오분류 범위를 근거 있게 특정할 수 있다.

## 확정 contract

```text
상품명에 복리 직접표현 또는 비고에 월복리 직접표현
→ compound

상품명/비고에 단리 직접표현
→ simple

둘 다 없거나 서로 충돌
→ unknown
```

다음 역추론은 금지한다.

```text
복리가 아니므로 단리
단리가 아니므로 복리
대상상품 설명에 복리식 상품이 포함되므로 현재 행도 복리
```

`고정금리`·`변동금리` 열은 금리 변동방식이지 단리·복리 계산방식이므로 판정
근거로 쓰지 않는다.

## 기존 데이터 교정 범위

기존 observation/raw/provenance는 보존한다. `interest_method`는
`product_variants.variant_key` 구성요소이므로 다음 수집에서 새 variant 169,570개가
불필요하게 생기지 않도록 기존 variant를 in-place 교정하고 deterministic key를
같이 재계산한다.

- 기존 NH `simple` → `unknown`
- `e-joy 인터넷예금 우대금리`의 기존 NH `compound` → `unknown`
- 직접 복리 29,100행에 대응하는 variant는 `compound` 유지

재키잉 시 target key가 이미 존재하면 자동 병합하지 않고 migration을 실패시킨다.

## 운영 DB 복사본 전환 검증

최종 구현은 GitHub Actions run `31381656703`에서 운영 R2 DB 복사본으로 검증했다.
운영 R2와 `rate-data`에는 다시 쓰지 않았다.

- 복원 snapshot: `state/snapshots/20260810T191536-ff62ee92.sqlite3.gz`
- migration 전: `compound 48,572`, `simple 150,098`
- migration 후: `compound 29,100`, `unknown 169,570`, `simple 0`
- 전체 variants: **329,250 → 329,250**
- observations: **720,535 → 720,535**
- duplicate `variant_key`: **0**
- migration elapsed: **7.53초**
- migrated DB validation: **12/12 PASS**

같은 복사본에서 새 parser로 부산을 다시 실제 수집했다.

- run_id: `279b9ff8-595a-4fe7-b746-6f3f1a71be75`
- raw/parsed: `241 / 4,920`
- valid/error: `4,920 / 0`
- warning: `480`
- 최신 run interest 분포: `compound 720`, `unknown 4,200`, `simple 0`
- e-joy: `unknown 480`, `compound 0`
- 수집 후 전체 variants: **329,250** — 신규 variant 증가 없음

후속 snapshot과 전체 경로도 검증했다.

- stored-data validation: **12/12 PASS**
- dashboard/export/public site build: PASS
- P1-A gate: **27/27 PASS**
- runtime evidence artifact: `p0-interest-runtime-31381656703` / ID `9060281245`

전국 원천은 이미 성공 수집 raw 198,670행을 전수 분석했으므로, 동일 원천에 3시간
이상 추가 부하를 주는 전국 live 재수집은 하지 않았다. 실제 parser 전환 경로는
부산 120개 점포 실수집으로 검증했다.
