# 금리수집기 대시보드 고도화 작업명세서 v2
## Fable Review 반영판 — Main Map + Strategy Decision Cockpit

```yaml
document_type: work_order
status: review_resolved
date: 2026-08-18
repository: dekt-oss/bank-rate-collector
base_branch: main
review_basis: Fable static-code review
related_issue: 108
production_strategy_release_gate: OFF
merge_policy: explicit_user_approval
```

---

# 0. 결론

Fable 리뷰 결과를 반영하여 다음과 같이 작업 범위를 확정한다.

## Stage A — Main Map
메인 대시보드의 기존 사각형 지역 금리 분포를 **대한민국 지도형 카드**로 교체한다.

단, 현재 `korea-sido.svg`의 배포가 Strategy Release Gate와 결합되어 있으므로
메인 공개 화면이 해당 gated asset에 런타임 의존하지 않도록 한다.

**결정: Stage A에서는 기존 SVG geometry를 메인 템플릿의 presentation layer에 인라인 재사용한다.**

따라서:

- Strategy Release Gate의 asset 발행/삭제 계약을 변경하지 않는다.
- `site_service.py`의 Strategy gate 동작을 이번 작업에서 수정하지 않는다.
- 메인 지도는 Gate OFF에서도 독립적으로 정상 렌더링된다.

또한 지도 수치는 기존 메인 `regionRows()` / `regionBasis()` 계산을 그대로 authoritative source로 사용한다.

---

## Stage B — Strategy Decision Cockpit Core
Strategy는 아래 세 질문을 우선 답하도록 고도화한다.

> 1. 현재 확인 가능한 시장 변화는 무엇인가?  
> 2. 우리 회사는 시장에서 어디에 있는가?  
> 3. 목표 순위까지 몇 bp가 필요한가?

단, 현재 historical derived contract의 범위를 넘는
`7일 · 전 기간 · 전 업권 변화`는 Stage B에서 구현하지 않는다.

Stage B의 시장 변화 브리핑은 **현재 계약이 지원하는 저축은행 · 12개월 · 30일 범위**로 제한한다.

나머지 historical 확장은 Stage C에서 파생 계약을 명시적으로 확장한 뒤 구현한다.

---

# 1. 이번 리뷰에서 해결한 P0 / P1

## P0-1. Main Map의 Strategy Gate asset 결합

### 문제
현재 `web/assets/korea-sido.svg`는 Strategy Release Gate ON에서만 발행되고,
Gate OFF에서는 stale asset 우회를 방지하기 위해 삭제된다.

메인 대시보드가 이 배포 asset을 직접 참조하면
Production Strategy Gate OFF 상태에서 메인 지도가 깨질 수 있다.

### 결정
**Stage A에서 메인 지도는 외부 gated asset을 참조하지 않는다.**

구현 원칙:

```text
기존 korea-sido.svg geometry
        ↓
site.html 내부 presentation SVG로 재사용
        ↓
메인 페이지에서 독립 렌더링
```

금지:

- Strategy Gate를 메인 지도 때문에 ON으로 변경
- stale asset 예외 허용
- 기존 gate cleanup 로직 완화
- 메인 지도만을 위해 Strategy Release 정책 변경

장기적으로 공용 geography asset 계약을 별도 도입할 수 있으나,
이번 Stage A 범위에는 포함하지 않는다.

---

## P0-2. Strategy 시장 변화 브리핑 범위

### 문제
현재 변화 파생은 `rate_observations`를 기반으로 하지만
현 계약은 사실상 다음 범위다.

```text
sector = savings_bank
term = 12M
window = 30/63일 기반
```

따라서 아래 요구는 Stage B 현 계약으로 지원되지 않는다.

- 7일 전용 브리핑
- 6/12/24/36개월별 변화
- 4업권 historical change
- 전 업권 TOP5/TOP10 churn

### 결정
Stage B 브리핑을 다음으로 축소한다.

**Stage B 지원 범위**

```text
저축은행
12개월
최근 30일
```

표시 가능 항목:

- 30일 금리 인상 이벤트 수
- 30일 금리 인하 이벤트 수
- 12개월 현재 시장 상단/평균
- 당사 현재 포지션과 현재 경쟁군 거리
- 기존 derived payload가 직접 지원하는 변화 요약

