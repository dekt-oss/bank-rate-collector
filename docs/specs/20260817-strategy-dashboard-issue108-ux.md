# 전략 대시보드 Issue #108 후속 UX 계약

```yaml
document_type: work_order
status: implementation
created_at: 2026-08-17
target_repository: dekt-oss/bank-rate-collector
base_commit: 45e37eed382dc59964c1fb2cff9a6a6abb551f34
issue: 108
inherits: docs/specs/20260812-strategy-dashboard-v1.md
```

## 1. 목적

Issue #108의 요구 1·2를 데이터 계약을 바꾸지 않는 최소 범위로 구현한다.

1. 우대조건 트렌드의 `OTHER(기타)`를 펼치면 현재 발행 데이터에 이미 보존된 원천 우대조건 문구를 확인할 수 있게 한다.
2. `시장 인사이트 + 우대조건 트렌드`를 전국 지도/TOP5보다 먼저 배치한다.
3. 전국 모드의 지도/TOP5 블록 높이를 줄이되 Stage D 부산 drill-down의 판독성 계약은 보존한다.

## 2. Evidence Gate

현재 canonical table에는 `preference`, `preference_status`, `preference_tags`가 함께 발행된다. `preference`는 `rate_observations.raw_preference_text`에서 온 원천 문구이며 lookup으로 압축된다. Stage B 전략 slice는 rows만 필터하고 columns/lookups를 그대로 보존하므로 전략 payload에도 `preference`가 이미 존재한다.

따라서 이번 작업은 DB/schema/migration/taxonomy 변경 없이 클라이언트가 기존 `preference` 열을 디코딩하는 것으로 충분하다.

## 3. FREEZE

- `OTHER`를 임의의 새 세부분류로 재분류하지 않는다.
- 원문을 요약·교정·추정하지 않는다.
- 원천 미제공을 `우대조건 없음`으로 바꾸지 않는다.
- 금리 계산, source precedence, stable product identity, dedupe를 변경하지 않는다.
- 부산 geometry·데이터 좌표·Stage D focus 레이아웃을 변경하지 않는다.
- Release Gate를 켜지 않는다.

## 4. 구현 계약

### 4.1 기타 원문 drill-down

- `expand()`가 `preference`를 `prefRaw`로 디코딩한다.
- 상품 대표 집계에는 `OTHER`가 붙은 원천 문구를 중복 제거해 보존한다.
- 우대조건 트렌드에서 `OTHER`가 노출될 때만 `<details>`를 제공한다.
- 상세에는 최대 5개 distinct source-backed sample을 `금융사 · 상품`과 함께 보여준다.
- 샘플은 실제 원문이며 한 원문에 여러 조건이 함께 있을 수 있음을 명시한다.

### 4.2 정보 순서

DOM 순서를 다음으로 고정한다.

```text
시장 흐름
→ 시장 인사이트 + 우대조건 트렌드
→ 전국 지도 + 경쟁사 TOP5
→ 신상품 기획
```

### 4.3 전국 모드 밀도

- 1121px 이상 전국 모드의 지도/TOP5 최소 높이를 440px 수준으로 낮춘다.
- 전국 지도 stage는 350px 수준으로 낮춘다.
- `.primary.busan-focus`의 650px/560px Stage D 계약은 유지한다.
- 모바일에서는 기존 Stage D 판독성 우선 규칙을 유지한다.

## 5. 검증

- build 산출 HTML 계약 테스트
- 전체 ruff/pytest/migration
- Strategy Preview production DB read-only build
- Vercel Preview 1280px/390px 실렌더링
- `OTHER`가 실제 데이터에 존재하면 원문 펼침을 실제 DOM으로 확인
- 부산 클릭 후 금리 열·중심 라벨·데이터 구 목록 회귀 확인

## 6. 범위 밖

Issue #108 요구 3인 상호금융 통합 비교는 별도 Evidence Gate 문서에서 다룬다. 업권별 최고금리·지역 scope·coverage/freshness 의미를 확인하기 전에는 이 PR에서 비교 universe를 넓히지 않는다.
