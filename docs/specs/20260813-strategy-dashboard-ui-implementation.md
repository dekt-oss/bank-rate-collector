# 전략 대시보드 UI 구현 기록 — 2026-08-13

## 목적

검색·조회 화면을 유지하면서 별도 전략 대시보드에서 실제 canonical 금리 데이터와 수집 이력을 사용해 시장 비교 및 신상품 금리 WHAT-IF를 제공한다. 운영 release gate는 계속 OFF로 유지한다.

## 사용자 검수 반영 — 지도 / 부산 / 시뮬레이터

2026-08-13 사용자 화면 검수에서 다음 불일치를 확인했고 수정했다.

- 전국 지도가 충분히 크지 않았다.
- 부산 클릭이 같은 지도에서 부산으로 확대되는 대신 지도 아래 카드 상세로 전환됐다.
- 시뮬레이터에 `우대조건 수` 선택이 남아 있었다.

최종 계약은 다음과 같다.

### 지도

- 데스크톱 컨테이너 최대폭: 1380px.
- 지도 카드 최소 높이: 640px.
- 지도 실제 표시 영역: 540px.
- 메인 2열에서 지도:TOP5 비율은 약 1.45:0.75로 지도를 우선한다.
- 전국 지도와 부산 지도는 동일 SVG(`geo-map`)를 재사용한다.
- 부산 node를 클릭하거나 키보드로 실행하면 `showBusanMap()`이 같은 SVG의 viewBox와 내용을 부산 지도 모드로 바꾼다.
- `전국 보기`를 누르면 `renderKoreaMap()`으로 복귀한다.
- 별도 `district-panel`/`district-grid` 방식은 제거했다.

### 부산 상세

저장소에는 검증된 행정경계 polygon geometry가 없으므로 실제 경계처럼 보이는 임의 polygon을 만들지 않는다. 현재 부산 화면은 **구·군 위치 개략도**이며, canonical `district`가 존재하는 구에만 실제 금리를 표기한다.

2026-08-13 production R2 snapshot audit 기준 12개월 대표상품에서 district가 있는 부산 상품은 31개다.

- 동구: 9
- 부산진구: 10
- 연제구: 12

나머지 부산 구·군은 위치 맥락을 위해 표시하되 `데이터 없음`으로 명시한다. 지점이 있다는 이유로 금리를 복제하지 않는다.

### 시뮬레이터

입력은 다음 세 가지 상품조건만 사용한다.

- 기본금리
- 우대금리
- 가입기간 6/12/24/36개월

`우대조건 수`, `condition-segment`, `condition-match`, 조건 복잡도 benchmark는 시뮬레이터에서 완전히 제거한다. 우대조건 자체의 시장분석은 별도의 `우대조건 트렌드` 카드에만 남긴다.

선택 가입기간이 바뀌면 canonical `table.json`에서 `금융기관 + 상품 + 가입기간` 대표상품을 다시 만들고 실제 시장평균·중앙값·TOP10 진입선·제안순위·고려저축은행 현재 최고를 재계산한다.

## 데이터 계약

- 별도 전략용 금리 DB를 만들지 않는다.
- `site-public/data/table.json`이 현재값의 canonical source다.
- 대표상품은 `금융기관 + 상품 + 가입기간` 단위다.
- variant가 여러 개면 최고 `max_rate`를 사용한다.
- 동일 최고금리면 더 최근 `source_effective_at` 행의 source metadata를 사용한다.
- `max_rate IS NULL`에 `base_rate`를 대체하지 않는다.
- 순위는 `1 + proposed_rate보다 높은 대표상품 수`이며 동률은 공동순위다.
- TOP5, KPI, 시뮬레이터가 같은 대표상품 universe를 사용한다.

## Preview / CI evidence

Visual source commit: `f86e3f4d490ab828d4d37e92b59cb9da0679d4ea`

Strategy Preview #21 / run `31672878890`:

- production R2 snapshot read-only restore 성공
- DB 2,112,434,176 bytes
- `rate_observations` 1,519,527
- `products` 80,848
- `product_variants` 329,309
- `collection_runs` 76
- generated canonical table 326,794 rows
- 12개월 전략 대표상품 321개
- historical trend 9 points
- 고려저축은행 historical points 9/9
- generated inline JavaScript `node --check` 성공
- isolated `preview/strategy-dashboard` branch publish 성공

Generated preview commit: `064f68672269852554e10dc6aae4092577ccb2c4`

`preview-source.json`은 source SHA `f86e3f4d...`와 `production:false`를 기록한다.

UI contract test commit: `ad6182074bfdf31ae65d1c820647978cfe247e1b`

PR CI #884 / run `31672981103`:

- Ruff 성공
- pytest **919 passed**
- empty DB Alembic migration 성공
- model/table parity **15 tables** 성공

### Vercel Preview 주의

Generated preview branch publish 자체는 성공했지만 Vercel은 commit `064f686...` 배포에 대해 `Deployment rate limited — retry in 24 hours.`를 반환했다. 따라서 기존 고정 Vercel Preview URL은 이전 배포 화면을 계속 보여줄 수 있으며, 이를 최신 UI runtime 검증으로 간주하지 않는다.

GitHub의 generated preview artifact와 Actions build/JS 검증은 최신 소스를 반영한 것으로 확인했다. Vercel 브라우저 배포는 rate limit 해소 후 재검증이 필요하다.

## 데이터 정확성

UI/canonical 계산 연동과 upstream source 정확성은 분리한다. FSB와 개별 저축은행 자체 공시 불일치는 Issue #98에서 교차검증 구조로 추적한다. 이 UI PR에서 원천 금리를 임의 overwrite하지 않는다.

## Acceptance

- KPI / TOP5 / 지도 / 시뮬레이터는 canonical `table.json` 기반이다.
- 지도는 데스크톱 540px 표시영역을 확보한다.
- 부산 클릭은 같은 SVG를 부산 지도 모드로 전환한다.
- 부산 상세에서 canonical district 없는 구는 금리를 만들지 않는다.
- 시뮬레이터에는 `우대조건 수` 입력이 없다.
- 가입기간은 실제 해당 기간 비교상품 universe를 변경한다.
- 고려저축은행 현재 최고와 제안금리를 비교한다.
- 사용자 가정이 없으면 예상 수신액 숫자를 만들지 않는다.
- inline JavaScript / Ruff / pytest / migration이 통과한다.
- official release gate는 사용자 승인 전 OFF다.
