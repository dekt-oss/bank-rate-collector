# 전략 대시보드 다음 개선판 — 작업 명세 (v2 work order)

```yaml
document_type: work_order
status: draft
created_at: 2026-08-16
target_repository: dekt-oss/bank-rate-collector
base_branch: feat/strategy-dashboard-korea-map
base_commit: 89813732c7e27f45bf51de2fc971a8ecd7151e93
inherits_product_contract: docs/specs/20260812-strategy-dashboard-v1.md
inherits_engine_contract: docs/specs/20260816-inflow-prediction-v1.md
review_basis: 2026-08-16 설계 리뷰 (Preview 실렌더링 + 소스 정독 + 실측)
```

## 0. 이 문서의 지위

- 이 문서는 전략 대시보드 다음 개선판 작업의 **단일 진실원**이다. 작업
  에이전트는 이 문서와 여기서 참조하는 기준 문서만 근거로 작업한다.
- §5 인터페이스 계약(FREEZE)은 작업 에이전트가 바꾸지 않는다. 계약 변경이
  필요해지면 **코드로 우회하지 말고 작업을 멈추고 발주자에게 에스컬레이션**한다.
- 저장소 공통 규칙을 그대로 상속한다.
  - 계약 변경은 문서를 먼저 고치고 구현한다 (`CURRENT.md` 규칙).
  - DB / schema / migration / collector 는 변경하지 않는다.
  - `max_rate IS NULL`을 기본금리로 대체하지 않는다.
  - production Release Gate(`RATE_MONITOR_STRATEGY_DASHBOARD`)는 켜지 않는다.
  - 기본(OFF) 빌드는 전략 산출물을 만들지 않고, stale 산출물을 삭제한다.
- 각 단계는 **독립 PR**이며 명시된 순서를 지킨다. 이전 단계가 merge되기 전에
  다음 단계 코드를 시작하지 않는다.

## 1. 배경 — 2026-08-16 설계 리뷰 실측 요약

Preview(현 base_commit 빌드)를 실제 렌더링하고 실측한 결과다. 아래 수치는
재검증 없이 인용해도 된다.

| 항목 | 실측값 |
|---|---|
| `data/table.json` | 326,755행 / 26.2MB (전송 3.9MB brotli) |
| 그중 전략 universe(저축은행·정기예금·6/12/24/36개월) | 1,878행 (0.57%) |
| 시뮬레이터 입력 이벤트 1회당 재계산 비용 | 9.1ms (데스크톱 Chromium, 저사양 기기는 수십 ms 예상) |
| 템플릿 가공 | 문자열 치환 어댑터 4층 (contract → inflow → refinement → korea map) |
| Python/JS 예측엔진 수치 일치 테스트 | 없음 (문자열 존재 grep만 존재) |
| 부산 drill-down | TOP5 칸 420px vs 테이블 min-width 560px → 금리 열 잘림 |
| CURRENT.md | 20260816 스펙 2종 미등재 (저장소 규칙 위반 상태) |

## 2. 목적 (한 줄)

전략 대시보드를 다음 기능을 얹을 수 있는 구조로 정리(어댑터 베이크·경량
페이로드·엔진 검증)하고, 리뷰에서 확인된 UX 결함을 해소한다.

## 3. 단계 계획 — PR 5개, 이 순서대로

```text
Stage A  어댑터 베이크 + 문서 정리        (구조, 기능 변화 없음)
Stage B  전략 전용 데이터 slice           (성능, 문서 먼저 수정)
Stage C  예측엔진 Python/JS parity 테스트  (검증)
Stage D  부산 drill-down 가독성            (UX)
Stage E  기획 흐름 UX + 표현 정리          (UX/표현)
```

