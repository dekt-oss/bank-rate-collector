# R2 용량 실측과 저장소 정리 후보 (2026-10-16)

이 문서는 **조사 결과와 제안**이다. 이 문서와 함께 들어간 코드는 읽기 전용
조회(`rate-monitor storage inventory`, `Storage inventory (R2, read-only)`
워크플로우)뿐이고, R2 객체나 저장소 파일은 하나도 지우지 않았다.

## 1. 실측 (run 38909801780, 2026-10-16 22:42 KST)

`storage inventory`가 버킷 `bank-rate-collector-prod` 전체를 목록 조회해 센 값이다.

| 계열 | 크기 | 객체 수 | 기간(단위 수) | 단위당 평균 |
|---|---:|---:|---|---:|
| `checkpoints/v1/nh_local` | **13.4 GB** | 5,000 | 2026-08-12 ~ 10-15 (47일) | 284.7 MB/일 |
| `state/snapshots` | 2.9 GB | 7 | 10-15 ~ 10-16 | 개당 약 414 MB |
| `checkpoints/v1/kfcc` | 626.0 MB | 2,881 | 08-12 ~ 10-15 (43일) | 14.6 MB/일 |
| `raw-evidence/institution-funding` | 379.7 MB | 1,152 | 31회 실행 | 12.2 MB/회 |
| `raw-evidence/` 기타 4계열 (일회성 bootstrap) | 118.8 MB | 7,242 | 각 1회 | - |
| `checkpoints/v1/cu_disclosure_funding` | 2.6 MB | 158 | 08-29 하루 | - |
| `state/current.json`, `state/rollbacks/` | 1 KB 미만 | 2 | - | - |
| **합계** | **17.4 GB** | 16,442 | | |

**NH 체크포인트 하나가 전체의 77%다.** 스냅샷은 7개 보관 규칙대로 정확히 7개이고,
`intermediate/`는 비어 있다.

## 2. 왜 NH 체크포인트가 계속 쌓이나

1. NH·KFCC 수집은 도중에 끊겨도 이어받을 수 있도록 원본 응답을 묶음(tar.gz)으로
   R2에 저장한다 (`src/rate_monitor/services/resumable_acquisition.py`).
2. 삭제 판정 함수 `session_gc_eligible`는 만들어져 있지만, **운영 코드에서 부르는 곳이
   없다.** 테스트에서만 쓴다. 계획서(`docs/plans/20260811-resumable-acquisition-plan-v1.md`
   §11, "PR D observability / GC")에 있던 GC 단계가 구현되지 않았다.
3. 그 함수를 지금 그대로 연결해도 거의 지워지지 않는다. 성공한 세션은 `complete`
   상태로 끝나는데, 함수는 `complete`를 "아직 운영 DB 반영을 기다리는 중"으로 보고
   기간과 관계없이 보호한다. 운영 DB에 반영됐다는 표시(`mark_canonical_committed`)를
   남기는 코드도 운영 경로에는 없다 (`grep mark_canonical_committed src` 결과는 정의부뿐).

정리하면, 지우는 규칙이 반쯤 만들어진 채 멈춰 있고, 성공한 수집일수록 영원히 남는다.

## 3. 그대로 두면

하루 증가량은 NH 약 285 MB, KFCC 약 15 MB, 자금 원본 증거 약 12 MB를 합쳐 **약 310 MB**다.
한 달이면 약 9.3 GB가 늘어난다.

| 시점 | 예상 총량 | 예상 저장 요금 (월) |
|---|---:|---:|
| 지금 | 17.4 GB | 약 $0.11 |
| 6개월 뒤 | 약 73 GB | 약 $0.95 |
| 1년 뒤 | 약 129 GB | 약 $1.79 |

