# HANDOFF — 전략 대시보드 다음 개선 작업

작성일: 2026-08-18 KST  
Repository: `dekt-oss/bank-rate-collector`  
기준 branch: `main`  
기준 main SHA: `f4b61cf135fb199598924f658b24a555dc582156`

> 목적: 새 세션이 이전 대화를 전혀 모른다고 가정하고, 현재 Strategy Dashboard의 완료 상태를 GitHub 기준으로 복구한 뒤 **기초 데이터/엔진을 다시 건드리지 않고 다음 화면 개선 기획으로 바로 진입**하게 한다.

---

## 0. 새 세션 작업 방식

저장소 변경이 필요하면 `Chat-Development-Mode-v2.0-Universal`을 사용한다.
GitHub/Repository를 Source of Truth로 사용한다.

작업 시작 시 반드시 최신 `main`을 다시 확인하고 아래 순서로 복구한다.

1. repo root / `AGENTS.md` / `CLAUDE.md` / `README.md`
2. `docs/specs/CURRENT.md`
3. Issue #108 본문 **및 최신 comments**
4. 본 HANDOFF
5. 아래 Strategy 관련 기준 문서
6. 최신 Strategy code / tests / Preview workflow

Issue #108의 **본문은 초기 Stage B 시점 요구를 포함하므로 현재 상태 그 자체가 아니다. 최신 comments와 실제 main이 우선**이다.

자동 merge하지 않는다.  
Production Strategy Release Gate를 자동으로 켜지 않는다.

---

## 1. 현재 기준점

### latest main

`f4b61cf135fb199598924f658b24a555dc582156`

이 commit은 PR #129 `chore: 수동 수집 Actions UI 정리` squash merge 결과다.

PR #129 검증 head에서는:

- Ruff SUCCESS
- full pytest **1016 passed**
- empty DB migration SUCCESS
- DB model 15 tables 일치

PR Preview/Vercel은 코드 오류가 아니라 2026-08-18 당시 **Vercel free daily deployment limit 초과**로 제한되었다. 동일 오류가 보이면 application regression으로 오판하지 않는다.

### Strategy foundation 기준 merge

PR #126 `feat: 기존 수집데이터 기준 상호금융 최고금리 현실화`

- merge commit: `74e1c1f3719bc88f2552a3b974477544f3a1c403`
- 저축은행 + 신협 + 새마을금고 + 농·축협 Strategy 비교 기반 완료
- Production Strategy Release Gate는 계속 OFF

---

## 2. Strategy Dashboard에서 이미 끝난 것

아래 항목은 **다시 구현하거나 구조를 흔들지 않는다.**

### 2.1 4개 업권 Strategy 비교

Strategy가 현재 비교 가능한 sector:

- `savings_bank` — 저축은행
- `cu` — 신협
- `kfcc` — 새마을금고
- `nh_local` — 농·축협

UI에서 업권별/통합 비교가 가능하도록 foundation이 이미 들어가 있다.

### 2.2 금리 기준

사용자 요구인 “항상 최고금리”는 현재 다음의 안전한 의미로 구현되어 있다.

**`수집 데이터 기준 최고금리`**

정책:

1. source/collector에 `max_rate`가 있으면 우선 사용
2. NH target deposit은 동일 snapshot에서 e-joy 4구간이 정확히 연결될 때 `base_rate + e-joy add_rate`
3. 그 외 source max가 없는 경우 실제 수집된 `base_rate`
4. NH e-joy 가산행 자체는 상품 랭킹에서 제외
5. stable product + term + geography 관측 안에서 가장 높은 수집 확인값 사용
6. `strategy_rate_basis`로 provenance 보존

basis:

- `source_max_rate`
- `nh_ejoy_base_plus_add`
- `collected_base_rate`

**금지:** canonical `max_rate`가 없는 업권의 기본금리를 공식 우대 최고금리라고 표현하지 않는다.

### 2.3 Canonical/Strategy 분리