Stage B에서 표시하지 않는 항목:

- 7일 변화
- 6/24/36개월 historical change
- 상호금융 historical change
- 전 업권 change ranking
- TOP5 신규 진입/이탈 추적
- TOP10 churn

위 항목은 Stage C로 이동한다.

---

## P1-1. `TOP10` 의미 충돌

### 문제
현재 Strategy KPI의 `top10`은 실제 10위가 아니라
`topCutoff(a, .1)` 기반 **상위 10% cutoff**이다.

신규 Position Matrix와 목표순위 계산은 **실제 순위**를 의미한다.

같은 `TOP10` 라벨을 쓰면 잘못된 의사결정을 유발한다.

### 결정
두 개념의 라벨을 완전히 분리한다.

기존 percentile KPI:

```text
기존: TOP10 진입선
변경: 상위 10% 진입선
```

신규 ordinal rank:

```text
TOP 10위 진입선
TOP 5위 진입선
현재 11위 / 321개
```

코드 내부 변수명도 가능한 범위에서 의미를 구분한다.

예:

```text
top_decile_cutoff
rank_10_threshold
rank_5_threshold
```

---

## P1-2. 지도 granularity와 기존 median

### 문제
현재 메인 지역 분포는:

- 9개 권역
- 부산 구·군
- median 기준

이고 SVG geometry는 17개 시도이다.

기존 명세의 `전환 전후 수치 동일`과
`대표 최고금리 + 시장 평균` 신규 표시가 충돌한다.

### 결정
**Stage A는 계산 로직을 바꾸지 않는다.**

Authoritative metric:

```text
기존 regionRows()가 계산한 median
```

따라서 메인 지도 1차 버전의 주 지표는:

- 지역 median 금리
- 비교 데이터 수
- 기존 지역 label / basis

이다.

Stage A에서 새로 계산하지 않는 값:

- 지역 최고금리
- 지역 평균
- 신규 지역 ranking

### 17개 SVG와 9개 권역 매핑

17개 path를 새로운 17개 독립 통계 단위로 해석하지 않는다.

원칙:

```text
기존 9개 region bucket
→ 해당 bucket에 속하는 SVG 시도 path에 동일 값 표현
```

즉 같은 기존 권역에 속하는 복수 시도는
동일한 기존 median을 공유할 수 있다.

구현 시 현재 `regionRows()`가 생성하는 region key를 기준으로
명시적 mapping table을 작성하고 테스트로 잠근다.

새로운 geography 추론을 하지 않는다.

### 부산

기존 부산 구·군 detail은 보존한다.

전국 시도 지도는 부산 시도 path까지만 표현하고,
부산 선택 시 기존 구·군 detail을 별도 progressive disclosure로 표시한다.

부산 구·군 polygon을 새로 만들지 않는다.

---

## P1-3. `bank` 업권 처리

### 문제
메인 대시보드는 Strategy 4업권 외에 `bank`를 포함한 5개 업권을 표시한다.

### 결정
`bank`를 위해 새로운 지역 의미를 만들지 않는다.

규칙:

1. 현재 `regionRows()`가 concrete region을 반환하는 bank 데이터가 있다면
   그 기존 값만 그대로 사용한다.
2. region 정보가 없거나 nationwide 의미뿐이라면
   시도별로 복제하지 않는다.
3. bank-only 선택에서 regional evidence가 없으면
   지도는 중립 상태로 표시하고 다음과 같이 안내한다.

```text
현재 수집 데이터 기준 지역 분포를 제공할 수 없습니다.
```

금지:

- 전국 은행 값을 17개 시도에 동일 복제
- 기관명으로 지역 추정
- 주소를 새로 추론하여 지도화
- bank를 임의로 Strategy 4업권 geography 계약에 편입

---

## P1-4. 당사 데이터 부재 fail-mode

### 문제
고려저축은행의 당사 금리는 수집 데이터 파생값이다.

특정 기간에서 당사 데이터가 없으면
Position Matrix와 Quick Action의 기준점이 사라진다.

### 결정
fail-closed 표시를 사용한다.

예:

```text
24개월
당사 데이터 없음
```

이 경우:

- 당사 순위 계산 안 함
- TOP10 gap 계산 안 함
- +5/+10/+15bp Quick Action 비활성
- 다른 기간 금리를 대체 사용하지 않음
- 0% 또는 N/A 숫자로 계산하지 않음