요금은 Cloudflare R2 Standard 기준이다. 무료 10 GB를 넘는 부분에 GB-월 $0.015가
붙는다. **당장 돈 문제는 아니다.** 문제는 상한이 없다는 것이다. NH 수집 범위가
넓어지거나 DB가 커지면 증가 속도도 따라 커진다. 또 오래된 체크포인트는 쓸 데가
없다. 이어받기는 같은 수집일(cycle date) 안에서만 하므로, 지난 날짜의 체크포인트는
복구에 쓰이지 않는다.

## 4. 보관 정책 제안 (미구현, 승인 필요)

| 계열 | 현재 | 제안 | 정상 상태 예상 |
|---|---|---|---:|
| `checkpoints/` | 영구 | 수집일 기준 7일 보관. 실패·중단 세션은 계획서대로 72시간 | 약 2.2 GB |
| `state/snapshots` | 최신 7개 | 유지. 하루 3~4개가 올라가 실제 되돌림 범위는 약 2일이다 | 약 2.9 GB |
| `raw-evidence/` | 영구 (설계) | 유지하되, 1년 뒤 다시 검토 | 연 약 4.4 GB 증가 |
| `intermediate/` | 30일 | 유지 | 0 |

체크포인트 정리를 적용하면 지금 기준으로 약 12 GB가 줄어 총량이 약 6 GB가 된다.
무료 구간 안으로 들어온다.

구현 방향 (별도 PR):

- **안 A.** 자금 수집 워크플로우가 이미 하는 것처럼, 수집 끝에 정리 단계를 둔다.
  `checkpoints/v1/<source>/<cycle_date>/`의 수집일이 오늘(KST)보다 7일 넘게 지났고
  현재 `state/current.json`의 스냅샷이 그 날짜보다 나중이면 지운다. 처음에는
  dry-run으로 후보 목록만 찍고, 확인한 뒤 실제로 지운다.
- **안 B.** 운영 DB 업로드(`storage upload`)가 성공한 직후 그 수집일 세션을
  `canonical_committed`로 표시하고, 기존 `session_gc_eligible`(7일)로 지운다.
  계획서 의도에 더 가깝지만, 건드리는 운영 워크플로우가 많다.

안 A를 추천한다. 날짜와 포인터만 보고 판단하므로 상태 기록이 빠진 과거 세션
47일치도 한 번에 정리된다.

결정이 필요한 점: **NH 원본 HTML을 감사·재처리용으로 오래 보관할 이유가 있는가.**
있다면 7일 대신 30일로 잡거나(체크포인트만 약 9 GB, 총량 약 13 GB), 월 1회 표본만 `raw-evidence/`로
옮기는 방법이 있다.

## 5. 저장소 정리 후보

판단 근거:

- 워크플로우 트리거 분석: `push` 대상 브랜치가 옛 기능 브랜치뿐인 것
- `tests/`에서 파일명이 참조되는지 여부
- 마지막 수정일 (`git log`, 2026-09-07은 저장소 히스토리가 시작된 날이라 "그 뒤로 손대지 않음"이라는 뜻)

**Strategy 관련 워크플로우(`strategy-*`)는 후보에서 뺐다.** AGENTS.md에 따라 Strategy
운영 경로를 건드리는 변경은 별도 판단이 필요하다.

### 5.1 일회성 검증·조사 워크플로우 (삭제 후보 33개)

전부 옛 기능 브랜치에 push될 때만 돈다. 그 브랜치들이 원격에 아직 남아 있지만
(원격 브랜치는 총 379개), 다시 push할 일이 없다면 이 워크플로우들은 쓰이지 않는다.
테스트에서 참조하는 것은 없다.

