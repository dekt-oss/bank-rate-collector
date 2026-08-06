# 금리 모니터링 — 우대조건 표준화·분류 작업명세서

```yaml
document_type: implementation_spec
status: accepted_not_started
date: 2026-08-06
target_repository: dekt-oss/bank-rate-collector
depends_on: docs/specs/20260806-rate-monitor-v4.md
```

> **저장소 반영 검토** (2026-08-06)
>
> 착수 전에 실제 DB(rate-data `60e90e7`, 관측 145,058건)에 비춰 봤다. 명세서를
> 그대로 따르면 막히는 곳이 셋 있다. **구현 전에 이 셋을 정해야 한다.**
>
> ### 1. `preferential_spread`를 71.6%에서 계산할 수 없다
>
> §8이 `preferential_spread = max_rate - base_rate`를 기본 검증식으로 둔다.
> 그런데 원천별 `max_rate` 보유 현황이 이렇다.
>
> | 원천 | 관측 | `max_rate` 있음 |
> |---|---:|---:|
> | kfcc | 103,844 | **0** |
> | cu | 30,980 | 30,980 |
> | finlife | 6,463 | 6,463 |
> | fsb | 3,771 | 3,765 |
>
> 새마을금고는 **공식 화면에 최고우대금리 열 자체가 없다.** 전체 관측의
> 71.6%다. 여기서 `max_rate`를 `base_rate`로 메우면 v4 §3.3과
> P1-A 게이트를 동시에 어긴다 — 게이트가 "새마을금고 관측 중 채워진 값 0건"을
> 매 실행 검사하고 있다.
>
> **그래서 `preferential_spread`는 계산할 수 없을 때 NULL이어야 하고,
> 화면은 "원천 미제공"으로 표시해야 한다.** 0으로 두면 우대금리가 없는
> 상품처럼 보인다.
>
> ### 2. 우대조건 원문이 24.8%에만 있다
>
> 145,058건 중 35,950건이다. 나머지는 원천이 아예 안 준다. 이것도
> "우대조건 없음"이 아니라 "원천 미제공"이다 (§3 주의사항과 같은 취지).
>
> 다만 **원문이 이미 구조를 갖고 있어** 자동 분류 전망은 밝다. 실측 형태:
>
> ```
> 모바일 가입 : 연 0.10%
> (고시금리 포함)
>
> 최고우대금리 : 0.4%
> - 당행 정기예금 첫거래 고객 우대 : 0.3%
> - 개인(신용)정보 마케팅(SMS)동의 유지 : 0.1%
> ```
>
> `조건명 : 금리` 패턴이라 §7의 "조건 단위 분리"와 "금리 추출"이 규칙만으로
> 상당 부분 된다. `(고시금리 포함/미포함)`은 §7의 "의미 보존이 필요한 표현"
> 목록에 없는데, **이 표시가 `max_rate`에 이미 반영됐는지를 가른다.** 목록에
> 넣어야 한다.
>
> `해당사항없음`도 실제로 있다. 이건 원천이 명시적으로 없다고 말한 것이므로
> "미제공"과 구별해 저장해야 한다 — 셋을 가르는 값이 필요하다.
>
> ```
> 원천 미제공     원문 자체가 없다
> 명시적 없음     원문이 "해당사항없음"이라고 말한다
> 있음            조건이 적혀 있다
> ```
>
> ### 3. 관리자 화면(§10)이 이 저장소에 없다
>
> 이 저장소는 GitHub Actions 배치 수집기와 **정적 사이트**다. 로그인도 서버도
> 없다. §10의 검수 목록·상세 검수·관리자 수정값 보호는 새 런타임을 들이는
> 일이고, 그것은 이 명세서보다 큰 결정이다.
>
> 대안 둘을 먼저 정해야 한다.
>
> ```
> (a) 검수를 데이터로 한다
>     review_items에 쌓고, 사람이 config/preference_overrides.yaml을 고쳐
>     커밋한다. manual_overrides 테이블이 이미 그 자리에 있다.
>     — 새 런타임 없음. PR이 곧 감사 기록.
>
> (b) 관리자 웹앱을 만든다
>     §10을 그대로 구현한다. 서버·인증·DB 쓰기 경로가 새로 필요하다.
> ```
>
> 지금 구조에서는 (a)가 맞다고 본다. 사용자가 정할 일이다.
>
> ### 이미 있는 것 — 새로 만들지 않는다
>
> | 명세서 | 저장소 현황 |
> |---|---|
> | `preferential_conditions_raw` | `rate_observations.raw_preference_text` (35,950건) |
> | 조건별 구조화 테이블 | `preference_conditions` 테이블 (스키마만, **0행**) |
> | 관리자 수정값 보호 | `manual_overrides` 테이블 (스키마만, 0행) |
> | `parse_status` | `preference_conditions.parse_status` (기본 `raw_only`) |
> | 검수 대상 | `review_items` (1,028행 운영 중) |
>
> `preference_conditions`의 현재 칸은 7개(`condition_type`·`description`·
> `add_rate`·`mandatory`·`stackable`·`parser_confidence`·`parse_status`)이고
> §6은 25개를 요구한다. 마이그레이션으로 넓히면 되고, 새 테이블을 만들 이유는
> 없다.
>
> ### 순서 제안
>
> v4 PR 7(통합 비교 UI)이 §11의 화면을 이미 다룬다. 우대조건 표시는 그
> 화면 위에 얹히므로 **PR 7 뒤**가 맞다. 그 전에 §5의 표준코드와 §6의 칸만
> 먼저 넣어 두면, 수집이 도는 동안 원문이 쌓이고 분류는 나중에 소급할 수 있다.