브랜치 이름: `feat/strategy-dashboard-v2-<stage>` (예: `-bake`, `-slice`,
`-parity`, `-busan`, `-ux`). PR base는 `feat/strategy-dashboard-korea-map`
(PR #103이 먼저 merge되면 `main`).

## 4. 단계별 상세

### Stage A — 어댑터 베이크 + 문서 정리

현재 `web/templates/strategy.html`은 최종 화면과 다르다(폐기된 구식 계산기,
임시 실루엣 지도 보유). 실제 화면은 빌드 시 4층 문자열 치환으로 만들어지며,
뒷단 marker가 앞단이 삽입한 문자열에 의존한다
(`strategy_refinement_service.py`의 `PREDICT v1` marker는
`strategy_contract_service.py`가 삽입한 것).

태스크:

- [ ] 현 어댑터 체인(`adapt_strategy_template` → 내부 UI 어댑터들 →
      `adapt_strategy_korea_map_template`)을 현재 템플릿에 적용한 결과 문자열을
      **새 `web/templates/strategy.html`로 저장**한다(베이크). 산출 HTML은
      바이트 단위로 기존 빌드 결과와 동일해야 한다.
- [ ] UI 어댑터 층 삭제: `strategy_refinement_service.py` 전체,
      `strategy_contract_service.py`의 `_adapt_inflow_prediction` 및
      템플릿 표현 치환부, `site_service.py`의
      `adapt_strategy_korea_map_template`과 관련 상수.
- [ ] **데이터 계약 어댑터는 유지**: `augment_strategy_table`(product_id 증강)과
      빌드 실패 검증(`DashboardBuildError`)은 남긴다.
- [ ] 예측엔진 설정의 원본은 Python(`public_model_config()`)이 유지되도록,
      베이크된 템플릿의 JS는 `data.strategy?.inflow_prediction`을 1순위로 읽는
      현 구조를 그대로 보존한다(템플릿에 남는 fallback 리터럴은 비상용).
- [ ] 어댑터 동작을 검사하던 테스트
      (`test_strategy_dashboard_refinement.py`,
      `test_strategy_dashboard_ui_contract.py`, `test_strategy_map_presentation.py`,
      `test_strategy_busan_focus.py`)를 **빌드 산출 HTML 검사로 전환**한다.
      검사 항목(문구·id·CSS 계약)은 줄이지 않는다.
- [ ] `docs/specs/CURRENT.md` 문서 목록에 `20260816-inflow-prediction-v1.md`,
      `20260816-inflow-prediction-v1-evidence.md`, 본 문서를 등재한다.

DoD:

- [ ] gate ON 빌드 산출 `strategy.html`이 베이크 전과 동일하다
      (`diff` 통과 증거를 PR에 첨부).
- [ ] gate OFF 빌드는 이전과 동일하게 전략 산출물을 만들지 않고 stale을 지운다.
- [ ] 전체 pytest, Strategy Preview workflow 통과.

### Stage B — 전략 전용 데이터 slice

**문서 먼저**: `20260812-strategy-dashboard-v1.md` §11의 "두 HTML은 같은
`data/table.json`을 사용한다"를 "전략 화면은 같은 canonical 빌드에서 파생된
전략 전용 slice를 사용한다"로 개정하는 커밋을 같은 PR 맨 앞에 둔다.

태스크:

- [ ] `build_site`가 gate ON일 때 `data/strategy-table.json`을 추가 발행한다.
      내용은 §5.1 계약을 따른다. 별도 수집/DB 접근 없이 기존 table 데이터의
      필터일 뿐이다.
- [ ] `strategy.html`의 `table_url`을 slice로 바꾼다. `index.html`은 그대로
      `data/table.json`을 쓴다.
- [ ] gate OFF 빌드는 stale `data/strategy-table.json`도 삭제한다.
- [ ] 클라이언트: 로드 시 1회 `expand()` 후 기간(6/12/24/36)별
      `aggregateProducts` 결과를 캐시하고, 입력 이벤트에서는 캐시를 쓴다.
      (slice로 행수가 ~1.9천이 되므로 필수는 아니나, 이벤트당 전체 스캔 제거가
      목적이다.)

DoD:

- [ ] 전략 화면 네트워크 전송량이 기존 대비 1/10 이하 (Preview에서 실측치 첨부).
- [ ] 전략 화면의 KPI/TOP5/지도/우대조건/시뮬 수치가 slice 전과 동일하다
      (동일 DB 스냅샷으로 전·후 빌드 비교).
- [ ] `index.html` 빌드 산출물은 바이트 동일.

### Stage C — 예측엔진 Python/JS parity 테스트

`20260816-inflow-prediction-v1.md` §12 검증기준 1번("Python 엔진과 UI가 동일한
계약")을 실제 수치로 검증한다. 현재는 같은 수식이 Python
(`inflow_prediction_service.py`)과 JS(베이크 후 템플릿 내)에 두 번 손으로
쓰여 있고 드리프트를 잡을 장치가 없다.

태스크:

- [ ] §5.2 계약의 golden vector 파일을 추가한다.
- [ ] pytest: 각 벡터를 `predict_range`로 계산해 기대값과 비교한다.
- [ ] JS 검증: 빌드 산출 HTML에서 `logistic` / `runInflowScenario` /
      `predictInflow` 함수 소스를 추출해 node로 실행하고, 같은 벡터에 대해
      Python 결과와 비교한다(허용 오차 §5.2). CI에 node가 있는 runner를 쓴다.
- [ ] 함수 추출이 실패하면(마커 부재) 테스트가 실패해야 한다. 조용히 skip 금지.

DoD:

- [ ] 계수·guardrail·수식 어느 한쪽만 바뀌면 CI가 빨간불이 된다
      (일부러 한쪽을 바꿔 실패를 확인한 증거를 PR에 첨부).

### Stage D — 부산 drill-down 가독성

태스크:

- [ ] 부산 focus에서 TOP5 금리 열 잘림 해소. 방법은 다음 중 하나:
      (a) 부산 모드에서 TOP5를 축약 열(순위·기관·최고금리)로 전환,
      (b) 테이블 min-width 해제 + 열폭 재조정. 가로 스크롤로 방치하지 않는다.
- [ ] 부산 중심부 라벨 겹침(부산진·연제·수영·동·중·서구) 해소. 전국 지도의
      `koreaLabelOffsets`와 같은 preset 오프셋 방식을 부산에 적용한다.
      geometry·데이터 좌표는 변경하지 않는다(표시 위치만).
- [ ] 데이터 있는 구가 3/16개인 현실을 보완: 지도 옆 또는 아래에 구별
      금리 리스트(데이터 있는 구만)를 병기한다.

DoD:

- [ ] 1280px·1440px 데스크톱과 390px 모바일에서 부산 모드 스크린샷 첨부,
      금리 열·구 라벨이 모두 판독 가능.
- [ ] 전국 모드 산출물은 회귀 없음(기존 계약 테스트 유지).

### Stage E — 기획 흐름 UX + 표현 정리

태스크:

- [ ] 시뮬레이터 기본값을 당사 현재 대표 최고금리로 초기화한다
      (당사 상품이 없으면 현 기본값 유지).
- [ ] 예측엔진 접힘 상태에서도 한 줄 요약을 상시 노출한다
      (예: "내부 실적 미보정 · 신규수신·만기·재예치율 3개 입력으로 총수신 범위 계산").
- [ ] KPI 4카드에 "12개월" 기준 라벨을 명시하고, 시뮬 기간을 6/24/36으로
      바꿨을 때 상단 KPI와 planning strip이 다른 기간임이 화면에서 드러나게 한다.
      (KPI를 기간 연동으로 바꾸는 것은 이번 범위 아님 — §7 열린 질문.)
- [ ] 트렌드 요약 "시장 최고 변화"에 비교상품 수 변화를 병기해 outlier 이탈이
      시장 하락처럼 읽히지 않게 한다.
- [ ] "기간별 금리 추이" 카드 제목을 실체에 맞게 조정한다
      (기간별 현재 평균 strip + 12개월 시계열 차트의 혼합 카드임을 반영).
- [ ] 본문 최소 폰트를 9px 이상으로 올린다(7.x~8.x px 사용처 정리).

DoD:

- [ ] 변경 전·후 스크린샷 비교 첨부.
- [ ] 기존 계약 문구 테스트 통과(문구를 바꾼 경우 테스트를 같은 PR에서 갱신).

## 5. 인터페이스 계약 (FREEZE — 작업 에이전트 변경 금지)

### 5.1 `data/strategy-table.json`

- 인코딩: 기존 `table.json`과 동일한 `{columns, lookups, rows}` 압축 형식.
- 열 구성: 기존 table 열 전체 + `product_id` (기존 `augment_strategy_table`
  결과와 동일).
- 행 필터: `sector = savings_bank` AND `product_type = term_deposit` AND
  `term_months ∈ {6, 12, 24, 36}`. 그 외 어떤 행도 넣지 않는다.
- 원자료 수정 금지: 필터만 하고 값 변환·집계·정렬 변경을 하지 않는다.
- gate ON 빌드에서만 존재. OFF 빌드는 생성하지 않고 stale을 삭제한다.

### 5.2 예측엔진 golden vector

- 위치: `tests/data/inflow_parity_vectors.json`.
- 형식: `{"vectors": [{"name": str, "inputs": {baseline_new_money,
  maturity_amount, current_rollover_rate_pct, current_own_rate, proposed_rate,
  market_top10_rate, term_months}}, ...]}`.
- 최소 케이스: 0bp 변화, 재예치율 0%·100% + 0bp, ±10bp, 금리 인하,
  극단 rate-step(log-effect clamp 발동), 6/12/36개월 기간.
- 비교 대상: 시나리오별 `predicted_new_money`, `predicted_rollover_rate_pct`,
  `predicted_total`, `surface_interest_delta` 및 `predicted_total_range`.
- 허용 오차: 상대 1e-9 (Python 반올림 전 값 기준. JS쪽은 표시용 반올림 전
  원값으로 비교한다).
- 계수·수식의 원본은 `inflow_prediction_service.py`다. JS를 Python에 맞춘다.
  반대 방향 수정 금지.

### 5.3 파일 경계

| 경로 | 이번 작업에서 |
|---|---|
| `web/templates/strategy.html` | 수정 대상 (Stage A 이후 단일 진실원) |
| `src/rate_monitor/services/site_service.py` | 수정 대상 (빌드/발행) |
| `src/rate_monitor/services/strategy_contract_service.py` | 수정 대상 (데이터 계약만 남김) |
| `src/rate_monitor/services/strategy_refinement_service.py` | Stage A에서 삭제 |
| `src/rate_monitor/services/inflow_prediction_service.py` | **읽기 전용** (계수·수식 변경 금지) |
| `src/rate_monitor/services/strategy_service.py` | 읽기 전용 (필요 시 에스컬레이션) |
| `web/templates/site.html`, `index.html` 계약 | **변경 금지** |
| `src/rate_monitor/collectors/**`, `migrations/**`, DB schema | **변경 금지** |
| `config/**` | 변경 금지 |
| `.github/workflows/strategy-preview.yml` | 검증 grep 갱신만 허용 (경로·권한·publish 대상 변경 금지) |
| `docs/specs/*` | 이 문서가 지시한 개정만 |

## 6. 공통 검증 절차 (모든 PR)

1. `uv run pytest` 전체 통과.
2. `uv run ruff check` 통과.
3. gate OFF 빌드: `strategy.html`·전략 asset·slice가 생성되지 않고 stale이
   삭제됨을 확인.
4. gate ON 빌드: Strategy Preview workflow 성공 + Preview URL에서 실화면 확인
   (전국 → 부산 → 복귀, 시뮬 기간 전환, 예측엔진 입력까지).
5. PR 본문에 증거 첨부: 테스트 결과 수치, 빌드 diff 또는 스크린샷.

## 7. 리스크 / 열린 질문 (발주자 확인 필요)

- PR #103 merge 시점: Stage A를 #103 merge 후 `main` 기준으로 시작할지,
  현 브랜치에 stack할지. **권장: #103을 먼저 merge하고 main 기준으로 진행.**
- KPI 4카드를 시뮬 기간과 연동할지(12개월 고정 유지 + 라벨 명시가 이번 범위).
- 시장 최고/평균/TOP10 3곳 중복 표기의 최종 배치(이번 범위는 라벨 명시까지).
- Stage B에서 `index.html`용 `table.json` 자체의 경량화는 다루지 않는다
  (별도 과제).