| 묶음 | 파일 |
|---|---|
| 자금 데이터 조사 (D0/D1) | `d0-market-funding-recon.yml`, `d1-institution-funding-actual-probe.yml`, `d1-institution-funding-recon.yml`, `cu-funding-producer-runtime-evidence.yml`¹ |
| 초기 조사 (P0/P2) | `p0-kfcc-capture.yml`, `p2-ecos-recon.yml` |
| 상대금리 R2 증거 | `relative-pricing-r2-funding-runtime-evidence.yml`, `relative-pricing-r2-product-scope-evidence.yml`, `relative-pricing-r2-product-url-evidence.yml`, `relative-pricing-strategy-runtime-e2e.yml`² |
| 검색 런타임 측정 | `search-d1-runtime.yml`, `search-phase3-runtime.yml`, `search-runtime-baseline.yml`, `search-performance-branch.yml` |
| 규모 비교군 증거 | `size-peer-common-vintage-evidence.yml`, `size-peer-cu-total-assets-evidence.yml`¹, `size-peer-cu-total-assets-persistence-gate.yml`¹, `size-peer-current-eligibility-evidence.yml`, `size-peer-total-assets-evidence.yml`, `size-peer-total-assets-persistence.yml`¹ |
| 출처 불일치 포렌식 | `source-discrepancy-7d-impact.yml`, `source-discrepancy-ambiguity-census.yml`, `source-discrepancy-ambiguity-taxonomy-forensic.yml`, `source-discrepancy-daishin-forensic.yml`, `source-discrepancy-dh-forensic.yml`, `source-discrepancy-official-evidence.yml` |
| 특판 단계별 증거 | `special-offer-canonical-readonly-evidence.yml`¹, `special-offer-r3c-official-evidence.yml`, `special-offer-r3d-catalog-isolation.yml`, `special-offer-r3e-writer-simulation.yml`, `special-offer-radar-runtime-evidence.yml`¹, `special-offer-registry-runtime-evidence.yml`¹ |
| 이력 압축 E2E | `rate-history-compaction-e2e.yml` |

¹ 운영 R2에 스냅샷을 올리는 단계(`storage upload`)가 있다. 돌면 운영 백업 7개 중
하나를 밀어내므로 우선 정리 대상이다.
² 이름에 strategy가 들어가지만 상대금리 r1d 브랜치 전용이다. Strategy 운영 경로와
무관한지 한 번 더 확인한 뒤 지운다.

**확인 후 결정:** `source-discrepancy-audit.yml`은 9월 30일에 수정됐고 해당 패턴의
브랜치가 18개 있어 아직 쓰는 중일 수 있다.

### 5.2 어디서도 참조하지 않는 스크립트 (삭제 후보 10개)

워크플로우, 테스트, `src` 어디에서도 파일명이 나오지 않는다.

`scripts/p0_finlife_test.py`, `scripts/p0_kfcc_probe.py`, `scripts/p1c_kfcc_census.py`,
`scripts/p1c_kfcc_rate_capture.py`, `scripts/p1d_cu_nh_recon.py`,
`scripts/p2_nh_local_recon.py`, `scripts/stage_g_mutual_max_rate_census.py`,
`scripts/validate_savings_bank_identity_reconciliation.py`,
`scripts/rate_funding_matrix_runtime_smoke.js`, `scripts/strategy_mobile_responsive_smoke.js`

5.1의 워크플로우를 지우면, 그 워크플로우만 쓰던 스크립트도 함께 지울 수 있다.
예를 들면 `scripts/d0_*`, `scripts/d1_*`, `scripts/search_*_runtime*.js` 같은 것들이다.

### 5.3 원격 브랜치

원격 브랜치가 379개다. 대부분 머지가 끝난 기능 브랜치로 보인다. 머지된 브랜치를
지우면 5.1의 워크플로우가 실수로 다시 돌 가능성도 사라진다. 브랜치 삭제는 되돌리기
어려우므로, 머지 여부를 확인한 목록을 따로 만든 뒤 진행한다.

## 6. 다시 재는 법

GitHub → Actions → **Storage inventory (R2, read-only)** → Run workflow.
결과는 실행 요약(Summary)과 `r2-inventory-<run_id>` 아티팩트(JSON)에 남는다.
읽기만 하므로 수집이 도는 중에도 실행해도 된다.