## 1. 작업 목적

금리 모니터링 시스템에서 금융기관별 우대조건을 원문 그대로만 저장하지 않고, 공통 기준으로 분류·관리·표출할 수 있도록 기능을 추가한다.

핵심 원칙은 다음과 같다.

- 우대조건 원문은 항상 보존한다.
- 반복되는 조건은 표준 코드로 분류한다.
- 금리, 금액, 기간, 횟수 등 확인 가능한 값만 구조화한다.
- 가입조건과 우대금리 조건을 구분한다.
- 분류가 어려운 특이 조건만 `OTHER`로 관리한다.
- 불명확한 내용은 자동 확정하지 않고 관리자 검수 대상으로 보낸다.
- 기존 금리 수집·조회 기능의 하위 호환성을 유지한다.

---

## 2. 구현 범위

### 필수 구현

1. 기본금리, 최고 적용금리, 우대금리 총폭 분리 저장
2. 우대조건 원문 저장
3. 표준 대분류 및 세부 코드 매핑
4. 가입조건·우대조건·제한조건 역할 구분
5. 조건별 우대금리, 금액, 횟수, 기간 저장
6. `AND`, `OR`, `택1`, `최대 N개` 등 복합조건 표현
7. 자동 분류 실패 시 `OTHER` 또는 `MANUAL_REVIEW` 처리
8. 관리자 검수·수정 기능
9. 사용자 화면에서 기본금리·우대금리·최고금리 분리 표출
10. 기존 API·CSV에 신규 필드 추가

### 이번 단계 제외

- 모든 조건의 100% 자동 해석
- 사용자 계좌정보 연동
- 개인별 실제 적용금리 자동 계산
- 이미지·PDF OCR
- LLM만으로 자유문장을 확정 분류하는 방식

---

## 3. 데이터 수집 기준

상품별 금리 데이터는 아래 항목으로 구분한다.

```text
base_rate                   기본금리
max_rate                    최고 적용금리
preferential_spread         우대금리 총폭 = max_rate - base_rate
preferential_conditions_raw 우대조건 원문
rate_source_url             출처 URL
effective_date              금리 기준일
collected_at                수집 시각
```

