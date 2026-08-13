# 전략 대시보드 데이터 연동 감사 — 2026-08-13

## 결론

전략 대시보드와 신상품 시뮬레이터는 별도 임의 데이터를 사용하지 않고 production R2에서 복원한 canonical `site-public/data/table.json`과 DB 관측 이력을 사용한다. KPI, TOP5, 가입기간별 시뮬레이터 순위, 시장평균·중앙값·TOP10 진입선, 고려저축은행 현재값이 같은 상품 대표 기준을 사용하도록 확인했다.

다만 **화면 계산의 일관성과 upstream 원천 금리의 정확성은 별개**다. FSB와 개별 저축은행 자체 공시가 충돌하는 사례가 있어 현재 canonical 전체를 무조건 정확하다고 판정하지 않는다. source reconciliation은 Issue #98에서 별도로 다룬다.

## Canonical 현재값 계약

- 전략 화면은 `site-public/data/table.json`을 읽는다.
- 저축은행 / 정기예금 / 선택 가입기간만 비교한다.
- `금융기관 + 상품 + 가입기간`을 대표상품 identity로 사용한다.
- 여러 variant가 있으면 가장 높은 `max_rate`를 대표값으로 사용한다.
- 동일 최고금리 variant가 여러 개면 더 최근 `source_effective_at`의 metadata를 표시한다.
- `max_rate IS NULL`을 `base_rate`로 대체하지 않는다.
- 제안 순위는 `1 + 제안금리보다 높은 대표상품 수`다.

## 2026-08-13 production R2 audit

Preview #21에서 production snapshot을 read-only로 복원했다.

- snapshot: `state/snapshots/20260813T123319-61fe7160.sqlite3.gz`
- DB size: 2,112,434,176 bytes
- `rate_observations`: 1,519,527
- `institutions`: 7,125
- `products`: 80,848
- `product_variants`: 329,309
- `collection_runs`: 76
- generated canonical table: 326,794 rows
- 12개월 전략 대표상품: 321
- 63일 historical chart points: 9
- 고려저축은행 historical points: 9/9

### 12개월 canonical audit 예시

1. 대백저축은행 애플정기예금 — base 4.10 / max 4.10 / `source=fsb` / effective 2026-08-12
2. 애큐온저축은행 처음만난예금(모바일전용) — base 4.00 / max 4.10 / `source=fsb` / effective 2026-08-03
3. 애큐온저축은행 다시만난예금(모바일전용) — base 3.70 / max 4.05 / `source=fsb` / effective 2026-08-03
4. 키움예스저축은행 SB톡톡 회전yes정기예금 — base/max 4.05 / `source=fsb` / effective 2026-08-10
5. 키움예스저축은행 e-회전yes정기예금 — base/max 4.05 / `source=fsb` / effective 2026-08-10

고려저축은행의 audit 대상 12개월 대표상품 6개는 모두 max 3.80%, `source=fsb`, effective 2026-08-11로 확인됐다.

## 지역 / 부산

전국 지도는 상품 대표 최고금리를 본점 `region`별 평균으로 표시한다.

부산 district가 있는 12개월 대표상품은 31개다.

- 동구 9
- 부산진구 10
- 연제구 12

지역 데이터는 저축은행 본점 소재지 참고값이며 지점 적용범위로 확장하지 않는다. district가 없는 구에 임의 금리를 만들지 않는다.

## 우대조건

우대조건 taxonomy 데이터는 별도 `우대조건 트렌드` 분석에서만 사용한다. 2026-08-13 audit에서 `preference_status=present`인 12개월 대표상품의 표준 태그 수 분포는 47상품이며 1개 37상품, 2개 10상품이었다.

사용자 검수 후 **신상품 시뮬레이터에서는 우대조건 수 입력과 조건 복잡도 benchmark를 제거했다.** 우대조건 개수가 금리순위를 변화시킨다는 검증된 인과관계가 없기 때문이다.

## Source discrepancy

대백저축은행 사례처럼 canonical FSB 값과 개별 금융사 자체 공시가 불일치하는 사례가 확인됐다. 화면에서 임의로 한 값을 overwrite하지 않는다.

후속 Issue #98에서 다음을 수행한다.

- FSB raw payload와 canonical row trace
- FSB ↔ 금융상품한눈에 ↔ 개별 금융사 공식 공시 cross-check
- effective date / 시행일 의미 검증
- source authority 및 freshness 규칙 정의
- discrepancy 자동 감지 신호 설계

## 검증 상태

Visual source `f86e3f4d490ab828d4d37e92b59cb9da0679d4ea` 기준 Preview #21은 R2 restore, migration, build, canonical audit, inline JavaScript `node --check`, generated preview branch publish가 모두 성공했다.

UI contract test head `ad6182074bfdf31ae65d1c820647978cfe247e1b`의 PR CI #884는 Ruff, **919 pytest**, empty DB migration, 15-table model parity가 모두 성공했다.

Generated preview commit은 `064f68672269852554e10dc6aae4092577ccb2c4`다. 다만 Vercel은 이 commit에 `Deployment rate limited — retry in 24 hours.`를 반환했으므로 기존 고정 Vercel Preview URL은 최신 UI browser evidence로 사용할 수 없다. GitHub generated artifact는 최신 visual source를 반영한 것으로 확인했다.
