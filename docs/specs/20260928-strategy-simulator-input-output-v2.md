# Strategy Simulator Input/Output v2 — 기본 펼침 + 가입방식 + 목표금액 역산 UX

작성일: 2026-09-28  
대상: `dekt-oss/bank-rate-collector` Strategy 금리설계 화면  
기준 main: `7ac7a436616a8ab86b807d99fd01e3def7a2ba0d`

## 1. 목적

금리설계 화면을 실제 업무 순서대로 읽히게 한다.

1. 금리설계 상세/예측엔진을 기본 펼침 상태로 시작한다.
2. 시뮬레이터에 가입방식 조건(`전체 / 비대면 / 대면`)을 추가한다.
3. `희망 총수신액 → 금리 찾기`에서는 목표금액을 입력으로 받고, 지원 후보 중 목표 이상이 되는 가장 낮은 금리를 결과로 명확히 표시한다.
4. 시뮬레이터의 조건 입력과 결과 출력을 시각적으로 분리한다.

## 2. 현재 근거

### 2.1 기본 접힘

최종 Lean IA reconciler가 `#lean-planning-detail`을 기본 closed로 만들고
`#prediction-panel`도 숨긴다. 그래서 사용자가 금리설계에 들어와도 먼저
`예측엔진 보기`를 눌러야 한다.

### 2.2 목표금액 역산

기존 `StrategyTargetCandidate.findFirstCandidate`는 이미 아래 fail-closed 계약을 가진다.

- forecast surface에 실제 존재하는 candidate만 사용
- 금리 오름차순으로 정렬
- 목표 총수신 이상이 되는 첫 candidate 선택
- 보간/외삽/연속 최적화 없음
- surface 최대치보다 목표가 높으면 `out_of_support`

이번 작업은 이 산식을 바꾸지 않고 결과 UX를 `추천 검토금리`로 명확히 한다.

### 2.3 가입방식 데이터

현재 production Strategy table은 `join_channel`을 포함하고 있으며
`branch / mobile / any / unknown / internet / agent`가 실제 존재한다.

다만 `join_channel=any` 중에는 상품명에 `비대면` 또는 `대면`이 명시된 행이
함께 존재한다. 따라서 `any`를 무조건 비대면/대면 양쪽에 넣으면 오분류한다.

가입방식 선택 시에는 fail-closed classification을 사용한다.

- **비대면**
  - 명시 채널: `internet / mobile / telephone`
  - 또는 `any/unknown`이더라도 상품명/조건에 비대면·인터넷·모바일·온라인 등 명시 근거가 있는 경우
- **대면**
  - 명시 채널: `branch / agent`
  - 또는 `any/unknown`이더라도 상품명에 `대면`이 명시되고 비대면 근거와 충돌하지 않는 경우
- **전체**
  - 기존과 동일하게 모든 채널을 포함
- 특정 가입방식에서 분류 근거가 없는 `any/unknown`은 제외한다.

## 3. UI 계약

### 3.1 기본 펼침

- `#lean-planning-detail`: 첫 로드 open
- `#prediction-panel`: 첫 로드 visible
- `#prediction-toggle`: `aria-expanded=true`, 문구 `예측엔진 닫기`
- 사용자가 직접 접거나 엔진을 닫은 이후에는 그 세션 조작을 존중한다.

기관/우대조건/특판의 secondary disclosure 기본 closed 계약은 유지한다.

### 3.2 시뮬레이터 입력

`1. 조건 입력` 영역에서 다음을 분리해 표시한다.

- 계산 방식
  - 금리 → 결과 계산
  - 희망금액 → 금리 찾기
- 가입방식
  - 전체
  - 비대면
  - 대면
- 계산값
  - 금리 모드: 검토금리
  - 목표 모드: 희망 총수신액

특정 가입방식 선택 시 명시 근거가 없는 상품은 비교군에서 제외한다는 문구를 표시한다.

### 3.3 결과

`2. 결과 출력` 영역을 별도 카드로 표시한다.

금리 모드:
- 검토금리
- 예상 총수신
- 현재 대비
- 시장 위치

목표금액 모드:
- **추천 검토금리**
- 예상 총수신
- **목표 대비**
- 시장 위치

`추천 검토금리`는 최적화 결과가 아니라
`목표 이상이 되는 첫 existing candidate`임을 계속 명시한다.

## 4. 가입방식 적용 범위

가입방식 필터는 다음 실제 시장 비교에 적용한다.

- 고려저축은행 anchor
- 시장 비교상품 universe
- 시장 순위 / TOP10 / TOP25 / 중앙값
- 현재 금리 주변 경쟁상품
- 목표금액 candidate가 사용하는 channel-scoped anchor

Public Structural 상세도 같은 가입방식 선택을 소비해 상·하위 화면이 서로 다른
시장 universe를 보여주지 않게 한다.

Relative Pricing R1은 현재 read-model이 가입방식별 계약을 제공하지 않으므로
특정 가입방식 선택 시 임의로 재해석하지 않고 `가입방식별 근거 미지원`으로
fail closed한다.

Size Peer는 기존 `비대면 / 부산 대면` 독립 eligibility 계약을 유지한다.

## 5. 비범위 / 안전 경계

변경하지 않는다.

- inflow β/γ 계수
- 신규수신/재예치 계산식
- surface candidate grid 반경/간격
- `findFirstCandidate` 선택 알고리즘
- source precedence
- canonical rate
- stable product identity
- DB/schema/migration
- Relative Pricing peer 선정 로직
- Size Peer 모집단/순위 로직

## 6. 검증

- 가입방식 classifier Node contract
- target candidate 기존 contract 비회귀
- simulator static contract
- Lean IA 기본 open contract
- Public Structural이 동일 가입방식 필터를 소비하는 계약
- desktop/mobile production-data browser smoke
  - 금리설계 상세 기본 open
  - 예측엔진 기본 visible
  - 가입방식 selector 존재
  - 비대면/대면 전환 시 비교 universe/시장위치 재계산
  - 목표금액 입력 시 추천 검토금리 output
  - 입력/결과 영역 시각적 분리
- Ruff / full pytest / empty DB migration
- merge 후 UI-only publish / rate-data / Vercel / production artifact 확인