주의사항:

- 원본의 `최고금리`는 우대폭이 아니라 최종 적용금리일 수 있으므로 별도 저장한다.
- 기본금리와 최고금리가 같아도 공식 원문 확인 없이 자동으로 `우대조건 없음` 처리하지 않는다.
- 확인되지 않은 조건별 우대율이나 결합관계는 추정하지 않는다.
- 원본값과 관리자 수정값은 분리한다.

---

## 4. 조건 역할 분류

각 조건은 다음 역할 중 하나로 분류한다.

| 코드 | 의미 |
|---|---|
| `PREFERENTIAL` | 충족 시 우대금리가 추가되는 조건 |
| `ELIGIBILITY` | 상품 가입 가능 여부를 결정하는 조건 |
| `REQUIREMENT` | 상품 또는 우대금리 유지에 필요한 조건 |
| `LIMITATION` | 최대한도, 중복 불가, 택1 등 제한조건 |
| `INFORMATION` | 금리 계산과 직접 관련 없는 안내 |
| `UNKNOWN` | 역할 판별 불가 |

예시:

```text
부산광역시 거주자만 가입 가능
→ ELIGIBILITY

부산광역시 거주자에게 +0.2%p
→ PREFERENTIAL
```

---

## 5. 표준 우대조건 분류

### 대분류

| 코드 | 화면 표시명 | 주요 조건 |
|---|---|---|
| `NEW_CUSTOMER` | 신규·첫 거래 | 신규고객, 첫 거래, 예금 미보유 |
| `INCOME_TRANSFER` | 급여·연금 수령 | 급여, 연금, 정기소득 입금 |
| `AUTO_PAYMENT` | 자동이체·자동납부 | 적금 자동이체, 공과금 자동납부 |
| `CARD_USAGE` | 카드 이용 | 체크카드·신용카드 사용실적 |
| `DIGITAL_CHANNEL` | 비대면·가입채널 | 앱, 인터넷, 모바일, 창구 |
| `PRODUCT_HOLDING` | 계좌·상품 보유 | 입출금계좌, 예금, 대출 등 |
| `MEMBERSHIP` | 회원·조합원 | 조합원, 출자회원, 우수고객 |
| `PAYMENT_PERFORMANCE` | 납입 실적 | 납입횟수, 납입금액, 미납 여부 |
| `CONTRACT_CONDITION` | 가입금액·기간 | 최소금액, 특정 가입기간 |
| `MAINTENANCE` | 만기·유지 | 만기 유지, 재예치, 중도해지 없음 |
| `AGE_LIFE_STAGE` | 연령·생애 조건 | 청년, 아동, 고령자, 결혼, 출산 |
| `REGION_AFFILIATION` | 지역·소속 | 지역주민, 직장, 학교, 단체 |
| `CONSENT_SERVICE` | 동의·전자서비스 | 마케팅, 알림, 오픈뱅킹 |
| `EVENT_REFERRAL` | 이벤트·추천 | 추천인, 쿠폰, 프로모션 |
| `OTHER` | 기타 | 기존 분류에 포함되지 않는 조건 |

### 세부 코드 예시

```text
FIRST_TRANSACTION
SALARY_TRANSFER
PENSION_TRANSFER
DEPOSIT_AUTO_TRANSFER
UTILITY_AUTO_PAYMENT
CHECK_CARD_USAGE
CREDIT_CARD_USAGE
MOBILE_JOIN
INTERNET_JOIN
NON_FACE_TO_FACE_JOIN
DEMAND_DEPOSIT_HOLDING
COOPERATIVE_MEMBER
PAYMENT_COUNT
PAYMENT_AMOUNT
MINIMUM_JOIN_AMOUNT
MATURITY_MAINTENANCE
RENEWAL
AGE_RANGE
YOUTH
LOCAL_RESIDENT
COMPANY_EMPLOYEE
MARKETING_CONSENT
OPEN_BANKING_REGISTRATION
REFERRAL
PROMOTION
OTHER
UNCLASSIFIED
```

