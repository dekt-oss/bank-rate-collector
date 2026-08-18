# Stage E0-4 — Strategy 외부 거시지표 read model

- Date: 2026-08-18
- Base: `main` (`efb7cc6f0013a073fb33db2cd6940e7f6786282c`)
- Related: Issue #108
- Production Strategy Release Gate: **OFF 유지**

## 목적

E0-3에서 저장하도록 연결한 한국은행 월별 level을 Stage E calibration이 바로 쓸 수
있는 **read-only context**로 변환한다.

DB에는 원천 level만 저장하고, signed MoM 변화는 read model에서 파생한다.

## 은행 수신금리 feature

- primary: `bok_bank_pure_savings_deposit_rate` — 순수저축성예금 신규취급액 금리
- headline/reference: `bok_bank_savings_deposit_rate` — 저축성수신
- 12M anchor: `bok_bank_term_deposit_1y_rate` — 1년 정기예금

모든 값은 `bok_ecos_macro` source의 valid row만 사용한다.

## 업권 수신잔액 feature

- savings bank
- credit union
- broad mutual finance
- KFCC

각 series에서 최신 2개 월말 level을 읽고 다음을 파생한다.

```text
MoM 증감액 = latest balance - previous balance
MoM 증감률 = MoM 증감액 / previous balance × 100
```

## 핵심 fail-closed 계약

### 연속월만 MoM

최신과 직전 row가 **달력상 연속된 월말**일 때만 MoM을 계산한다.

예:

```text
2026-05-31 → 2026-06-30 : ready
2026-04-30 → 2026-06-30 : non_consecutive_months, MoM=null
```

누락된 한 달을 건너뛴 변화를 전월 대비라고 표시하지 않는다.

### broad mutual finance

BOK `상호금융`은 `nh_local`과 1:1 동일 업권이 아니다.

```text
mapping_role = broad_market_control_not_nh_local_1to1
```

을 payload에 명시한다.

### stale/month transparency

월별 ECOS 지표는 공개 시차가 있으므로 현재 날짜와 혼동하지 않는다.
모든 feature에 `source_effective_at`과 `data_month`를 포함한다.

### missing != zero

- table 없음 → `schema_unavailable`
- 전혀 없음 → `no_data`
- balance 1개월뿐 → `insufficient_history`
- source/unit/date 계약 불일치 → `source_contract_mismatch`

어느 경우에도 0으로 대체하지 않는다.

## 실제 E0-2 값 기반 회귀

2026-05 → 2026-06:

| 업권 | 5월 조원 | 6월 조원 | MoM 조원 | MoM % |
|---|---:|---:|---:|---:|
| 저축은행 | 100.4487 | 100.3558 | -0.0929 | -0.0925% |
| 신협 | 141.2654 | 140.3664 | -0.8990 | -0.6364% |
| 광의 상호금융 | 522.1082 | 519.4273 | -2.6809 | -0.5135% |
| 새마을금고 | 243.7910 | 243.2478 | -0.5432 | -0.2228% |

은행 2026-06:
- 순수저축성예금 3.02%
- 저축성수신 3.08%
- 1년 정기예금 3.26%

## 이번 PR 범위

- `strategy_external_context_service.py`
- actual E0 values 기반 synthetic DB tests
- fail-closed / consecutive-month / semantic-boundary tests

## 다음 단계

서비스 계약 CI 통과 후 Strategy summary payload에 `external_context`로 연결한다.
화면 표시보다 먼저 Stage E feature input 계약을 고정한다.

## 비범위

- prediction 계수 calibration
- 내부실적 적재
- Strategy UI 표시
- DB migration
- Release Gate ON
