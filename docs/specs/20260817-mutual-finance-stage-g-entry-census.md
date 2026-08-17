# 상호금융 최고금리 Stage G Entry Census — 2026-08-17

- 상태: **decision / evidence-gate**
- 대상: Stage G1(KFCC), Stage G2(NH local)
- 선행 문서:
  - `20260817-mutual-finance-max-rate-stage-f-evidence.md`
  - `20260817-mutual-finance-max-rate-claude-review.md`
- 원칙: 공식 원천만 사용하고 이름 유사도·금리 추정·`base_rate` fallback을 금지한다.

## 1. 결론

| Gate | 판정 | 이유 |
|---|---|---|
| KFCC G1 | **BLOCKED 유지** | 중앙 공식 원본의 `gmgoCd` 명부에는 개별 금고 홈페이지를 결정론적으로 연결할 URL/도메인/공식 site key가 없다. 이름 매칭으로 우회하지 않는다. |
| NH local G2 | **ENTRY GO** | 최신 전국 공식 raw에서 e-joy 우대행의 대상상품·기간구간·가산방식이 전수 일관되고, 같은 `brc`의 source product + term에 모호성 없이 연결할 수 있다. 구현은 별도 `join_channel=internet` variant에만 허용한다. |

`ENTRY GO`는 수집기/화면 활성화 완료를 뜻하지 않는다. G2 구현 PR에서 parser/variant/traceability/downstream validation을 통과한 뒤에만 canonical `max_rate` capability를 열 수 있다.

---

## 2. 고정 증거

### 2.1 NH local 전국 raw

GitHub Actions:

- workflow: `Collect NH rates`
- run: `31956936041`
- result: `success`
- artifact: `nh-attempt-1-31956936041`
- artifact id: `9269227044`
- digest: `sha256:a64a31c2249029fabc515db2e1a255d0a255a74744fb6bab401d03cfc009abb4`
- source capture date: `2026-08-17`

공식 원천:

- `wmall.nonghyup.com/servlet/SFDPW0161R.view`
- `SFDPW0163R.view?brc=<code>` — 거치식
- `SFDPW0164R.view?brc=<code>` — 적립식

artifact에 전국 점포 `4,871`개의 거치식/적립식 상세 HTML이 각각 `4,871`개, 합계 `9,742`개 들어 있다.

### 2.2 KFCC 최신 raw

GitHub Actions:

- run: `31968096638`
- result: `success`
- artifact: `collection-run-31968096638`
- artifact id: `9271192722`
- digest: `sha256:d2e75382b0ddc9e2a6d3570929e43f0a4ade0685020acba23475c2b472e9db2d`
- source capture date: `2026-08-17`

공식 원천:

- `kfcc.co.kr/map/list.do`
- `kfcc.co.kr/map/goods_19.do`

17개 지역 명부 HTML과 각 `gmgoCd` 금리 HTML을 기준으로 감사했다.

### 2.3 재현 스크립트

`scripts/stage_g_mutual_max_rate_census.py`

```bash
python scripts/stage_g_mutual_max_rate_census.py \
  --nh-artifact nh-attempt-1-31956936041.zip \
  --kfcc-artifact collection-run-31968096638.zip \
  --output stage-g-census.json
```

스크립트는 production parser를 import하지 않고 captured official HTML을 직접 읽는다. 현재 parser가 같은 실수를 하고 있을 때 audit가 그 실수를 그대로 재사용하지 않도록 독립 구현했다.

---

## 3. NH local G2 전수 결과

### 3.1 e-joy 우대행 자체

원천 상품명:

`e-joy 인터넷예금 우대금리`

전국 raw 결과:

- 우대행: `19,472`행
- 우대행이 존재하는 `brc`: `4,868`
- 비고 고유 문구: **1종**
- 아래 문구와 정확히 일치: `19,472 / 19,472`

```text
- 대상예금 <거치식> 정기예탁금, 복리식 정기예탁금
<적립식> 정기적금, 자유적립 적금, 자유로 부금
- 상품별 금리 + 우대금리 적용
```

우대 기간 구간도 전수 동일하다.

| 원천 기간 구간 | 행 수 |
|---|---:|
| 1개월 이상 ~ 12개월 미만 | 4,868 |
| 12개월 이상 ~ 24개월 미만 | 4,868 |
| 24개월 이상 ~ 36개월 미만 | 4,868 |
| 36개월 이상 | 4,868 |

따라서 우대행의 `term_months` 하한값만 동일 비교하는 방식은 금지한다. 예를 들어 기본상품 3개월/6개월은 `1개월 이상~12개월 미만` 우대구간에 포함되고, 48개월/60개월은 `36개월 이상` 구간에 포함된다.

우대폭은 점포마다 다르다. `0%`, `0.05%`, `0.1%`, `0.2%`, `0.3%` 등 여러 값이 실제로 존재한다. 중앙값이나 대표 우대폭을 전국 점포에 일괄 적용할 수 없다.

### 3.2 deterministic target linkage

우대 문구의 대상상품을 현재 source product key에 다음 **고정 exact mapping**으로 연결한다.

| 우대 문구명 | source product key |
|---|---|
| 정기예탁금 | `정기예탁금` |
| 복리식 정기예탁금 | `복리식정기예탁금` |
| 정기적금 | `정기적금` |
| 자유적립 적금 | `자유적립적금` |
| 자유로 부금 | `자유로부금` |

`자유로부금`은 이번 전국 raw에 실제 상품행이 0건이다. 없는 상품을 생성하거나 이름이 비슷한 다른 상품에 붙이지 않는다.

링크 키는 다음을 모두 만족해야 한다.