금융기관 문구가 다르더라도 의미가 같으면 동일 코드로 매핑한다.

예:

```text
급여이체 고객
급여 수령 실적
월급 통장 이용
→ SALARY_TRANSFER
```

---

## 6. 우대조건 데이터 모델

조건별 구조화 데이터는 별도 테이블 또는 JSON 배열로 관리한다.

권장 필드:

```text
id
product_rate_id
condition_role
category_code
condition_code
condition_name
condition_description
source_text
bonus_rate
threshold_min
threshold_max
threshold_unit
measurement_period
required_duration
required_duration_unit
combination_group
combination_operator
is_stackable
max_application_count
display_order
parse_status
admin_review_required
created_at
updated_at
```

### 주요 값

```text
combination_operator:
SINGLE
AND
OR
SELECT_ONE
LIMITED_SUM
UNKNOWN
```

```text
parse_status:
EXACT
PARTIAL
RAW_ONLY
MANUAL_REVIEW
ADMIN_CONFIRMED
```

조건별 우대율이 아니라 복합조건 전체에 하나의 우대율이 적용되는 경우, 각 조건에 금리를 중복 저장하지 말고 그룹 단위 금리로 저장한다.

---

## 7. 처리 흐름

```text
원본 수집
→ 기본금리·최고금리 저장
→ 우대금리 총폭 계산
→ 우대조건 원문 저장
→ 문장 및 조건 단위 분리
→ 조건 역할 판별
→ 표준 대분류·세부코드 매핑
→ 금리·금액·횟수·기간 추출
→ AND·OR·최대한도 관계 추출
→ 금리 검증
→ 정상 저장 또는 관리자 검수
```

의미 보존이 필요한 표현:

```text
모두 충족
각각
중 하나
택1
최대
합산
중복 가능
중복 불가
선착순
매월
연속
만기 시
가입 시
```

판단이 불가능한 경우:

- 상위 대분류만 지정
- 세부코드는 `UNCLASSIFIED`
- 원문은 보존
- `MANUAL_REVIEW` 처리

---

## 8. 금리 검증

기본 검증식:

```text
preferential_spread = max_rate - base_rate
```

구조화된 조건의 최대 우대금리 합계가 계산 가능한 경우:

```text
calculated_max_bonus ≈ preferential_spread
```

다음은 자동 검수 대상으로 처리한다.

- 기본금리가 최고금리보다 높음
- 최고금리가 더 높은데 우대조건 원문이 없음
- 조건별 우대금리와 총 우대폭 불일치
- AND·OR 관계 불명확
- 조건별 금리와 그룹 전체 금리 구분 불가
- 중복 적용 또는 최대한도 불명확
- 가입조건과 우대조건 구분 불명확
- 원문과 구조화 결과 충돌

---

## 9. 기타 조건 관리

기존 코드로 분류할 수 없는 조건은 다음과 같이 저장한다.

```text
category_code = OTHER
condition_code = OTHER
source_text = 원문
admin_review_required = true
other_reason = 분류 실패 이유
```

`OTHER`는 영구 분류가 아니라 신규 표준코드 후보로 관리한다.

다음 조건을 만족하면 신규 코드 승격을 검토한다.

- 유사 조건이 여러 금융기관에서 반복
- 사용자 검색·필터 가치가 있음
- 명확한 판별 기준을 만들 수 있음
- 기존 코드로 분류하기 어려움

---

## 10. 관리자 화면

### 검수 목록

표시 항목:

- 금융기관
- 상품명
- 가입기간
- 기본금리
- 최고금리
- 우대금리 총폭
- 추출 조건 수
- 대표 분류
- 분석 상태
- 검수 필요 여부
- 기준일
- 최종 검수일

