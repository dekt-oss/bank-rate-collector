# Stage C2 — Market Intelligence UI

```yaml
date: 2026-08-18
repository: dekt-oss/bank-rate-collector
base: main
related_issue: 108
production_strategy_release_gate: OFF
stage: C2
```

## 목적

C1에서 계산한 7D/30D 시장이력 파생값을 금리결정자가 즉시 읽을 수 있는 브리핑으로 만든다.

핵심 질문은 다음이다.

> 최근 시장이 실제로 오르고 있는가, 어느 구간이 움직이는가, 당사와의 간격은 좋아지고 있는가?

순위 자체를 목표로 하지 않는다.

## 화면 우선순위

1. 방향: 상승 / 하락 / 보합 / 혼조
2. 시장 중앙값 변화 bp
3. 상위 10% 진입선 변화 bp
4. Rate Change Breadth
5. 당사 spread 변화 또는 비교상품 평균 변화
6. 인상/유지/인하 비중
7. 상위 10% churn
8. 실제 비교 snapshot 기간과 coverage

## Selector

- 업권: 저축은행 / 신협 / 새마을금고 / 농·축협
- 기간: 6 / 12 / 24 / 36개월
- window: 7D / 30D

각 selector는 C1의 32개 scope cell을 직접 선택한다.

## Evidence 표시

`status != supported`인 scope는 숫자를 만들지 않는다.

예:

- `insufficient_history` → 비교 이력 부족 + C1 reason
- `unsupported_rate_contract` → 과거 최고금리 계약 미지원 + reason
- `no_data` → 최신 snapshot 데이터 없음

특히 농·축협은 historical e-joy base+add 재구성 계약이 생기기 전까지 숫자를 표시하지 않는다.

## 기존 화면과 역할 분리

기존 `기간별 현재금리 · 12개월 시장 추이`는 장기 흐름을 보는 보조 차트로 유지한다.

C2는 그 위에서:

- 7D/30D 정량 변화
- 범위별 비교
- Evidence Gate

를 담당한다.

## 구현 방식

- `market_intelligence_presentation.py`에서 presentation-only injection
- C1 payload 외 별도 계산 없음
- 기존 Strategy template 대규모 재작성 금지
- Stage B Decision Cockpit 합성 경로에서 Strategy 전용으로만 호출
- idempotent injection

## 검증

- Python presentation contract tests
- 기존 전체 pytest / Ruff / migration
- isolated Strategy Preview build
- Playwright desktop 1280px / mobile 390px
- NH fail-closed 문구
- horizontal overflow / runtime console error

## 비범위

- 외부 신규지표 수집
- 내부 수신실적 calibration
- NH historical base+add reconstruction
- Strategy Release Gate ON
