# Main / Strategy 역할 분리 + 보고서 출력 v1

- Date: 2026-08-20
- Repository: `dekt-oss/bank-rate-collector`
- Base: `main@35b454244df3d1322a67e50f48cbeb362e6dc556`
- Related: Issue #108
- Production Strategy Release Gate: **변경하지 않음**

## 1. 배경

검색 조회(`/`)와 전략 대시보드(`/strategy.html`)가 같은 데이터를 공유하면서 전국 지도, 시장 기준선, 경쟁사 정보가 화면마다 반복되고 있다.

두 화면의 역할을 다음처럼 고정한다.

```text
검색 조회 = 탐색 / 증거 / 상세 조회
전략 대시보드 = 금리결정 지원 / 시나리오 / 해석 / 의사결정 보고
```

Strategy의 최종 질문은 기존 pricing work order를 유지한다.

> 다음 기간에 필요한 순수신을 가장 낮은 조달비용으로 확보하려면 당사 예금금리를 얼마로 결정해야 하는가?

단 현재 `inflow_prediction_service` 계수는 내부 실적 미보정 stress assumption이다. 내부 calibration 전에는 실제 forecast, 목표 순수신 최적금리, 1bp 증분효과, FTP 반영 최소비용 금리를 확정값으로 표시하지 않는다.

## 2. 화면별 소유권

### 2.1 검색 조회가 소유

- 업권 / 상품유형 / 기간 / 지역 상세 필터
- 현재 조회 결과와 원시 비교표
- 대한민국 전국 지도와 부산 drill-down
- 지역 중앙값 / 지역 상세 evidence
- 수집상태 / 데이터 근거
- CSV / JSON 다운로드
- 조회조건 기반 보고서 출력

검색 조회는 "무엇이 어디에서 얼마인가"를 확인하는 evidence explorer다.

### 2.2 Strategy가 소유

- 선택 시장 universe와 기간
- 당사 현재금리 / 시장 기준선
- 현재/+5/+10/+15bp/제안금리 수신반응 stress scenario
- 추가 표면이자비용
- 시장 변화 / external funding context
- 우대조건 구조
- 금리결정용 축약 경쟁사 benchmark
- 의사결정 가능범위 / calibration boundary
- 금리결정 검토보고서 출력

Strategy는 "그래서 금리를 어떻게 판단할 것인가"를 지원한다.

## 3. 중복 정리 계약

### 3.1 전국 지도

- 전국 지도와 부산 drill-down의 단일 소유자는 검색 조회다.
- Strategy의 full interactive Korea map은 화면에서 제거한다.
- Strategy의 기존 지역 계산/데이터 계약 자체는 삭제하지 않는다. 다른 insight/향후 calibration 소비자가 사용할 수 있으므로 presentation에서만 비노출한다.
- Strategy에는 `지역 상세는 검색 조회에서 확인` 링크와 지역정보의 해석 한계를 짧게 남긴다.

### 3.2 Strategy 상단 KPI

기존 Strategy의 대형 4 KPI는 바로 아래 금리결정 영역의 market/own anchor와 중복된다.

- 대형 KPI strip은 presentation에서 비노출한다.
- 결정에 필요한 시장 최고/평균/상위10%/당사현재는 `금리 결정 · 수신반응 시나리오`의 planning context가 단일 visible source가 된다.
- 기존 DOM/계산은 삭제하지 않아 계산 계약을 흔들지 않는다.

### 3.3 경쟁사 TOP5

- 검색 조회: 전체 결과를 필터/정렬하여 상세 탐색
- Strategy: `가격결정 경쟁 기준 TOP5`만 축약 유지
- Strategy TOP5는 원시 탐색 표가 아니라 시장 상단 anchor의 보조 근거로 명시한다.

### 3.4 반복 허용 기준

숫자 자체의 반복을 전부 금지하지 않는다. 아래 조건을 만족하면 Strategy에서 반복할 수 있다.

- 제안금리 계산/해석에 직접 필요한 anchor
- 시장 변화/외부환경처럼 의사결정 context가 다른 경우
- provenance/caveat를 함께 제시하는 경우