필터:

- 대분류
- 세부코드
- 분석 상태
- `OTHER`
- 금리 불일치
- 금융기관
- 지역
- 상품 유형

### 상세 검수

한 화면에서 다음을 확인·수정할 수 있어야 한다.

1. 원본 우대조건
2. 구조화된 조건
3. 기본금리·최고금리·우대폭
4. 조건별 가산금리
5. 금액·횟수·기간 기준
6. AND·OR 관계
7. 검증 결과
8. 관리자 수정값

관리자 수정값은 재수집으로 덮어쓰지 않는다. 원본 변경 시 `원본 변경 감지` 상태를 표시한다.

---

## 11. 사용자 화면

### 목록 화면

```text
기본금리 3.00%
우대금리 최대 +0.50%p
최고금리 3.50%

[첫 거래] [급여이체] [앱 가입]
```

### 상세 화면

조건별 금리가 확인된 경우:

```text
우대금리 최대 +0.50%p

- 첫 거래 고객: +0.20%p
- 월 50만원 이상 급여이체: +0.20%p
- 모바일 앱 가입: +0.10%p
```

조건별 금리를 알 수 없는 경우:

```text
우대금리 최대 +0.50%p

주요 조건
- 급여이체
- 카드 이용
- 마케팅 동의

조건별 적용 금리는 금융기관 안내 확인 필요
```

가입자격은 우대조건과 별도 영역에 표시한다.

---

## 12. API·CSV

기존 응답을 유지하면서 다음 필드를 추가한다.

```text
preferential_spread
preferential_condition_status
preferential_categories
preferential_conditions
preferential_conditions_raw
```

CSV 신규 컬럼:

```text
preferential_spread
preferential_condition_status
preferential_category_codes
preferential_condition_codes
preferential_condition_tags
preferential_conditions_raw
preferential_conditions_json
```

기존 CSV 호환성을 위해 신규 컬럼은 뒤쪽에 추가한다.

---

## 13. 테스트

### 필수 테스트

1. 같은 의미의 다른 문구가 동일 코드로 분류되는지
2. 가입조건과 우대조건이 구분되는지
3. AND·OR·LIMITED_SUM이 정확히 저장되는지
4. 기본금리·최고금리·우대폭 계산이 맞는지
5. 우대조건 합계 불일치 시 검수대상 처리되는지
6. `OTHER` 조건을 관리자 화면에서 재분류할 수 있는지
7. 관리자 수정값이 재수집으로 덮어써지지 않는지
8. 기존 금리 수집·조회·CSV 기능이 정상 작동하는지

---

## 14. 완료 기준

다음 조건을 만족하면 작업 완료로 본다.

- 우대조건 원문과 구조화 결과가 분리 저장된다.
- 표준 대분류와 세부코드로 관리된다.
- 가입조건과 우대조건이 구분된다.
- 조건별 금리·금액·기간·횟수를 저장할 수 있다.
- 복합조건 관계를 표현할 수 있다.
- 규격 외 조건은 `OTHER`로 관리된다.
- 불명확한 조건은 관리자 검수 대상으로 분리된다.
- 관리자 수정값이 재수집으로 보호된다.
- 사용자 화면에 기본금리·우대금리·최고금리가 구분된다.
- 기존 API와 화면의 하위 호환성이 유지된다.
- 관련 테스트가 추가되고 통과한다.

---

## 15. 작업 완료 후 보고

클로드코드는 작업 후 아래 내용을 보고한다.

1. 변경 파일
2. DB 마이그레이션
3. 최종 표준코드 목록
4. 자동 분류 규칙
5. 관리자 화면 변경
6. 사용자 화면 변경
7. API·CSV 변경
8. 테스트 결과
9. 자동 분류가 어려운 사례
10. 다음 개발 권장사항 3개
