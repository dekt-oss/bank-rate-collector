# 전략 대시보드 실제 구현 — 2026-08-13

## 목적

`docs/specs/20260812-strategy-dashboard-v1.md`의 비공개 Preview / release gate 계약을 유지하면서,
수신상품 담당자가 경쟁 금리와 시장 흐름을 한 화면에서 읽고 신상품 제안금리의 위치를 판단할 수 있는
실제 데이터 기반 전략 대시보드를 구현한다.

이번 디자인 기준은 dark navy/charcoal 기반의 고밀도 분석 화면이다. 밝은 카드가 반복되며 화면 비율이
무너지는 이전 초안 대신, 동일한 어두운 surface 안에서 green/gold를 핵심 숫자와 상태에만 사용한다.

## 화면 구조

### 1. 상단

- `SB 인사이트` 브랜드
- `검색 조회 / 전략 대시보드` 2메뉴
- 최신 발행 시각과 `collection_health` 상태
- 제목 `수신상품 전략 대시보드`
- 분석범위: 저축은행 / 정기예금 / 12개월 / 최고금리 / 최근 변화 30일

### 2. 핵심 KPI 4개

한 행에 다음 네 지표만 둬 첫 화면 비율과 정보 위계를 고정한다.

1. 시장 최고 금리
2. 시장 평균 금리
3. 현재 비교군 상품 수 / 기관 수 / 중앙값
4. 상위 10% 진입선

별도 `핵심 시장 브리핑` 카드 3개를 KPI 위에 중복 배치하지 않는다.

### 3. 경쟁사 / 지역 분포

- 좌측: `경쟁사 TOP 5`
  - 기관+상품+기간 단위 대표값
  - 기본금리 / 우대폭 / 최고금리
- 우측: `본점 소재지별 금리 분포`
  - 지역 최고금리 실제 값으로 node를 표시
  - 가장 높은 지역만 gold highlight
  - 지역은 본점 소재지 참고값이며 지점 적용금리가 아님을 계속 표시

### 4. 분석 카드 3개

- `우대조건 트렌드`
  - 실제 우대조건 원문이 `present`인 상품만 분모에 포함
  - 표준 taxonomy tag별 상품 비중
  - 한 상품의 복수 조건은 중복 가능
- `신상품 기획 시뮬레이터`
  - 기본금리 / 우대금리
  - 우대조건 수 selector
  - 가입기간 6/12/24/36개월 selector
  - 가입기간 선택 시 실제 해당 기간 비교상품 universe로 예상 순위와 시장 포지션을 다시 계산
  - 예상 수신액은 사용자 입력 baseline / sensitivity가 모두 있을 때만 계산
- `시장 인사이트`
  - 최근 30일 상승/하락 이벤트 우세 방향
  - 실제 본점 소재지별 최고금리 강세 지역
  - 실제 우대조건 taxonomy 상위 비중
  - 별도 생성형 예측 수치나 가공된 임의 시장수치를 만들지 않음

### 5. 기간별 금리 추이

`기간별 금리 추이`는 목업 line을 사용하지 않는다.

현재 DB는 금리값이 바뀔 때만 `rate_observations` 새 행을 생성한다. 따라서 `valid_from` 날짜별로 단순
평균하면 그날 변경된 상품만 평균하게 되어 시장 평균으로 사용할 수 없다.

실제 구현은 다음 순서로 snapshot을 복원한다.

1. 최근 63일의 저축은행 정상 수집(`success`, `partial`, `no_change`) 날짜를 찾는다.
2. 같은 날짜에 여러 실행이 있으면 마지막 수집 시각을 snapshot 시각으로 사용한다.
3. 각 snapshot에서 `valid_from <= snapshot < valid_to` 또는 `valid_to IS NULL`인 관측만 선택한다.
4. 저축은행 / 정기예금 / 12개월 / 최고금리 non-null로 범위를 제한한다.
5. 상품별 여러 variant 중 최고 `max_rate`를 대표값으로 사용한다.
6. 상품 대표 최고금리의 평균을 날짜별 point로 저장한다.
7. 최근 최대 9개 snapshot을 chart에 표시한다.

반환 필드:

- `date`
- `snapshot_at`
- `mean_max_rate`
- `market_max_rate`
- `product_count`

scope의 aggregation은 `product_representative_mean`으로 고정한다.

현재 6/12/24/36개월 미니카드는 canonical `data/table.json`의 현행 수집값에서 계산한다. 기간별 historical
line은 현재 우선순위인 12개월만 DB 이력으로 제공한다.

### 6. 최근 시장 변화

상세 변경 피드는 핵심 화면 비율을 방해하지 않도록 하단 보조영역으로 이동한다.

- 최근 30일
- 상품 변경 이벤트 수
- 상승 / 하락 수
- 영향 세부 관측 수
- 동일 run + 동일 product + 동일 전후 최고금리 transition의 variant 동시 변경은 상품 이벤트 1건
- 원본 `rate_observations` 수정/삭제 없음

## 반응형

### Desktop

- KPI 4열
- TOP5 / 지역 분포 2열
- 트렌드 / 시뮬레이터 / 인사이트 3열
- 기간별 금리 추이 full width

### Tablet

- KPI 2열
- 주요 2열 영역은 1열 전환
- 분석 카드 2열 후 인사이트 full width

### Mobile

- KPI와 분석카드 1열
- TOP5는 가로 table 대신 상품별 카드형 row
- 지도 높이 축소
- simulator controls / 결과를 세로 재배치
- 기간별 chart 높이 축소
- `viewport-fit=cover`, `prefers-reduced-motion` 적용

## 데이터·운영 경계

- DB schema 변경 없음
- migration 변경 없음
- collector 변경 없음
- canonical `data/table.json` 재사용
- historical trend / market changes는 기존 DB의 read-only 집계
- 공식 release gate 기본 OFF 유지
- Preview workflow만 `RATE_MONITOR_STRATEGY_DASHBOARD=1`
- Preview는 production DB를 read-only 복원한 copy에 migration을 적용하고 isolated preview branch만 갱신
- 공식 `rate-data`에는 승인 전 전략 화면을 발행하지 않음

## Acceptance

- 4개 핵심 KPI가 현재 12개월 저축은행 정기예금 실제 비교상품에서 계산된다.
- TOP5 / 지역 / 우대조건 / 기간별 현재 평균이 canonical table에서 계산된다.
- 가입기간 selector가 simulator의 실제 비교상품 universe를 변경한다.
- 사용자 가정이 없으면 예상 수신액 숫자를 만들지 않는다.
- 시장 인사이트의 숫자는 현재 비교표 또는 DB 시장변화 집계에서만 나온다.
- historical line은 `valid_from`/`valid_to` 유효구간을 복원한 실제 snapshot에서 계산된다.
- production DB Preview에서 historical point가 1개 이상 확인된다.
- 동일 상품 variant 동시 변경은 시장 이벤트 한 건으로 표시된다.
- 인라인 JavaScript가 `node --check`를 통과한다.
- Ruff / pytest / empty DB migration CI가 통과한다.
- official release gate는 사용자 승인 전 OFF다.
