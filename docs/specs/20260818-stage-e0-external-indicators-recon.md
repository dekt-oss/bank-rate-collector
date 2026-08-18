# Stage E0 — 외부지표 ECOS Evidence Gate

- Date: 2026-08-18
- Base: `main` (`2b5c98be6f673626df915218a0cb164bf5202e29`)
- Related: Issue #108, `20260818-deposit-pricing-decision-cockpit-v3.md`
- Production Strategy Release Gate: **OFF 유지**

## 목표

Stage E의 수신예측/금리결정 보정에 사용할 외부시장 변수 중 아래 두 항목의
**실제 ECOS 통계표·항목·주기·단위 계약을 먼저 확인**한다.

1. 예금은행 신규취급액 기준 저축성수신금리
2. 업권 전체 수신 증감 계산의 원천이 되는 비은행금융기관 기관별 수신잔액

한국은행 기준금리는 이미 `bok_ecos` collector가 수집하므로 다시 만들지 않는다.
시중은행·저축은행·상호금융의 공시 예금금리도 기존 수집 데이터를 재사용한다.

은행채·CD·COFIX는 E v1 직접변수에서 제외한다.

## Evidence 원칙

저장소의 기존 ECOS 계약을 그대로 따른다.

- 통계표/항목 코드를 이름에서 추정해 collector에 하드코딩하지 않는다.
- 먼저 `StatisticTableList`와 `StatisticItemList`를 실제 API로 정찰한다.
- 인증키는 URL 경로에 포함되므로 결과·로그·artifact에서 반드시 마스킹한다.
- ECOS가 HTTP 200으로 오류를 줄 수 있으므로 body의 `RESULT`도 기록한다.
- 이번 단계에서는 production DB에 쓰지 않는다.
- 이번 단계에서는 Strategy 화면에 숫자를 표시하지 않는다.

## 왜 discovery와 collector를 분리하는가

기존 기준금리는 단일 item을 일별로 조회하는 단순 계약이다.
그러나 비은행금융기관 수신 통계는 기관별 분류 등 다차원 item tree일 수 있다.
실제 item hierarchy를 보지 않고 `StatisticSearch` 경로를 만들어 버리면 다른 계열을
정상 데이터처럼 저장할 위험이 있다.

따라서 E0-1은 **discovery-only**다.

```text
StatisticTableList
→ 이름 기반 후보 통계표
→ StatisticItemList 원본 + target keyword hit
→ artifact 보존
→ 사람/에이전트가 계약 확정
→ E0-2 collector 구현
```

## 정찰 target

### A. bank_deposit_rate

통계표 후보 키워드:
- 예금은행
- 여수신금리 / 금리

항목 후보 키워드:
- 저축성수신
- 수신금리
- 예금금리

### B. nonbank_deposit_balance

통계표 후보 키워드:
- 비은행금융기관
- 기관별 수신 / 수신

항목 후보 키워드:
- 상호저축은행 / 저축은행
- 신용협동조합 / 신협
- 새마을금고
- 상호금융
- 농협 / 수협 / 산림조합

키워드는 **후보를 찾기 위한 검색어**일 뿐 통계코드 계약이 아니다.

## E0-1 산출물

수동 diagnostic workflow가 아래 artifact를 만든다.

`strategy-external-indicators-recon.json`

포함 내용:
- 전체 통계표 목록 조회 메타데이터
- target별 후보 통계표
- 후보 통계표별 `StatisticItemList` 원본
- target keyword hit
- API 오류/응답 상태
- 인증키 마스킹 결과

## E0-2 진입조건

아래가 artifact로 확인된 target만 collector 단계로 넘어간다.

- exact `STAT_CODE`
- exact item hierarchy / item code 조합
- cycle
- unit
- 실제 시계열 샘플
- 최근 값/기준월의 의미
- 수신잔액의 말잔/평잔 의미
- 업권 매핑 가능 여부

확인되지 않은 target은 `blocked_by_source_contract`로 남긴다.

## 비범위

- DB/schema/migration 변경
- `market_indicators` 신규 행 저장
- scheduled collector 변경
- Strategy UI 변경
- 내부 실적 calibration
- 은행채/CD/COFIX 도입
- Production Strategy Release Gate ON