```text
same brc
+ exact target source_product_key
+ target term ∈ e-joy raw interval
+ exact e-joy product name
+ exact supported e-joy applicability note
```

결과:

| 대상상품 | 현재 상품행 | linkable | unmatched | ambiguous |
|---|---:|---:|---:|---:|
| 정기예탁금 | 38,944 | 38,944 | 0 | 0 |
| 복리식 정기예탁금 | 19,472 | 19,472 | 0 | 0 |
| 정기적금 | 28,884 | 28,878 | 6 | 0 |
| 자유적립적금 | 24,070 | 24,065 | 5 | 0 |
| 합계 | **111,370** | **111,359** | **11** | **0** |

전체 현재 대상행 기준 deterministic linkage coverage는 `99.990123%`다.

12개월만 보면:

- target rows: `19,364`
- linkable: `19,362`
- coverage: `99.989672%`
- ambiguous: `0`

미연결 11행은 `brc=611088` 다압농협의 적립식 상품행이다. 이 점포는 적립식 화면은 존재하지만 거치식/e-joy 우대행이 없으므로 **max_rate를 NULL로 유지**한다.

`brc=100003`, `100004`는 상세표 자체가 비어 있고 대상상품행도 없으므로 target denominator에 들어가지 않는다.

### 3.3 G2 구현에 허용하는 계산

다음 계산만 허용한다.

```text
internet_max_rate = target_base_rate + source_declared_ejoy_add_rate
```

이 계산은 일반적인 `base_rate` fallback이 아니다. 같은 공식 원천이 명시적으로 `상품별 금리 + 우대금리 적용`이라고 밝힌 행의 실제 가산값을 같은 `brc`와 해당 기간구간에 연결하는 것이다.

우대폭이 `0%`인 경우도 source-declared 값이므로 결과가 base와 같을 수 있다. 이 경우에도 `max_rate = base_rate`로 fallback한 것이 아니라 `base + explicit 0`의 결과임을 trace에 남긴다.

---

## 4. NH G2 구현 계약

G2 구현 PR은 아래를 모두 지켜야 한다.

1. 일반 `join_channel=unknown` variant는 그대로 둔다.
2. e-joy가 결정론적으로 연결된 대상상품에만 **별도 `join_channel=internet` variant**를 생성한다.
3. internet variant의 `source_product_key`는 대상상품 key를 유지해 같은 stable Product에 붙인다.
4. 대상 기본행의 기간 하한이 e-joy 원문 기간구간에 포함될 때만 연결한다.
5. `max_rate = base + e-joy add_rate`는 exact product/note/interval 계약을 모두 통과한 경우에만 설정한다.
6. 연결 실패·누락·복수 후보는 `max_rate=NULL`로 fail closed 한다.
7. `base_source_locator`는 대상상품 행, `option_source_locator`는 e-joy 우대행을 가리킨다.
8. e-joy 원천 행 자체를 최고금리 완성상품으로 취급하지 않는다.
9. `자유로부금`을 합성 생성하지 않는다.
10. 과거 관측에 추정 backfill하지 않는다. 새 parser가 실제 raw를 읽은 시점부터 적용한다.
11. KFCC/NH strategy 활성화는 G2 구현·shadow·downstream audit 후 별도 단계로 한다.

필수 테스트:

- exact 대상상품 mapping
- 기간 interval 포함관계(3/6개월 → 1~12, 48/60개월 → 36+)
- 다른 `brc` cross-join 금지
- 대상상품 부재
- e-joy 부재
- note drift
- duplicate e-joy interval
- 0% explicit add-rate
- source locator / hash trace
- 원래 unknown-channel variant 보존
- idempotency

---

## 5. KFCC G1 전수 결과

최신 중앙 공식 명부:

- 지역 list 파일: `17`
- 점포행: `3,111`
- unique `gmgoCd`: `1,230`
- 각 점포행의 hidden field: `16`종

필드:

```text
addr, code1, code2, divCd, divNm, fax, gmgoCd, gmgoNm,
gmgoType, key, name, pageNo, r1, r2, sel, telephone
```

URL/domain/homepage로 사용할 수 있는 값:

- `http` / `www` / `.com` / `.kr` 형태 값: **0건**
- 공식 홈페이지 URL field: **없음**

중앙 수시공시 화면도 금고명·유형·주소·전화번호·게시일·첨부파일을 제공하지만 개별 금고 공식 홈페이지와 `gmgoCd`를 함께 제공하는 registry 계약은 확인되지 않았다.

따라서 개별 홈페이지 사례가 존재한다는 사실만으로 중앙 `gmgoCd`와 이름 유사도 매칭하지 않는다.

### G1 판정

**BLOCKED 유지**

다음 중 하나가 공식적으로 증명되기 전까지 collector 구현 금지:

- 중앙 공식 registry/API가 `gmgoCd + official homepage`를 함께 제공
- 개별 공식 홈페이지가 중앙 `gmgoCd`를 결정론적으로 노출하고 전국 열거 가능
- 또는 동등한 공식 stable key linkage가 전국 coverage와 함께 입증

---

## 6. 다음 실행 순서

1. 이 evidence gate를 merge한다.
2. 최신 main에서 **NH G2 구현 PR**을 별도 branch로 시작한다.
3. fixture/unit/full CI 후 최신 전국 raw 또는 production snapshot으로 shadow census한다.
4. downstream consumer에서 `max_rate`가 생기는 위치와 denominator/ranking 영향을 감사한다.
5. G2가 통과하면 그 다음 PR에서 strategy capability metadata/selector 활성화를 검토한다.
6. KFCC는 G1 linkage가 풀릴 때까지 기존 `max_rate=NULL`/ranking blocked를 유지한다.
7. Production Strategy Release Gate는 계속 OFF다.
