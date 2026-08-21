# Dashboard usability + Preference Intelligence v2 — 2026-08-21

## 목표

1. 검색 조회 전국 지도는 본토+제주 crop을 유지하면서 100% 브라우저 배율에서 한 단계 크게 읽히게 한다.
2. 제주 등 하단 지역 hover tooltip이 지도 stage 밖으로 잘리지 않도록 viewport/stage 안에서 flip + clamp한다.
3. 전략 대시보드는 브라우저 100%에서 약 110% 체감의 실제 CSS 타이포/간격으로 확대한다. `zoom`/transform은 사용하지 않는다.
4. 우대조건 비중은 전체 상품이 아니라 **우대조건이 실제 존재하는 상품(`preference_status=present`)**을 분모로 한다.
5. 상호금융 우대조건은 공통 taxonomy를 유지하며, 선택된 신협/새마을금고/농·축협을 하나의 **상호금융 통합 시장**으로 재집계해 표시한다.
6. 원천 우대정보 미제공(MISSING)과 명시적 조건 없음(NONE)을 계속 구분한다.

## 계산 계약

- 단위: Strategy `product + term + geography` representative.
- 시장 우대조건 분모: `preference_status == present`인 representative 수.
- 상위금리 우대조건 분모: 상위 10% 상품 중 `preference_status == present`인 representative 수.
- 하나의 상품이 여러 표준 우대조건에 동시에 속할 수 있으므로 카테고리 비중 합계는 100%를 초과할 수 있다.
- `known_preference_share`는 원천 정보 제공률로 유지한다.
- `preference_bearing_share_among_known`은 원천에서 우대조건 여부를 판별할 수 있는 상품 중 실제 조건 보유 비율이다.
- `NONE`은 조건 없음, `MISSING`은 원천 미제공이며 서로 대체하지 않는다.

## 상호금융 계약

- 공통 taxonomy를 사용한다. 업권별 taxonomy를 별도로 만들지 않는다.
- 상단 체크박스는 데이터 포함/제외 범위만 제어한다.
- D2 카드에는 선택된 상호금융 업권을 pooled market으로 재계산한 단일 카드가 나온다.
- pooled market의 상위 10% cutoff도 통합 집합에서 다시 계산한다.
- 원천별 정보 제공률은 보조 근거로 남겨 새마을금고 등 source limitation을 숨기지 않는다.

## 비범위

- DB/schema/migration
- 수집기/원천 파서 변경
- 금리 계산/source precedence/stable product identity
- Strategy Release Gate
- 내부 실적 calibration/수신효과 추정