원시 탐색 기능과 대형 시각화는 중복하지 않는다.

## 4. Strategy 결정 가능범위

Strategy 상단 또는 금리결정 영역에 상태 블록을 표시한다.

### 현재 판단 가능

- 당사 금리의 시장 위치
- 시장 최고/평균/상위10% 기준선
- 최근 시장 금리 방향
- 경쟁사 상단 benchmark
- 외부 자금환경
- 우대조건 구조
- 미보정 stress scenario에서 금리 변경 시 수신반응/표면이자비용 비교

### 내부자료 전에는 확정 불가

- 실제 신규수신 탄력성
- 실제 재예치 탄력성
- 순수신 forecast
- 1bp당 실제 증분유입 효율
- FTP 반영 조달비용
- 목표 순수신 달성 최소비용 최적금리

표시 문구는 `의사결정 지원`과 `최적금리 확정`을 구분한다.

## 5. 보고서 출력 v1

정적 사이트 구조를 유지하기 위해 서버 PDF 엔진을 추가하지 않는다.

각 화면에 `보고서 출력` 버튼을 제공하고 browser print dialog를 열어 사용자가 PDF로 저장할 수 있게 한다.

### 공통 계약

- 현재 화면의 선택상태를 캡처한 print-only report DOM 생성
- `window.print()` 사용
- print 종료 후 임시 report DOM 제거
- `@media print`에서 interactive UI/원시 화면은 숨기고 report만 표시
- 생성 시각 / 데이터 기준일 / 화면 역할 / caveat 포함
- 데이터/DB write 없음

### 5.1 검색 조회 보고서

`금리 조회·경쟁현황 보고서`

포함:
- 현재 조회조건
- 결과 건수 / 당사 비교 기준
- 주요 benchmark
- 현재 전국/부산 지역 요약
- 현재 화면 상위 결과 일부
- 데이터 기준일 / 수집상태 / caveat

CSV/JSON은 세부 데이터 전달용으로 계속 유지한다.

### 5.2 Strategy 보고서

`수신상품 금리결정 검토보고서`

포함:
- 선택 업권 / 기간
- 당사 현재금리와 시장 기준선
- 현재 제안금리
- 금리별 수신반응 비교표
- 시장 변화 / external context 요약
- 가격결정 경쟁 기준 TOP5
- 우대조건 핵심 요약
- 결정 가능범위 / calibration boundary

제외:
- 전국 지도
- raw 검색결과

필수 경고:

> 내부 수신실적 미보정. 수신반응은 stress scenario이며 최적금리 확정값이 아니다.

## 6. 구현 경계

변경하지 않는다.

- 금리 계산식 / 시장 집계식
- inflow prediction coefficient
- source precedence
- stable product identity
- NH e-joy linkage
- collector / DB / schema / migration
- R2 / rate-data write 계약
- Strategy Release Gate 설정

이번 단계는 information architecture + presentation + client-side report만 변경한다.

## 7. 검증 Gate

- Ruff / full pytest / empty DB migration
- Main map은 계속 존재하고 필터 반응 계약 유지
- Strategy visible full map 없음
- Strategy region-detail CTA 존재
- Strategy 대형 KPI strip 비노출, planning context는 유지
- Strategy TOP5가 가격결정 benchmark로 명확히 표시
- Main/Strategy 각각 report button 존재
- report snapshot 생성 후 필수 제목/선택상태/caveat 검증
- Strategy report에 full map 없음
- desktop 1280 / mobile 390 Chrome smoke
- horizontal overflow / pageerror / console error 없음
- production R2 read-only build 검증

## 8. 후속 E1/E2

내부자료 수령 후 기존 E0 intake gate를 그대로 따른다.

```text
source-specific mapping
→ intake Gate
→ internal/external feature alignment
→ time-based OOS validation
→ E1 calibrated inflow/rollover response
→ E2 목표 순수신 최소비용 최적금리
```

이 v1 UI 작업은 E1/E2를 선행 구현하거나 모방하지 않는다.
