# 리뷰 점검표 — bank-rate-collector (harness-reviewer 가 항목마다 판정)

근거 문서: `AGENTS.md`, `docs/data-trust.md`, `.github/workflows/ci.yml`. 여기 없는 규칙은 지어내지 않는다.

## Strategy 운영 발행 (AGENTS.md "Strategy production release policy")
- [ ] 정식 사이트 작성 워크플로의 `RATE_MONITOR_STRATEGY_DASHBOARD: "1"` 을 빼거나 바꾸지 않았다 — `.github/workflows/*`, `tests/test_strategy_production_release.py` 가 고정
- [ ] Strategy 발행 끄기·`strategy.html` 제거·Strategy 메뉴 항목 제거가 없다(있으면 사용자 명시 승인 근거가 있다) — 별개 동작 변경
- [ ] 옛 인수인계 글을 근거로 "Strategy 운영 발행이 꺼져 있다"고 적지 않았다 — 진실원은 저장소 워크플로·테스트
- [ ] PR 생성·머지를 런타임 검증으로 적지 않았다. Strategy 화면 변경이면 기존 운영 데이터/미리보기 브라우저 E2E 결과 또는 "미검증"을 적었다

## 금융·데이터 안전 (AGENTS.md "Financial/data safety")
- [ ] 예측 계수를 표시 정리 명목으로 바꾸지 않았다 — 과제가 명시하고 증거 게이트를 거친 경우만 허용
- [ ] 원천 우선순위(source precedence)를 바꾸지 않았다 — 같은 조건
- [ ] 상품 식별(stable product identity)·중복 제거/식별 규칙을 바꾸지 않았다 — 같은 조건
- [ ] 순위 모집단(ranking populations)을 바꾸지 않았다 — 같은 조건
- [ ] 저장 데이터 계약(DB 스키마·발행 파일 형식)을 표시 정리 명목으로 바꾸지 않았다 — `src/rate_monitor/db/`, alembic 마이그레이션

## 데이터 신뢰 (docs/data-trust.md)
- [ ] 관측의 원본 추적 칸(`raw_artifact_id`·`base_source_locator`·`source_record_hash`)이 비는 경로를 만들지 않았다 — §1.1, 빈 행이면 발행이 멈춰야 한다
- [ ] 못 읽은 값을 그럴듯한 값으로 채우지 않았다(예: 기본금리를 우대금리로 복사) — §1.2, 비우고 사유를 남긴다
- [ ] 발행 게이트(저장 검사·완료 게이트)를 약화·우회하지 않았다 — §1.3
- [ ] 원천이 차단 신호를 주면 우회하지 않고 멈추는 동작을 유지했다 — §2.6

## CI 계약 (.github/workflows/ci.yml)
- [ ] 테스트가 외부 네트워크·시크릿 없이 돈다 — ci.yml 머리말(원천 장애가 코드 검증을 막으면 안 된다)
- [ ] 모델을 바꿨으면 마이그레이션도 있다(빈 DB 에 `alembic upgrade head` 뒤 표 목록이 모델과 일치) — ci.yml 마이그레이션 단계
