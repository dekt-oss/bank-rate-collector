# 전략 대시보드 데이터 엔진 계약 — 2026-08-14

## 상태

- 대상: `strategy.html` 실험 화면
- 운영 Release Gate: **OFF 유지**
- canonical 자동 보정: **하지 않음**
- DB/schema migration: **없음**

## 배경

전략 대시보드의 현재 KPI/TOP5/시뮬레이터는 공개 `table.json`을 사용하지만,
최근 30일 변경이력과 기간별 추이는 SQLite를 직접 읽었다. 공개 비교표에는
`config/presentation.yaml`의 source precedence가 적용되므로 FSB가 존재하는
저축은행 비교축에서 `finlife_savings_bank`는 물러난다. 기존 전략 이력에는 이
규칙이 없어 현재값과 과거값의 시장 universe가 달라질 수 있었다.

또한 전략 브라우저 집계는 `기관명 + 상품명 + 기간` 문자열을 상품 identity로
사용했다. canonical DB에는 stable `product_id`가 있으므로 전략 순위·평균은 이를
사용해야 한다.

## 1. Source precedence

전략 현재값·변경이력·기간별 추이는 동일한 precedence를 사용한다.

현재 설정:

```yaml
db_only_sources:
  - finlife_savings_bank
```

동일 `정규화 기관 + 상품유형 + 가입기간`에 non-retreating source가 유효하면
retreating source 관측은 전략 시장통계에서 제외한다. primary coverage가 없는
비교축에서는 secondary source가 fallback으로 남는다.

이 규칙은 canonical 관측을 삭제하거나 수정하지 않는다. 전략용 read-only 집계에만
적용한다.

## 2. 기간별 추이

각 정상 수집일의 snapshot 시점에 `valid_from <= t < valid_to`인 관측을 복원한 뒤:

1. source precedence 적용
2. canonical `product_id`별 최고 `max_rate`를 상품 대표값으로 선택
3. 상품 대표값의 평균·최고·비교상품 수 계산
4. 고려저축은행은 동일 snapshot의 당사 상품 대표 최고금리 중 최고값을 표시

현재값을 과거에 소급하지 않는다.

## 3. 최근 30일 변경 이벤트

기존 이벤트 단위는 유지한다.

```text
run + product_id + previous_max_rate + max_rate
```

동일 실행에서 같은 상품의 여러 variant가 같은 전후금리로 움직이면 1개 상품
이벤트로 센다. 이후 변경 시점에 source precedence를 적용하여 secondary source의
중복 시장 이벤트를 제거한다.

source metadata가 없는 최소/legacy fixture에서는 precedence 판정을 할 수 없으므로
기존 동작으로 fail-open한다. 실제 운영 schema에는 source metadata가 존재한다.

## 4. Stable product identity

전략 Release Gate가 켜진 빌드에서만 기존 `table.json`에 압축 `product_id` 열을
추가한다.

- 기본 공식 빌드: 기존 table 계약 유지, `product_id` 추가 안 함
- 전략 Preview/release 빌드: canonical current observation을 read-only 조회하여
  각 table row와 `product_id`를 연결
- 저축은행 정기예금 6/12/24/36개월 전략 비교행에서 product_id를 찾지 못하면
  이름 기반 fallback으로 조용히 계산하지 않고 build 실패
- DB에는 어떠한 write도 하지 않음

전략 브라우저의 상품 대표 key는 `product_id + 기간`을 우선 사용한다.

## 5. 날짜 semantics와 우대조건 인사이트

`source_effective_at`은 source마다 동일한 업무 의미라고 확정하지 않는다.
전략 UI에서는 이를 **원천 기준일**로 표현한다.

우대조건 인사이트의 날짜는 전체 12개월 시장에서 가장 최신인 날짜가 아니라,
해당 우대조건 태그가 실제 확인된 상품들의 최신 `source_effective_at`을 사용한다.

## 6. Production evidence

2026-08-14 scheduled Collect #102 이후 production R2 snapshot을 read-only로 복원하여
FINLIFE identity를 재감사했다.

- latest FINLIFE run: `4598d38c-b87c-469a-8c29-14b95d842f36`
- checked: 4,000
- unknown service: 0
- identity mismatch: **0**

동일 snapshot에서 source discrepancy baseline:

- FSB representative products: 2,166
- FINLIFE representative products: 2,261
- exact matches: 2,149
- max-rate mismatch, same reference date: 2
- max-rate mismatch, different reference date: 18
- total max-rate mismatch: **20**
- unmatched product: 111
- source only: 18

이 20건은 조사 queue이며 어느 원천이 맞는지 자동 판정하거나 canonical을 보정하지
않는다.

## 7. 검증 기준

- CI Ruff 통과
- 전체 pytest 통과
- FSB와 FINLIFE가 의도적으로 다른 fixture에서 current precedence와 동일한 이력
  universe 확인
- secondary-only 기관은 fallback으로 유지
- 전략 OFF build의 table에 `product_id`가 추가되지 않음
- 전략 ON build의 전략 비교행은 stable `product_id` 확보
- 우대조건 날짜는 해당 태그 기준일을 사용
- DB row count 불변
- Release Gate OFF 유지
