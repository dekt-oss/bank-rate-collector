# Stage E0-6 — Strategy 외부 시장 자금환경 UI

## 목적

Stage E0-3~E0-5에서 이미 수집·검증한 외부 수신시장 feature를 Strategy 화면에서 금리결정의 **보조 환경 근거**로 표시한다.

새 지표 산식이나 예측계수를 만들지 않는다. 내부 실적 calibration 전까지 외부지표를 수신효과 또는 인과로 해석하지 않는다.

## 입력 계약

`build_deposit_pricing_external_features()`의 기존 read-only bundle만 사용한다.

- 한국은행 기준금리 (`bok_ecos / bok_base_rate`)
- 예금은행 순수저축성예금 신규취급액 금리
- 예금은행 1년 정기예금 신규취급액 금리
- 저축은행 / 신협 / 새마을금고 / 광의 상호금융 월말 수신잔액 MoM

## 표시

Strategy에서 `시장 자금환경` 카드로 표시한다.

1. 기준금리
2. 은행 순수저축성예금 신규취급 금리
3. 은행 1년 정기예금 신규취급 금리
4. 업권별 수신잔액 MoM과 최신 잔액

각 항목은 `source_effective_at` 또는 `data_month`를 함께 표시해 ECOS 공표시차를 숨기지 않는다.

## 의미 경계

- BOK `광의 상호금융`은 농협·수협·산림조합 단위조합을 포함하므로 `nh_local`과 1:1 동일하지 않다.
- 화면에는 `NH local 대리지표 · 농·축협과 1:1 동일하지 않음`을 명시한다.
- status가 ready가 아니면 값을 0으로 대체하지 않고 `—`와 원래 상태를 표시한다.
- 월별 거시 참고지표이며 당사 수신효과/인과 추정치가 아니다.
- 은행채 / CD / COFIX는 Stage E v1 직접변수에서 계속 제외한다.

## 화면 순서

`시장 자금환경 → 최근 시장 변화(C2) → 기존 시장/상품 인사이트 → 금리결정 시뮬레이터`

외부 macro 환경과 실제 공시 금리변화를 구분하되 금리결정자가 위에서 아래로 근거를 읽을 수 있게 한다.

## 비범위

- 내부자료 calibration
- inflow prediction coefficient 변경
- FTP 최적화
- 순수신 예측
- 최적금리 solver
- DB/schema/migration 변경
- 외부 source 추가
- Production Strategy Release Gate ON

## 완료 Gate

- Strategy summary payload에 `external_features` 포함
- presentation idempotency/fail-closed 테스트
- direct PII/내부자료와 무관
- 기존 9px 최소 absolute font 계약 통과
- full CI 통과
- production-backed isolated Strategy Preview에서 실제 macro payload 확인
- desktop/mobile Chrome smoke에서 runtime error / horizontal overflow 없음
