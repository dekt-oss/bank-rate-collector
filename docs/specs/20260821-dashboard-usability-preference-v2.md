# Dashboard usability + Preference Intelligence v2 — 2026-08-21

## 목표

1. 검색 조회 전국 지도는 본토+제주 crop을 유지하면서 100% 브라우저 배율에서 한 단계 크게 읽히게 한다.
2. 제주 등 하단 지역 hover tooltip이 지도 stage 밖으로 잘리지 않도록 viewport/stage 안에서 flip + clamp한다.
3. 전략 대시보드는 브라우저 100%에서 약 110% 체감의 실제 CSS 타이포/간격으로 확대한다. `zoom`/transform은 사용하지 않는다.
4. 화면의 우대조건 비중은 전체 시장 상품이 아니라 **우대조건이 실제 존재하는 상품(`preference_status=present`)**을 분모로 한 조건별 상품 침투율로 표시한다.
5. 상호금융 우대조건은 공통 taxonomy를 유지하며, 선택된 신협/새마을금고/농·축협을 하나의 **상호금융 통합 시장**으로 재집계해 표시한다.
6. 원천 우대정보 미제공(MISSING)과 명시적 조건 없음(NONE)을 계속 구분한다.

## 계산·표시 계약

- 단위: Strategy `product + term + geography` representative.
- 화면 `전체 우대상품 침투율`: 해당 표준조건 보유 representative 수 ÷ `preference_status == present` representative 수.
- 화면 `상위금리군 침투율`: 상위 10% 안의 해당 표준조건 보유 representative 수 ÷ 상위 10% 안의 `present` representative 수.
- 화면 `침투율 차이`: `상위금리군 침투율 - 전체 우대상품 침투율` (%p). 세 컬럼은 반드시 같은 상품 분모를 사용한다.
- 하나의 상품이 여러 표준 우대조건에 동시에 속할 수 있으므로 조건별 상품 침투율 합계는 100%를 초과할 수 있다.
- `market_share` / `top_tier_share`는 별도 보조값인 **표준조건 출현건수 구성비**이며 합계가 100%다. 화면의 상품 침투율과 혼용하지 않는다.
- 구성비 차이를 보존할 경우 `top_tier_composition_lift_pp`로 분리하고, 화면의 `top_tier_lift_pp`는 상품 침투율 차이를 뜻한다.
- `known_preference_share`는 원천 정보 제공률로 유지한다.
- `preference_bearing_share_among_known`은 원천에서 우대조건 여부를 판별할 수 있는 상품 중 실제 조건 보유 비율이다.
- `NONE`은 조건 없음, `MISSING`은 원천 미제공이며 서로 대체하지 않는다.

## 상호금융 계약

- 공통 taxonomy를 사용한다. 업권별 taxonomy를 별도로 만들지 않는다.
- 상단 체크박스는 데이터 포함/제외 범위만 제어한다.
- D2 카드에는 선택된 상호금융 업권을 pooled market으로 재계산한 단일 카드가 나온다.
- 2~3개 업권 선택 시 pooled market의 상위 10% cutoff도 통합 집합에서 다시 계산한다.
- 1개 업권만 선택한 경우 기존 `scopes[]`의 해당 업권 결과를 재사용한다.
- `mutual_finance_scopes[]`에는 중복인 단일 업권 조합을 저장하지 않고 2~3개 조합만 저장한다.
- 원천별 정보 제공률은 보조 근거로 남겨 새마을금고 등 source limitation을 숨기지 않는다.

## 비범위

- DB/schema/migration
- 수집기/원천 파서 변경
- 금리 계산/source precedence/stable product identity
- Strategy Release Gate
- 내부 실적 calibration/수신효과 추정
