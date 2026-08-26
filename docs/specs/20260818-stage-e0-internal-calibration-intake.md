# Stage E0 — Internal Calibration Intake Gate

- Date: 2026-08-18
- Repository: `dekt-oss/bank-rate-collector`
- Production Strategy Release Gate: **OFF**
- 목적: 내부자료가 도착했을 때 원본 양식을 강제하지 않고, 모델 calibration 전에 데이터 품질을 fail-closed로 판정한다.

## 1. 현재 상태

외부 feature foundation은 PR #145까지 완료됐다.

- 한국은행 기준금리
- 예금은행 신규취급액 수신금리
- 업권 월말 수신잔액/MoM context
- 시장 공시 예금금리/Strategy market intelligence

현재 `inflow_prediction_service`의 계수는 여전히 내부실적 미보정 구조적 stress assumption이다.

## 2. 이번 단계의 역할

내부 담당자에게 특정 Excel 양식이나 컬럼명을 강제하지 않는다.

```text
내부 원본 Excel/CSV
  → 자료 수령 후 source-specific mapping
  → canonical internal dataset
  → Internal Calibration Intake Gate
  → 통과한 자료만 후속 E1 calibration 후보
```

이번 PR은 첫 번째 화살표의 source-specific mapping을 만들지 않는다. 실제 파일을 보기 전에 열 이름/시트 구조를 추정하지 않기 위해서다.

## 3. 필수 canonical dataset

### pricing_flow
- 기준일
- 내부 상품 식별키
- 가입기간
- 실제 적용금리
- 신규 수신금액
- 신규 계좌수
- 잔액

### maturity_rollover
- 기준일
- 내부 상품 식별키
- 가입기간
- 만기도래 금액/계좌수
- 재예치 금액/계좌수

### early_withdrawal
- 기준일
- 내부 상품 식별키
- 가입기간
- 중도해지 금액/계좌수

### pricing_events
- 시행일
- 내부 상품 식별키
- 가입기간
- 변경 전/후 금리
- 특판 여부

광고/앱푸시/판매한도 등 추가 이벤트 정보는 원본에 존재하면 후속 mapping 시 보존한다.

### ftp
- 기준일/월
- 가입기간
- FTP 금리

## 4. 선택 dataset

### channel_segments
채널/고객구분 등 집계 세그먼트가 있을 때 사용한다.

### preference_performance
우대조건별:
- 대상 건수
- 달성 건수
- 달성 금액
- 우대 bp

를 받을 수 있으면 Stage D의 시장구조 분석과 연결해 실제 달성도/증분효과 검증에 사용한다.

## 5. 기간 Gate

- 최소: `pricing_flow`에서 서로 다른 달력 월 24개 이상 + 최소 24개 관측시점
- 권장: `pricing_flow`에서 서로 다른 달력 월 36개 이상 + 최소 36개 관측시점

첫 관측일과 마지막 관측일의 단순 일수 차(`history_days`)는 audit/reporting 값으로 유지하지만 readiness/grade Gate에는 사용하지 않는다. 월별 자료 24개를 정확히 받았을 때 23개월가량의 날짜 span 때문에 반려되는 off-by-one을 피하기 위해서다.

단순히 시작일과 종료일만 3년 떨어져 있는 자료는 3년 history로 인정하지 않는다. 서로 다른 관측 월 수와 관측시점 수를 함께 요구한다.

일별이 가장 좋지만 월별도 허용한다. v1 Gate는 연속 월 coverage까지 강제하지 않으며, 실제 파일 수령 후 빈 달/빈 기간/상품별 coverage를 더 세밀하게 감사한다.

## 6. 개인정보 Gate

직접 식별정보는 calibration 입력으로 받지 않는다.

금지 예:
- 고객명
- 계좌번호
- 주민등록번호
- 전화번호
- 이메일
- 자택주소

고객단위 분석이 꼭 필요한 경우에도 원본 식별자는 사용하지 않고, 별도 승인된 비식별/집계 계약을 먼저 만든다.

## 7. 현재 구현의 fail-closed 상태

다음이면 calibration을 허용하지 않는다.

- 필수 dataset 부재
- 필수 필드 누락
- 날짜 형식 오류
- 숫자 필드 비수치
- 음수 금액/계좌수
- 금리 범위 오류
- 직접식별 개인정보 필드 발견
- 서로 다른 관측 월 24개 또는 관측시점 24개 미달

결과에는 항상 다음을 포함한다.

- `calibration_allowed`
- `model_coefficients_changed = false`
- `database_written = false`

즉 이번 단계 자체는 예측모델을 보정하지 않고 DB도 변경하지 않는다.

## 8. 후속 E1

실제 내부자료가 들어오면:

1. source-specific mapping 작성
2. 이 Gate로 품질검사
3. 상품/기간/채널 기준 feature table 작성
4. 외부 feature bundle과 날짜 정렬
5. time-based train/test split
6. baseline 대비 out-of-sample 검증
7. 통과한 경우에만 `uncalibrated` 상태 해제 검토

우대조건 actual effect도 이 시점부터 별도 calibration 대상으로 올린다.

## 비범위

- 원본 Excel 양식 강제
- 내부자료 DB 적재
- 사용자/계좌 PII 수집
- 모델 coefficient 변경
- 실제 forecast 라벨 전환
- 최적금리 계산
- Production Strategy Release Gate ON