- 공개 `data/table.json`의 canonical `max_rate`는 Strategy 때문에 변경하지 않는다.
- Strategy는 파생 slice/파생값을 사용한다.
- collector / DB / schema / migration을 화면 개선 때문에 변경하지 않는다.
- `max_rate_capability`와 Strategy 비교 가능 여부는 별개다.

### 2.4 Stable product identity

상호금융 display-key ambiguity는 이미 stable `product_id` 직접 전달 방식으로 해결됐다.

이름 기반 fallback이나 institution/product entity merge를 새로 만들지 않는다.

### 2.5 지도/지역 의미

- 전국 지도는 대한민국으로 인식되는 실제 한국형 SVG로 교체된 상태다.
- 업권별 geography 의미가 다르다.
- KFCC 지도는 공시 소재지 의미다.
- NH는 점포 주소 의미다.
- 가입 가능 지역으로 임의 재해석하지 않는다.
- 부산 상세 drill-down은 현재 **저축은행 전용 경계**를 유지한다.

### 2.6 Issue #108 UX 요구 중 이미 구현된 것

다시 하지 않는다.

- 우대조건 `기타(OTHER)` 원문 drill-down
- 시장 인사이트를 지도/TOP5보다 선배치
- 전국 지도/TOP5 블록 밀도 축소
- 부산 drill-down 가독성 개선

Issue #108 초기 본문만 보고 이를 미완료로 판단하지 말 것.

---

## 3. 먼저 읽을 문서

현재 실제 code와 충돌하면 code/main + 최신 Issue/PR evidence가 우선이며, 오래된 문서 상태 문구를 그대로 작업지시로 사용하지 않는다.

필수:

- `docs/specs/CURRENT.md`
- `docs/specs/20260812-strategy-dashboard-v1.md`
- `docs/specs/20260816-strategy-dashboard-v2-workorder.md`
- `docs/specs/20260817-strategy-dashboard-issue108-ux.md`
- `docs/specs/20260817-strategy-stable-product-id.md`
- `docs/specs/20260817-strategy-mutual-finance-evidence.md`
- `docs/specs/20260817-mutual-finance-max-rate-stage-f-evidence.md`
- `docs/specs/20260817-mutual-finance-stage-g-entry-census.md`
- `docs/specs/20260814-strategy-engine-data-contract.md`

핵심 history:

- PR #100 / #102: 지도/데이터 엔진/부산 drill-down 안정화
- PR #113: Issue #108 UX 1·2
- PR #115: stable product identity
- PR #122: 상호금융 census
- PR #123: 향후 NH e-joy derived max 수집 경로
- PR #124: NH Strategy capability 초기 gate
- PR #126: 기존 수집데이터 기준 4업권 Strategy 현실화

---

## 4. 다음 작업의 성격

**기본 세팅은 끝났다. 다음은 foundation 보수 작업이 아니라 새 UI/업무 흐름 기획 단계다.**

새 세션은 바로 코드를 고치기보다 먼저 현재 Preview를 실제 렌더링해 정보 구조를 감사하고, 다음 개선판을 새 작업명세로 정의한다.

### 목표 사용자

저축은행 실무자가 경쟁사 수신금리를 조사하고 신규 수신상품을 기획하는 업무 화면이다.

따라서 단순 데이터 시각화보다 다음 질문에 빠르게 답할 수 있어야 한다.

- 오늘 경쟁사 중 누가 금리를 움직였는가?
- 당사 금리는 시장에서 몇 번째/어느 구간인가?
- 어느 업권·지역·기간에서 금리 gap이 큰가?
- 우대조건은 시장에서 어떤 방향으로 바뀌고 있는가?
- 신규상품 금리를 X%로 놓으면 경쟁 위치와 예상 수신 영향은 어떻게 바뀌는가?
- 지금 실무자가 실제로 취해야 할 액션은 무엇인가?

---

## 5. 다음 화면 개선 기획 권장 순서

