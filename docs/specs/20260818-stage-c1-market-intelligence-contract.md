# Stage C1 — Market Intelligence 파생계약

```yaml
date: 2026-08-18
repository: dekt-oss/bank-rate-collector
base: main
related_issue: 108
production_strategy_release_gate: OFF
stage: C1
```

## 목적

Stage C 화면을 만들기 전에 시장이력 파생값의 universe와 fail-mode를 먼저 고정한다.

최종 질문은 다음이다.

> 최근 7일/30일 동안 각 업권·가입기간의 금리 경쟁이 실제로 어느 방향으로 얼마나 움직였는가?

이 파생값은 향후 두 곳에서 재사용한다.

1. Strategy Market Intelligence 시각화(C2)
2. Deposit Pricing Engine의 외부 시장 feature(E)

## Scope grid

- window: `7D`, `30D`
- term: `6M`, `12M`, `24M`, `36M`
- sector: `savings_bank`, `cu`, `kfcc`, `nh_local`
- product type: `term_deposit`
- stable identity: `products.id`

총 32개 scope cell을 생성하되 모든 cell이 반드시 숫자를 내는 것은 아니다.

## History Evidence Gate

요청 window와 충분히 가까운 실제 history가 없으면 변화량을 만들지 않는다.

- 최소 요구: 요청 window의 80% 이상
- 최대 허용: 요청 window의 125% 이하
- 범위를 벗어나면: `insufficient_history`
- 최신 snapshot 자체가 없으면: `no_history` / `no_data`
- 시작/종료 stable product가 겹치지 않으면: `insufficient_comparable_products`

즉 2일치 데이터로 `7D 변화`를 만들지 않고, 60일 전 baseline을 사용해 `30D 변화`라고 표시하지도 않는다.

각 scope는 실제 `start_snapshot_at`, `end_snapshot_at`, `observed_days`, `coverage_ratio`를 함께 보존한다. `history_gate`에는 `minimum_window_coverage_ratio=0.80`, `maximum_window_coverage_ratio=1.25`를 명시한다.

## Rate contract

### savings_bank / cu / kfcc

현재 C1에서는 각 historical snapshot의 visible observation 중 stable `product_id`별 대표 최고금리를 사용한다.

- rate field: `max_rate`
- product representative: 같은 stable product에서 최고 visible rate
- source precedence: `presentation.db_only_sources`

### nh_local

**C1 v1에서는 historical 변화량을 계산하지 않는다.**

현재 NH 전략 최고금리는 e-joy의 base/add 1:1 결합을 포함한 별도 `strategy_rate_basis` 계약이 있다. 과거 snapshot에 대해 이 결합을 재구성하지 않고 raw `max_rate`만 사용하면 현재 Strategy 지표와 다른 의미가 된다.

따라서 NH scope는 데이터가 있어도:

```text
status = unsupported_rate_contract
```

으로 닫는다.

C2 또는 후속 C1.1에서 historical NH base+add reconstruction evidence가 확보된 후에만 연다.

## Metrics

지원되는 scope에서 다음을 계산한다.

### 1. Rate Change Breadth

stable product 기준 시작/종료 snapshot을 비교한다.

```text
up_count
down_count
unchanged_count
up_share
down_share
breadth_score = (up_count - down_count) / comparable_product_count
```

`breadth_score` 범위는 -1 ~ +1이다.

### 2. Market Median Change

```text
median_change_bp = end_market_median - start_market_median
```

### 3. Upper-tier Momentum

상위 `ceil(10%)` 상품 중 최저 금리를 상위 10% 진입선으로 정의한다.

```text
upper_decile_change_bp
```

### 4. Comparable Mean Change

시작과 종료 모두 존재하는 stable product들의 금리변화 평균(bp).

### 5. Market Churn

시작/종료 상위 10% stable product set의 Jaccard distance.

```text
top_decile_entrants
top_decile_exits
top_decile_churn_rate
```

### 6. 당사 spread

`savings_bank` scope에서 고려저축은행 상품이 시작/종료 모두 존재하면:

```text
our_company.start_rate
our_company.end_rate
our_company.rate_change_bp
our_company.spread_vs_median_start_bp
our_company.spread_vs_median_end_bp
our_company.spread_change_bp
```

을 계산한다.

## Direction label

임의 점수 가중치를 만들지 않는다.

- median ↑ AND breadth > 0 → `rising`
- median ↓ AND breadth < 0 → `falling`
- 둘 다 0 → `flat`
- 그 외 → `mixed`
- evidence gate 미충족 → `insufficient`

## 비범위

C1에서는 하지 않는다.

- 화면 레이아웃 변경
- 외부 신규수집
- 업권 전체 수신 증감 수집
- BOK 신규취급액 저축성수신금리 추가
- NH historical base+add reconstruction
- 내부 고려저축은행 수신실적 사용
- Deposit Pricing calibration
- Strategy Release Gate ON

외부 거시지표 수집은 Stage C의 후속 데이터-source 작업 및 E0와 분리한다.
