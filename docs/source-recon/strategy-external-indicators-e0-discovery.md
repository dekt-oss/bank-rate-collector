# Stage E0 ECOS 외부지표 discovery evidence

- Date: 2026-08-18
- trusted main run: `32135388199`
- workflow: `Diagnostic — Strategy ECOS external indicators`
- artifact: `9323770229`
- artifact digest: `sha256:d53eb1033a3a16c4699e8f2c4a297fa8cfe62aee7d4c2af892e1920e642e6a4c`
- secret leak check: **PASS**
- production DB write: **없음**

## 1. 예금은행 신규취급 수신금리

실제 `StatisticTableList` / `StatisticItemList` 정찰 결과:

- `STAT_CODE = 121Y002`
- `STAT_NAME = 1.3.3.1.1. 예금은행 수신금리(신규취급액 기준)`
- monthly cycle available through `202606` at recon time

주요 월별 item:

| item | 이름 | 단위 |
|---|---|---|
| `BEABAA2` | 저축성수신 | 연% |
| `BEABAA21` | 순수저축성예금 | 연리% |
| `BEABAA211` | 정기예금 | 연리% |
| `BEABAA2118` | 정기예금(1년) | 연리% |
| `BEABAA22` | 시장형금융상품 | 연리% |
| `BEABAA224` | 금융채 | 연리% |
| `BEABAA1` | 저축성수신(금융채 제외) | 연리% |

### E0-2 판정 전 경계

`BEABAA2`를 이름만 보고 바로 Strategy 변수로 확정하지 않는다.

이번 Pricing Engine은 은행채/CD/COFIX를 v1 직접변수에서 제외하기로 했으므로
실제 예금상품 경쟁을 더 직접 반영하는 아래 계열을 실제 시계열로 함께 대조한다.

- `BEABAA2` 저축성수신
- `BEABAA1` 저축성수신(금융채 제외)
- `BEABAA21` 순수저축성예금
- `BEABAA2118` 정기예금(1년)

E0-2는 실제 `StatisticSearch` 결과·단위·최근 값·공식 보도 headline과의 일치성을
확인한 뒤 어떤 값을 모델의 기본 외부변수/보조변수로 둘지 결정한다.

## 2. 비은행금융기관 업권 수신잔액

실제 discovery 결과:

- `STAT_CODE = 111Y007`
- `STAT_NAME = 1.2.1.2.2. 비은행금융기관 수신(말잔)`
- cycle = `M`
- unit = `십억원`
- monthly series available through `202606` at recon time

필요 item:

| 내부 사용명 | ECOS item | ECOS 이름 | mapping |
|---|---|---|---|
| savings_bank_balance | `1120600` | 상호저축은행 | 저축은행 업권 외부 control |
| credit_union_balance | `1120700` | 신용협동조합 | 신협 업권 외부 control |
| mutual_finance_balance | `1120800` | 상호금융 | 광의 상호금융 external control |
| kfcc_balance | `1121000` | 새마을금고 | 새마을금고 업권 외부 control |

### 중요한 의미 경계

한국은행 통계 분류의 `상호금융`은 농협·수협·산림조합의 단위조합을 포함한다.
따라서 `1120800`을 현재 Strategy collector의 `nh_local`과 1:1 동일 업권으로
표시하지 않는다.

사용 계약:

```text
111Y007 / 1120800
= 광의 상호금융 시장의 월말 수신잔액/증감 control
!= nh_local 농·축협 collector의 직접 업권 잔액
```

Stage E에서 필요하면 `nh_local` 자체 경쟁금리/기관 움직임은 현재 collector에서,
광의 업권 자금흐름은 ECOS `상호금융`에서 서로 다른 feature로 사용한다.

## 3. 왜 말잔을 선택하는가

동일 계열에 `111Y008 비은행금융기관 수신(평잔)`도 존재한다.

이번 변수의 질문은 "업권 전체 수신이 전월 대비 얼마나 늘거나 줄었는가"이므로
stock 변화에 직접 대응하는 월말 잔액 `111Y007`을 기본 계약으로 선택한다.
평잔은 이번 v1의 기본 변수에 포함하지 않는다.

## 4. 다음 Gate — E0-2

증명된 exact code만 사용해 read-only `StatisticSearch`를 수행한다.

### bank series probe

`121Y002 / M`
- `BEABAA2`
- `BEABAA1`
- `BEABAA21`
- `BEABAA2118`

### nonbank balance probe

`111Y007 / M`
- `1120600`
- `1120700`
- `1120800`
- `1121000`

확인할 것:
- 실제 최근 월 데이터 존재
- 응답의 `STAT_CODE` / `ITEM_CODE1` 일치
- unit 일치
- 월 시점 파싱
- missing month 여부
- 최근 24~36개월 변동 방향/규모 sanity check
- ECOS 오류가 HTTP 200 body `RESULT`로 오는 경우 fail-closed

E0-2에서도 production DB에는 쓰지 않는다.
