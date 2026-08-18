# Stage E0-3 — ECOS 수신시장 거시지표 collector 계약

- Date: 2026-08-18
- Base: `main` (`21c6c9e842b8bd411297686d72a013ad596051f4`)
- Related: Issue #108
- Production Strategy Release Gate: **OFF 유지**

## 근거

trusted-main E0 정찰/실조회:

- discovery run `32135388199`, artifact `9323770229`
- exact series run `32136553896`, artifact `9324218955`
- 8개 검증 series 모두 2023-01~2026-06 42개월, source/item/unit warning 0건

## 목적

Stage E calibration에 사용할 월별 거시지표를 production DB의 기존
`market_indicators` 경로로 보존할 수 있게 한다.

기존 기준금리 `bok_ecos`는 안정화된 operational source이므로 **수정하지 않고**
새 source `bok_ecos_macro`로 실패영역을 분리한다.

## production 저장 대상

### 은행 신규취급액 수신금리

1. `121Y002 / BEABAA2` — 저축성수신
   - indicator: `bok_bank_savings_deposit_rate`
   - 사용: BOK headline/reference
2. `121Y002 / BEABAA21` — 순수저축성예금
   - indicator: `bok_bank_pure_savings_deposit_rate`
   - 사용: **Stage E v1 primary bank realized deposit-rate feature**
3. `121Y002 / BEABAA2118` — 정기예금(1년)
   - indicator: `bok_bank_term_deposit_1y_rate`
   - 사용: 12개월 보조 anchor

금융채/CD/COFIX는 E v1 직접변수에서 제외한다.

### 비은행 업권 월말 수신잔액

`111Y007 / M / 십억원`

- `1120600` 상호저축은행
- `1120700` 신용협동조합
- `1120800` 상호금융
- `1121000` 새마을금고

`1120800`은 농협·수협·산림조합 단위조합을 포함하는 **광의 상호금융**이며
현재 collector의 `nh_local`과 1:1 같은 업권으로 취급하지 않는다.

## 저장 단위 결정

현재 `market_indicators.value`는 `Rate` 타입이라:

- 음수 저장 불가
- 최대 `999.9999`

따라서 signed MoM 증감률을 직접 저장하지 않는다.

BOK 원천 월말잔액 `십억원`을 **조원(`trillion_krw`)**으로 나눠 positive level을
저장한다.

예:

```text
100355.8 십억원 → 100.3558 조원
519427.3 십억원 → 519.4273 조원
```

원천의 0.1 십억원 정밀도가 조원 소수점 4자리와 정확히 일치하므로 정보 손실이
없다. 값이 `999.9999 조원`을 넘으면 현재 schema contract를 넘는 것이므로
파서가 fail-closed하고 그 시점에 범용 numeric migration을 별도 검토한다.

업권 수신 **증감액/증감률은 저장된 두 월 level에서 조회 시 파생**한다.

## 월 시점 계약

ECOS 월 데이터는 `TIME=YYYYMM`만 주며 일자는 주지 않는다.

새 macro series는 모델에서 월 단위로 정렬하므로 `source_effective_at`을 해당
월의 **period-end date**로 표현한다. 원본 `YYYYMM`은 source locator에 그대로
보존한다.

예:

```text
TIME=202606 → source_effective_at=2026-06-30
locator=111Y007/1120600/202606
```

## 수집 범위

매 실행 시 최근 **48개월**을 다시 조회한다.

- 내부 calibration 권장 36개월보다 buffer가 있다.
- ECOS 잠정치가 과거 월을 수정하면 기존 `_upsert`가 같은 월을 갱신할 수 있다.
- 동일 값은 기존 indicator service가 `unchanged`로 처리한다.

## 실패영역

`bok_ecos_macro`는 기존 `bok_ecos` 기준금리와 별도 run/source다.

한 macro series라도 HTTP/schema/source-contract 오류가 나면 macro run을 실패시키고
해당 run의 DB 변경은 rollback한다. 기준금리 run에는 영향이 없다.

## 이 PR 범위

- macro parser
- isolated macro adapter
- 실제 E0 값 기반 parser/storage tests
- source/key/range/fail-closed tests

## 별도 wiring PR

parser/adapter/storage CI가 통과한 뒤에만:

- CLI/source registration
- `collect.yml`의 `참고지표만` / 일반 수집 연결

을 별도 최소 diff로 진행한다.

## 비범위

- DB/schema/migration 변경
- signed MoM 직접 저장
- Stage E model coefficient 변경
- Strategy UI 표시
- Release Gate ON
