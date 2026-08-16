# 전략 대시보드 v2 외부 리뷰용 프롬프트

아래 내용을 그대로 복사해 다른 리뷰 에이전트/모델에 전달한다.

---

```text
`dekt-oss/bank-rate-collector`의 수신상품 전략 대시보드 다음 개선판을 구현하기 전에 설계 리뷰를 해주세요.

중요: 이번 요청은 구현 요청이 아닙니다. 코드를 수정하거나 PR을 만들지 말고, 현재 Preview와 제안 문서를 검토한 뒤 문제점·보완안·우선순위를 제시해 주세요.

## Source of Truth

저장소:
- dekt-oss/bank-rate-collector

현재 구현 기준 브랜치:
- feat/strategy-dashboard-korea-map

현재 구현 기준 commit:
- 89813732c7e27f45bf51de2fc971a8ecd7151e93

현재 main:
- bdad96135fc9bc6a37dfca62fd7803ffadb76949

현재 Preview:
- https://bank-rate-collector-git-strategy-preview-dekt-oss-projects.vercel.app/strategy.html

관련 PR:
- #103 전략 대시보드 전국 지도 / 부산 drill-down
- #104 수신금액 예측엔진 v1 + 정보 흐름 재배치
  - #104는 #103 브랜치로 merge 완료

반드시 먼저 읽을 문서:
1. docs/specs/CURRENT.md
2. docs/specs/20260812-strategy-dashboard-v1.md
3. docs/specs/20260816-inflow-prediction-v1.md
4. docs/specs/20260816-inflow-prediction-v1-evidence.md
5. docs/specs/20260816-strategy-dashboard-v2-review-plan.md

가능하면 실제 생성 Preview와 관련 코드도 확인해 주세요:
- src/rate_monitor/services/strategy_service.py
- src/rate_monitor/services/strategy_refinement_service.py
- src/rate_monitor/services/inflow_prediction_service.py
- tests/test_strategy_dashboard_refinement.py
- .github/workflows/strategy-preview.yml

## 현재 화면의 정보 흐름

1. 시장 핵심지표
   - 시장 최고금리
   - 시장 평균금리
   - 현재 비교군
   - 상위 10% 진입선

2. 시장 흐름
   - 63일 금리 추이
   - 최근 30일 시장 변화

3. 경쟁 구조
   - 전국 본점 소재지별 금리 분포
   - 경쟁사 TOP5

4. 시장 해석
   - 시장 인사이트
   - 우대조건 트렌드

5. 신상품 기획
   - 기본금리 / 우대금리 / 가입기간
   - 예상 최고금리 / 예상 시장순위
   - 시장 포지션
   - 필요할 때 여는 수신금액 예측엔진

## 다음 개선판 제안의 핵심

A. 시장 흐름 기간을 7일 / 30일 / 90일로 분리
B. 단순 상승·하락 건수를 넘어 시장 변화의 폭과 확산 정도 표시
C. TOP5/TOP10 cutoff의 기간별 이동 표시
D. 인사이트를 `근거 → 해석 → 기획 영향` 구조로 강화
E. 자동 정답 대신 시장기준 전략안 A/B/C 비교
F. 현재 / +5bp / +10bp / +15bp / 직접입력안을 한 표에서 비교하는 5bp 시나리오 매트릭스

## 반드시 지켜야 할 기존 계약

- 저축은행 정기예금 중심
- 기간별 동일 기간끼리 비교
- 최고금리 기준
- max_rate NULL을 기본금리로 대체하지 않음
- 동일 기관+상품+기간 대표 최고금리 dedupe 계약 유지
- 공동순위 유지
- 지역은 판매지역이 아니라 본점 소재지 기준 참고값
- 부산 district 계산 계약 유지
- source precedence / stable product identity 변경 금지
- collector 변경 금지
- production Release Gate는 별도 승인 전 OFF

수신예측 관련:
- 현재 β/γ는 고려저축은행 실적 기반 calibrated 계수가 아님
- 저/기준/고민감 stress assumption임
- 내부 실적이 없으므로 `최적 금리`, `정확한 예상 수신액`처럼 표현하면 안 됨
- 수신금액 입력이 없으면 금액을 생성하면 안 됨

## 특히 검토해 주세요

### 1. 7일 / 30일 / 90일 설계

현재 rate_trend 기본 window는 63일입니다.

- 7/30/90이 실제 수신상품 기획에 적절한 기간 구분인지
- 90일을 위해 payload/window를 확장하는 것이 맞는지
- 90일 이력이 부족하면 `보유 전체`가 더 좋은지
- 기간별 observation_days / 결측을 어떻게 보여줘야 하는지

### 2. 시장 변화 확산지수

제안식:

breadth = (상승 이벤트 수 - 하락 이벤트 수)
          / (상승 이벤트 수 + 하락 이벤트 수)

- 이 정의가 충분히 유용한지
- 같은 금융회사의 여러 상품 변경 때문에 왜곡될 위험은 없는지
- 상품 기준 / 기관 기준 / 둘 다 중 어떤 방식이 적절한지
- 더 단순하고 설명 가능한 대안이 있는지

### 3. 상위권 압력

기간별로 다음을 비교하려고 합니다.

- 시장 최고
- TOP5 cutoff
- TOP10 cutoff
- 시장 평균

- 이 네 값이 실무적으로 충분한지
- TOP5 공동순위 처리 정의는 어떻게 하는 것이 가장 일관적인지
- 최고금리 한 상품의 특판 노이즈를 어떻게 분리할지

### 4. 5bp 시나리오 비교표

기본안:
- 현재금리
- +5bp
- +10bp
- +15bp
- 직접입력안

비교 컬럼 후보:
- 제안 최고금리
- 현재 대비 bp
- 예상 시장순위
- 순위 percentile
- TOP10 gap
- 시장 최고 gap
- 시장 평균 gap
- 추가 표면이자비용
- 예상 총수신 stress range

검토할 것:
- 반드시 필요한 컬럼 / 빼야 할 컬럼
- 5bp step이 적절한지
- 비용과 순위를 한 표에 두는 것이 과밀한지
- 어떤 threshold를 시각 강조해야 하는지

### 5. 시장기준 전략안 A/B/C

현재 후보:
- A 순위 확보형
- B 균형형
- C 방어/우대차별화형

중요:
자동 최적금리 추천이 아니라 비교 가능한 전략안이어야 합니다.

검토할 것:
- 이 3분류가 실제 수신상품 기획에 유용한지
- 더 좋은 분류가 있는지
- B 균형형의 기준을 무엇으로 두는 것이 합리적인지
- C에서 우대조건 데이터의 `존재율`을 실제 고객 달성률처럼 오해할 위험을 어떻게 막을지

### 6. 시장 인사이트

현재 5축:
- 시장 방향
- 경쟁 강도
- 당사 위치
- 지역 편차
- 우대조건 구조

제안 구조:
- 신호
- 근거
- 해석
- 기획 영향

검토할 것:
- 이 구조가 지나치게 설명적이거나 장황하지 않은지
- 카드에서 어떤 숫자만 보여주고 상세는 접는 것이 좋은지
- 실제 상품기획 담당자 입장에서 빠진 핵심 인사이트가 무엇인지

### 7. 금융/통계적 안전성

다음 관점에서 adversarial하게 검토해 주세요.

- 파생지표가 시장 전체를 대표하는 것처럼 과장될 가능성
- sparse snapshot에서 추세를 과신할 가능성
- TOP5/TOP10 threshold 계산의 공동순위 문제
- variant dedupe와 event dedupe의 불일치
- 한두 특판이 시장 방향을 왜곡하는 문제
- 당사 비교상품이 없을 때 허구의 anchor가 생기는 문제
- 수신 prediction stress band가 추천엔진에 섞여 과신을 만드는 문제

## 원하는 리뷰 결과 형식

### 1. 결론
- 이 v2 방향을 그대로 진행해도 되는지
- 반드시 수정해야 하는 핵심 3~5개

### 2. 현재 Preview 리뷰
- 유지할 것
- 줄일 것
- 위치를 바꿀 것
- 추가할 것

### 3. 제안별 판정
각 항목을 다음 중 하나로 판정:
- KEEP
- MODIFY
- DROP
- DEFER

대상:
- 7/30/90
- breadth
- TOP5/TOP10 pressure
- 5bp scenario matrix
- 전략안 A/B/C
- insight 구조 강화

### 4. 계산/데이터 계약 리뷰
각 지표의 정확한 정의와 edge case를 지적해 주세요.

### 5. UX 리뷰
데스크톱 기준 정보 밀도와 카드 배치를 평가해 주세요.

### 6. 구현 우선순위
P0 / P1 / P2로 다시 정리해 주세요.

### 7. 구현 전 결정해야 할 질문
최대 10개만 제시해 주세요.

### 8. 최종 권고 구조
가능하면 ASCII wireframe으로 추천 배치를 보여주세요.

## 리뷰 원칙

- 코드/문서에서 확인되지 않는 사실을 추정하지 마세요.
- 현재 구현과 제안 상태를 구분하세요.
- 새 지표를 제안한다면 계산식과 오해 가능성을 함께 적어 주세요.
- `좋다`는 평가보다 무엇을 왜 고쳐야 하는지 우선해 주세요.
- 상품기획 실무자의 의사결정 속도와 데이터 신뢰성을 최우선으로 봐 주세요.
```