### A. 현재 화면 실렌더링 감사

먼저 desktop 1280/1440 + mobile 390에서 현재 Strategy를 보고 아래를 기록한다.

- 첫 화면에서 가장 먼저 보이는 정보
- 사용자가 행동 결정을 내리기까지 필요한 스크롤/클릭 수
- KPI / 인사이트 / 지도 / TOP5 / 우대조건 / 시뮬레이터의 우선순위
- 중복 정보
- 너무 큰 카드/너무 작은 텍스트
- 업권 selector와 기간 selector의 이해 가능성
- 지도와 TOP5가 실제 업무 의사결정에 차지하는 비중

Vercel quota 때문에 Preview가 막히면 production Release Gate를 켜지 말고, 기존 isolated Strategy Preview workflow 또는 로컬/site artifact 기반 검증 경로를 사용한다.

### B. 정보 구조를 “의사결정 cockpit” 중심으로 재기획

권장 우선순위:

1. **오늘의 시장 변화 / 핵심 인사이트**
2. **당사 경쟁 포지션**
3. **경쟁사 금리 움직임 / 상품 gap**
4. **우대조건 트렌드**
5. **신상품/금리 시뮬레이션**
6. 지도 / TOP5는 보조 탐색

지도와 순위표가 화면의 주인공이 되지 않게 한다.

### C. 다음 신규 기능 후보

아래는 새 기획 후보이며, 한 PR에 모두 넣지 않는다.

- 경쟁사 금리 변동 감지/최근 변경 강조
- 당사 대비 `+/- bp` gap 랭킹
- 기간별 시장 구간(percentile/band)과 당사 위치
- “신규상품 기회” 후보: 시장 gap + 우대조건 + 지역/업권 조합
- 경쟁사 상품별 최근 움직임 타임라인
- 우대조건 변화/신규 조건 등장
- 신상품 금리 시뮬레이터의 전략 해석 문구 강화
- 인사이트 카드에서 근거 row/drill-down 연결

금융 계산/예측 수식 변경은 UI PR과 분리하고 Evidence Gate를 적용한다.

---

## 6. 디자인 방향

다음 UI 작업 시 유지할 사용자 선호:

- 동적이고 현대적인 화면
- 과도한 메뉴 구조는 불필요
- 부드럽고 고급스러운 색감
- 약한 depth / floating / 3D 감각
- 쨍한 원색 파랑 지양
- 정보 밀도는 높되 카드 수만 늘리지 않음
- 핵심 업무 인사이트가 첫 화면에 보이도록

디자인을 크게 바꾸기 전에는 실제 HTML/Preview 시안으로 먼저 비교하는 편이 좋다.

---

## 7. 절대 보존할 경계

다음 작업에서 특별한 Evidence/계약 변경 없이 건드리지 않는다.

- canonical source precedence
- stable product identity
- `strategy_rate_basis`
- NH e-joy fail-closed linkage
- 부산 drill-down의 현재 데이터 경계
- sector별 geography semantics
- canonical `data/table.json` 계약
- collector / DB / schema / migration
- shared `rate-data-writer` 직렬 writer 계약
- Production Strategy Release Gate OFF

PR merge와 Release Gate ON은 별도 승인이다.

---

## 8. 현재 운영 이슈 — Strategy와 분리

2026-08-18 NH 정기수집 누락 원인은 source parser가 아니라 GitHub Actions concurrency pending 교체 문제였다.

PR #127에서 shared writer workflow에 `queue: max`를 넣어 pending 보존하도록 수정했고 main에 merge됐다.

오늘 누락된 NH 복구를 위해 temporary PR #128에서 recovery run을 실행했다.

Handoff 작성 시점 상태:

- recovery run: `32097241927`
- `attempt_1 / attempt`: 실행 중
- `Probe NH network path`: SUCCESS
- DB restore/migration: SUCCESS
- `Collect NH local`: **IN PROGRESS**

