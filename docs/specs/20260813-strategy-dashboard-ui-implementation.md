# 전략 대시보드 HTML 초안 구현 — 2026-08-13

## 목적

`docs/specs/20260812-strategy-dashboard-v1.md`의 병렬 실험 계약을 유지하면서,
앞서 정한 dark charcoal + off-white floating card 초안을 실제 전략 화면의
의사결정 흐름으로 구현한다.

## 이번 구현 범위

- 기존 `검색·조회` 화면과 전략 화면의 2메뉴 구조 유지
- 히어로 아래 `핵심 시장 브리핑` 3건 추가
  - 현재 시장 선두 최고금리
  - 최근 30일 최대 최고금리 변동
  - 현재 비교군의 상위 10% 진입 최고금리
- 기존 시장 KPI / 경쟁사 TOP 5 / 본점 소재지별 분포 유지
- 시장변화는 raw variant 건수가 아니라 상품 변경 이벤트 수로 표시
  - 동일 run + product + 이전 max_rate + 현재 max_rate는 1건
  - 영향받은 세부 관측 수는 별도 보조정보로 표시
- 신상품 시뮬레이터에 시장 포지션 게이지 추가
  - 시장 평균
  - 중앙값
  - 제안 최고금리
  - 비교상품과 제안금리를 모두 포함해 마커가 보이도록 잡은 표시 범위
- 예상 수신액은 기존과 동일하게 사용자 가정 기반 WHAT-IF로만 표시

## 데이터·운영 경계

- DB/schema/migration 변경 없음
- collector 변경 없음
- canonical `data/table.json` 재사용
- `rate_observations` 원본 이력 수정/삭제 없음
- 공식 release gate 기본 OFF 유지
- Preview에서만 전략 화면을 빌드하고 검토

## Acceptance

- 핵심 브리핑이 실제 비교상품과 변경이력에서 계산된다.
- 상위 10% 진입선은 현재 수집 범위의 고유 기관·상품 대표 최고금리에서 계산된다.
- 시장 포지션 게이지가 평균/중앙값/제안금리의 상대 위치를 표시한다.
- 제안금리가 시장 최저·최고 범위를 벗어나도 표시 범위를 확장해 제안 마커가 보인다.
- 시장 변화 피드에서 동일 상품 variant 동시 변경은 한 상품 이벤트로 보인다.
- 사용자 가정이 없으면 예상 수신액 숫자를 만들지 않는다.
- Preview 산출물의 인라인 JavaScript가 `node --check`를 통과한다.
- 전체 Ruff / pytest / empty DB migration CI가 통과한다.
- Preview 빌드가 canonical 운영 DB를 읽기만 하고 isolated preview branch를 갱신한다.