가능하면 사유를 함께 표시한다.

```text
현재 수집 데이터에 해당 기간 당사 상품 없음
```

---

# 2. Stage A — Main Dashboard Korea Map

## 2.1 대상

메인 대시보드:

```text
web/templates/site.html
```

현재 사각형 지역 타일:

```text
regionBars()
regionRows()
regionBasis()
```

기존 계산/필터 path를 최대한 유지한다.

---

## 2.2 핵심 구현 원칙

```text
Data calculation = 기존 유지
Presentation      = 사각형 → 한국 지도
```

즉:

- `regionBasis()` 필터 의미 유지
- `regionRows()` median 유지
- 지도는 presentation 변경
- 기존 비지역 필터 반응성 유지
- 계산값 전후 회귀검증

---

## 2.3 메인 지도 정보 구조

```text
전국 금리 분포
현재 선택조건 · geography 기준

[대한민국 지도]

hover / click
- 지역명
- 지역 median
- 비교 데이터 수
- 기존 basis 설명

부산 선택
→ 기존 부산 구·군 detail

범례
낮음 ───── 높음
```

Stage A에서 지역 최고/평균을 새로 추가하지 않는다.

---

## 2.4 Filter Reactivity

현재 지역 타일은 지역 외 다른 필터에 반응한다.

지도도 동일해야 한다.

예:

- 업권
- 상품 종류
- 가입기간
- 우대조건
- 기타 메인 필터

필터 적용 후 기존 `regionBasis()`가 바라보던 동일 universe를 사용한다.

---

## 2.5 Main Map Acceptance Criteria

- [ ] 기존 사각형 region tile UI 제거
- [ ] 대한민국으로 즉시 인지 가능한 SVG 지도 표시
- [ ] Strategy Gate OFF에서도 지도 정상 표시
- [ ] `site_service.py` Strategy gate cleanup 계약 변경 없음
- [ ] 기존 `regionRows()` median 값 유지
- [ ] 9개 기존 region bucket → SVG path mapping 명시
- [ ] 부산 기존 구·군 detail 보존
- [ ] bank 데이터 없는 경우 fail-closed neutral state
- [ ] 지역 외 기존 필터에 동일하게 반응
- [ ] 전환 전후 동일 filter snapshot에서 region 수치 동일
- [ ] desktop 정상
- [ ] mobile 390px 정상
- [ ] console/page error 없음
- [ ] 메인 테이블/필터 회귀 없음

---

# 3. Stage B — Strategy Decision Cockpit Core

## 3.1 권장 정보 순서

```text
1. 시장 변화 브리핑
2. 우리 회사 Position Matrix
3. 목표 순위 필요금리
4. Quick Action Scenario
5. 주요 경쟁 View
6. 우대조건 / 지역 / TOP5 / provenance
```

단, 1번 브리핑은 현재 historical contract 범위 안에서만 표시한다.

---

# 4. 시장 변화 브리핑 v1

## 4.1 Stage B 범위

```text
업권: 저축은행
기간: 12개월
변화기간: 최근 30일
```

예:

```text
최근 30일 12개월 예금
67건 인상 · 187건 인하

현재 상단 3.80%
당사 3.50%
당사와 상위권 gap +10bp
```

Stage B에서 `7일`이라는 라벨을 만들지 않는다.

---

## 4.2 Combined / Mutual Finance 모드

상호금융 또는 통합 모드에서는
저축은행 historical trend를 전체 선택시장 trend처럼 보이게 하지 않는다.

표현 예:

```text
현재 비교시장: 저축은행 + 상호금융
Historical change evidence: 저축은행 12개월 · 30일
```

두 universe를 시각적으로 분리한다.

---

# 5. 우리 회사 Position Matrix

## 5.1 기간

- 6M
- 12M
- 24M
- 36M

## 5.2 표시

| 기간 | 당사 | 시장 평균 | 상위 10%선 | 10위선 | 최고 | 당사 순위 | 10위까지 |
|---|---:|---:|---:|---:|---:|---:|---:|

`상위 10%선`과 `10위선`을 같은 값으로 취급하지 않는다.

화면 밀도가 높으면 기본 열은 다음으로 축소 가능하다.