이 작업은 Strategy foundation과 별개다.

새 세션에서 Strategy 작업을 시작할 때:

- PR #128을 작업 base로 사용하지 않는다.
- 먼저 recovery run이 성공/실패했는지만 확인한다.
- 성공 시 rate-data publish/freshness 정상화를 확인하고 temporary PR #128 정리 여부를 판단한다.
- NH freshness 문제를 이유로 Strategy 금리 엔진을 다시 설계하지 않는다.

---

## 9. 수동 Actions UI 최신 상태

PR #129 merge 후 workflow 이름:

- `수집 — 일반·새마을금고`
- `수집 — 농·축협`

일반 수동 실행은 skip 체크박스 조합 대신 positive preset 방식이다.

- 일반 전체
- 저축은행만
- 신협만
- 새마을금고만
- 참고지표만
- 화면만 재발행

NH 수동 실행 기본:

- 범위 `전국`
- resume `auto`
- volume drop 강제 승인 OFF

Strategy 작업에서 이 workflow UI를 다시 리팩터링할 필요 없다.

---

## 10. 검증 원칙

다음 Strategy UI PR은 최소 아래를 수행한다.

- full pytest
- lint
- build
- Strategy-specific tests
- gate OFF regression
- production-backed read-only Preview 가능 시 수행
- desktop 1280/1440 + mobile 390 browser smoke
- pageerror / console error / horizontal overflow 확인
- 주요 selector/드ill-down 실제 클릭
- 수치 변경이 있다면 변경 전/후 동일 snapshot 비교

**PR 생성/merge 자체를 기능 검증으로 간주하지 않는다.**

Vercel `api-deployments-free-per-day`는 infra quota로 별도 표기한다.

---

## 11. 새 세션에서 가장 먼저 할 일

1. 최신 `main` SHA 확인 — 이 문서의 `f4b61cf...`보다 새 commit이 있으면 새 상태를 우선
2. Issue #108 최신 comments 확인
3. PR #128 / NH recovery run 최종 상태 확인
4. 현재 Strategy Preview/산출 HTML 실렌더링
5. **current state / UX 문제 / target state를 먼저 정리**
6. 다음 화면 개선안을 1~3개 Stage로 분해
7. 사용자에게 화면 우선순위/시안 제시
8. 승인된 최소 Stage부터 새 PR

---

## 12. 새 세션 시작용 프롬프트

아래를 그대로 새 세션에 전달해도 된다.

```text
`dekt-oss/bank-rate-collector` 최신 main에서 전략 대시보드 다음 화면 개선 작업을 이어서 진행한다.

이 세션은 이전 대화를 모른다고 가정하고 GitHub를 Source of Truth로 복구한다.
저장소 변경은 Chat Development Mode를 사용한다.

먼저 아래를 읽는다.
- AGENTS.md / CLAUDE.md / README.md
- docs/specs/CURRENT.md
- Issue #108 최신 comments
- docs/handoffs/20260818-strategy-dashboard-next-session.md
- 문서가 참조하는 Strategy 관련 최신 spec

중요:
- 기본 Strategy foundation은 완료된 상태다.
- 4업권(저축은행/신협/새마을금고/농축협) 비교와 `수집 데이터 기준 최고금리`, stable product identity, NH e-joy linkage, 지도/부산 drill-down을 다시 구현하지 않는다.
- collector/DB/schema/migration을 UI 개선 때문에 건드리지 않는다.
- Production Strategy Release Gate를 켜지 않는다.
- 자동 merge하지 않는다.

첫 작업은 현재 Strategy 화면을 실제 렌더링해 UX/정보구조를 감사하고,
경쟁사 금리 조사 및 신규 수신상품 기획 업무에 더 직접적인 ‘의사결정 cockpit’ 형태의 다음 개선안을 제안하는 것이다.

코드부터 수정하지 말고 current state → 문제 → target state → Stage/PR 범위를 먼저 정리해서 보여줘.
```