| 기간 | 당사 | 시장 평균 | 10위선 | 당사 순위 | 필요 bp |
|---|---:|---:|---:|---:|---:|

상위 10%선은 보조 정보/tooltip로 이동 가능하다.

---

## 5.3 Rank denominator

모든 순위에는 분모와 universe를 표시한다.

예:

```text
11위 / 321개
저축은행 · 12개월 · 수집 데이터 기준 최고금리
```

통합 모드 예:

```text
247위 / 24,546개
통합 비교 · 12개월
```

숫자는 실제 runtime 데이터에서 계산하며
명세 예시 숫자를 하드코딩하지 않는다.

---

# 6. 목표 순위 필요금리

## 6.1 목표

- TOP 10위
- TOP 5위
- 직접 순위

## 6.2 계산 계약

현재 Strategy simulator가 사용하는
동일한 aggregated product universe와 동일한 rank function을 사용한다.

새로운 별도 ranking universe를 만들지 않는다.

필요금리는:

```text
가상 당사 금리를 적용했을 때
목표 rank 이하가 되는 최소 금리
```

로 정의한다.

동률 처리:

- 기존 ranking epsilon 계약 유지
- UI 표시 precision에서 최소 달성 금리를 명확히 표시
- tie case를 fixture test로 잠금

출력 예:

```text
10위 진입 필요금리 3.60%
현재 대비 +10bp
예상 10위 / 321개
```

---

# 7. Quick Action Scenario

## 7.1 기본안

```text
유지
+5bp
+10bp
+15bp
```

각 시나리오는 목표순위 계산과 동일 universe를 사용한다.

출력:

- 제안금리
- 예상 순위 / 분모
- 시장 평균 대비 spread
- 10위/5위 진입 여부

당사 기준 데이터가 없는 기간은 비활성화한다.

---

# 8. 주요 경쟁 View v1

Persistence는 도입하지 않는다.

Stage B 자동 기준:

1. 현재 당사 금리와 인접한 경쟁상품
2. 현재 상위 10위 경쟁상품
3. 부산 경쟁군
4. 최근 변경상품 — 단, Stage B에서는 현재 지원되는 저축은행 12M · 30일 범위만

표시:

```text
금융사
상품
기간
현재금리
당사 대비 spread
현재순위
지원되는 경우 최근 변경
```

---

# 9. Benchmark 정책

## 9.1 Primary decision market

기본 의사결정 기준:

**저축은행**

이유:

- 당사 직접 경쟁시장
- 현재 historical evidence가 가장 성숙
- 실제 Position/순위 해석이 명확

---

## 9.2 상호금융

상호금융은 없애지 않는다.

역할:

```text
외부 조달금리 benchmark
```

표현 예:

```text
저축은행 12M 10위선 3.60%
상호금융 12M 상단 3.75%
```

상호금융과 저축은행을 합친 단일 순위를
기본 의사결정값처럼 강조하지 않는다.

기존 시장 모드 3종은 유지하되
모드마다 ranking denominator를 명시한다.

---

# 10. Stage C — Historical Change Intelligence

Stage B에서 제외된 변화 분석을 여기서 구현한다.

## Evidence Gate

현재 `rate_observations`와 existing history가
아래 파생을 안정적으로 지원하는지 먼저 확인한다.

목표:

- 7D / 30D
- 6M / 12M / 24M / 36M
- 업권별 historical change
- TOP5 신규 진입 / 이탈
- TOP10 churn
- 당사 gap 확대 / 축소
- 기간별 시장 상단 변화
- 중요 경쟁사 변화

필요 시 Strategy 전용 derived historical payload를 확장한다.

허용:

```text
strategy_service.py 파생 레이어 수정
```

기본적으로 변경하지 않음:

```text
collector
DB schema
migration
canonical max_rate
```

---

# 11. Scope 정의 수정

기존 표현:

```text
UI + 파생분석
```

최종 표현:

```text
Stage A:
Main presentation layer 중심

Stage B:
Strategy UI + 현재 계약 범위의 파생분석

Stage C:
Strategy historical derived layer 확장
```

따라서 Stage B/C가 순수 UI 작업이라는 표현은 사용하지 않는다.

---

# 12. Non-Goals

Evidence 없이 다음을 변경하지 않는다.

- collector
- canonical `max_rate`
- source precedence
- DB schema
- migration
- stable product identity
- NH e-joy linkage
- geography semantics
- 부산 drill-down 업권 경계
- Strategy Preview isolation
- shared writer concurrency
- Production Strategy Release Gate

또한 Stage A에서는:

- Strategy Gate asset publish/delete 정책 변경 안 함
- region metric을 median에서 임의 변경 안 함

---

# 13. Test / Verification

## Stage A

### Contract
- region mapping unit/contract test
- median 값 회귀 test
- filter reactivity test
- bank fail-mode test
- 부산 detail preservation

### UI
- main production-style preview
- 1280px
- 1440px 권장
- 390px
- hover/click
- page/console error 없음

### Gate
- Strategy Release Gate OFF 상태에서 main map 표시
- gated `korea-sido.svg` 부재 상태에서도 main map 표시

---

## Stage B

### Calculation
- same aggregated universe
- rank denominator
- rank tie
- target-rank reverse calculation
- +5/+10/+15
- own-data-missing fail-mode
- percentile vs ordinal label distinction

### Historical
- Stage B briefing이 savings_bank + 12M + 30D 밖의 데이터를 암시하지 않는지 test

### UI
- Strategy Preview
- 1280px
- 390px
- 모든 market mode
- source/provenance 유지
- console/page error 없음

---

# 14. PR Boundary

## PR A
**Main Korea Map**

포함:

- site.html 지도 presentation
- 기존 region calculation 재사용
- tests

미포함:

- Strategy Decision Cockpit
- historical derived change 확장

---

## PR B
**Strategy Decision Cockpit Core**

포함:

- 30D / savings-bank / 12M 브리핑 v1
- Position Matrix
- 목표 순위 필요금리
- Quick Action
- Watch View v1
- rank denominator UI

미포함:

- 7D
- 전 기간 historical trend
- 상호금융 history
- TOP churn history

---

## PR C
**Historical Change Intelligence**

Evidence Gate 통과 후 별도 진행.

---

# 15. Adversarial Self-Review

구현자는 완료 전에 다음을 반대로 가정하고 검증한다.

> “내 구현이 기존 계약을 깨뜨렸거나 사용자가 숫자를 잘못 해석하게 만든다.”

필수 질문:

1. Gate OFF인데 main map이 asset 부재로 깨지지 않는가?
2. 17개 path를 17개 독립 통계처럼 오해시키지 않았는가?
3. 기존 region median이 평균/최고금리로 바뀌지 않았는가?
4. bank에 가짜 지역 데이터를 만들지 않았는가?
5. 기존 필터 적용 후 지도 수치가 이전 tile과 동일한가?
6. `상위 10%`와 `10위`가 명확히 구분되는가?
7. 순위 분모가 항상 보이는가?
8. 목표순위 계산과 Quick Action이 같은 universe를 쓰는가?
9. 당사 데이터가 없는데 0 또는 대체 금리를 사용하지 않는가?
10. 저축은행 12M 30D history를 통합시장 history처럼 보이게 하지 않는가?
11. Stage B가 Stage C 기능을 암묵적으로 구현하지 않았는가?
12. Strategy Release Gate가 계속 OFF인가?

---

# 16. 최종 착수 조건

Fable 리뷰에서 제기된 P0 2건은 본 v2에서 다음과 같이 해소한다.

```text
A-1 Gate/asset
→ main inline presentation SVG로 분리

B-1 Historical scope
→ Stage B = savings_bank + 12M + 30D
→ 확장은 Stage C
```

P1도 다음과 같이 확정한다.

```text
TOP10 충돌
→ 상위 10% vs 실제 10위 분리

지도 metric
→ 기존 median 유지

17개 geometry
→ 기존 9개 bucket mapping

bank
→ 기존 concrete region만, 없으면 fail-closed

당사 데이터 없음
→ 해당 기간 ranking/action 비활성

rank 의미
→ 분모 + universe 항상 표시
```

따라서 다음 개발 세션은:

1. 최신 main / Issue / PR / CI 재확인
2. **PR A: Main Korea Map**
3. runtime / browser / regression 검증
4. Draft PR
5. 사용자 확인
6. 이후 PR B 착수

순서로 진행한다.

자동 merge하지 않는다.

Production Strategy Release Gate는 OFF로 유지한다.
