# 금리모니터 제작 명세서 v3.1 — GitHub Actions 실행형

```
status: current
supersedes: 20260805-rate-monitor-v3.md
effective_from: P1
```

- 프로젝트명: `rate-monitor`
- 작성일: 2026-08-05
- 관련 문서: `docs/specs/CURRENT.md`, `docs/plans/20260805-rate-monitor-plan-v3.md`
- 1차 목표: 부산 16개 구·군의 저축은행·새마을금고·신협·지역농축협 수신금리를 통합 조회·편집·내보내기

---

## 0. v3.1이 존재하는 이유

P0 정찰이 v3의 두 전제를 무너뜨렸다.

**첫째, finlife는 부산 구 단위를 줄 수 없다.** 2026-08-05 실행 검증 결과 상품 API(`depositProductsSearch`, `savingProductsSearch`)의 `baseList`·`optionList`에 지역 필드가 없고(`product_api_has_region_field: false`), 지역 정보는 `companySearch`의 시도 단위 점포 유무 플래그뿐이다(`company_api_area_granularity: "시도"`). 근거: `docs/source-recon/finlife.md` §5.

**둘째, 실행 위치가 GitHub Actions로 확정됐다.** v3 §2·§12·§13이 전제한 로컬 FastAPI(`python app.py` → `127.0.0.1:8000`)는 이 운영 형태에서 아무도 열어볼 수 없는 코드가 된다.

v3의 도메인 모델과 데이터 계약은 옳다. 실행 모델만 바꾼다.

---

## 1. v3에서 변경되는 항목

| 항목 | v3 | v3.1 |
|---|---|---|
| 실행 모델 | 로컬 `python app.py` → `127.0.0.1:8000` | GitHub Actions 실행 + 정적 산출물 |
| §2 스택 | FastAPI, uvicorn, Jinja2 + HTMX + Tabulator, openpyxl | 제거. CLI + 빌더 스크립트 (§9) |
| §12 웹 API | FastAPI 라우트 6종 | **후순위 강등.** P1·P2 범위 밖 |
| §13 웹 화면 | Jinja2 서버 렌더링 + 인라인 편집 | 정적 HTML 생성 (§6). 편집은 P2.5에서 재설계 |
| §16.4 CLI | `rate-monitor serve` 포함 | `collect` / `build-dashboard` / `validate` (§9) |
| DB 파일 | `data/rate_monitor.sqlite3` 단일 | `work/` 작업본 + `publish/` 스냅샷 (§3) |
| 원본 보존 | "최소 1년", 위치 미지정 | Actions Artifact (§4) |

## 2. v3에서 그대로 승계하는 계약

아래 절은 **v3 원문을 그대로 승계한다.** 실행 위치와 무관하며, 이 프로젝트의 실제 가치다.

| 승계 대상 | v3 위치 |
|---|---|
| 도메인 열거형 (`Sector`, `ProductType`, `JoinChannel`, `InterestMethod`, `AvailabilityScope`, `RateScope`, `CollectionMode`, `SourceRole`, `TrustLevel`, `RunStatus`, `ValidationStatus`) | §4 |
| DB 스키마 13종 | §5 (단, `rate_observations`는 §7에서 컬럼 추가) |
| 수집기 인터페이스 (`CollectionRequest`, `RawArtifactData`, `SourceAdapter`) | §6.1 (단, `ParsedRateRow`는 §7에서 필드 추가) |
| 클린룸 재구현 원칙 | §6.3 |
| 예외 5종 | §6.4 |
| 소스별 명세 | §7 전체 |
| 정규화 계약 | §8 |
| 우대조건 파서 | §9 |
| 수집 오케스트레이션 순서·트랜잭션·재시도 | §10 |
| 유효 데이터와 오버라이드 병합 | §11 |
| 엑셀 명세 | §14 |
| 보안 | §16.1 |
| 테스트 명세 | §17 |
| 착수 전 필수 산출물 | §22 |

승계 계약을 바꾸려면 이 문서를 먼저 고친다. 코드로 우회하지 않는다.

---

## 3. SQLite 일관성 계약 (신규)

작업 중인 DB를 그대로 `git add` 하지 않는다. WAL 모드에서는 커밋 시점의 파일이 불완전할 수 있고, `-wal`/`-shm` 파일이 분리돼 있으면 복원이 깨진다.

```
work/rate_monitor.sqlite3       # 실행 중 작업용. 커밋하지 않는다
publish/rate_monitor.sqlite3    # 일관된 배포용 스냅샷
```

### 3.1 스냅샷 절차

순서를 지킨다. 트랜잭션이 열린 상태에서 파일을 복사하면 안 된다.

```
1. 모든 트랜잭션 종료 (commit / close)
2. sqlite3.Connection.backup() 또는 VACUUM INTO → publish/rate_monitor.sqlite3
3. PRAGMA integrity_check      → 'ok' 아니면 실행 실패 처리
4. PRAGMA foreign_key_check    → 결과 0건 아니면 실행 실패 처리
5. SHA256 계산
6. manifest.json 기록
7. 커밋
```

3·4 단계가 통과하지 못하면 스냅샷을 배포하지 않는다. 이전 배포본을 유지한다.

### 3.2 커밋 금지 대상

```
work/
*.sqlite3-wal
*.sqlite3-shm
```

### 3.3 `manifest.json`

```json
{
  "generated_at": "ISO8601 UTC",
  "run_id": "…",
  "sqlite_sha256": "…",
  "sqlite_bytes": 0,
  "integrity_check": "ok",
  "foreign_key_check_violations": 0,
  "row_counts": { "institutions": 0, "products": 0, "product_variants": 0, "rate_observations": 0 }
}
```

`row_counts`는 배포 후 SQL `COUNT`와 대조해 일치해야 한다 (§12 게이트).

---

## 4. 산출물 저장 범위와 보존 정책 (신규)

`rate-data` 브랜치는 **최신 사용 가능 산출물 전달용**이다. raw 원본 장기보존소로 쓰지 않는다.

```
rate-data 브랜치
├─ latest/
│  ├─ rate_monitor.sqlite3.gz
│  ├─ manifest.json
│  └─ summary.json
└─ site/
   └─ index.html
```

원본 JSON과 실행 로그는 Actions Artifact로 보존한다.

```
Actions Artifact
├─ raw/
├─ validation/
└─ collection-report.json
```

보존기간은 처음 `retention-days: 400`으로 설정했으나 저장소 상한에 걸렸다.

> **실측 기록 (2026-08-05, run 30987518893)**
> ```
> Retention days cannot be greater than the maximum allowed retention
> set within the repository. Using 90 instead.
> ```
> 이 저장소의 Artifact 보존 상한은 **90일**이다. 워크플로우에 90을 명시해
> 기대와 실제가 어긋나지 않게 했다.
>
> 명세서 v3 §16.2는 "수집 원본 최소 1년 보존"을 요구한다. Artifact만으로는
> 이를 충족하지 못한다. **미해소 항목** — 1년 보존이 필요하면 별도 보관소
> (저장소 설정 상향, 외부 스토리지, 또는 rate-data 브랜치에 원본 일부 포함)를
> 결정해야 한다.

`main`은 코드와 문서만 유지한다. DB·원본·생성 산출물을 `main`에 커밋하지 않는다.

---

## 5. 게시 방식 (신규)

Git 브랜치와 Actions Artifact는 정적 사이트 호스팅이 아니다. 이 저장소는 private이므로 Pages 공개 범위가 확정되지 않았다.

**기본 경로 (P1-A 필수):** 생성된 `site/index.html`을 Artifact로 내려받아 확인한다.

**옵션 경로 (별도 결정):** GitHub Pages 배포.

```
collect → 스냅샷 → dashboard 생성 → rate-data 갱신
        → site/ 를 Pages Artifact 업로드 → Pages 배포
```

private 저장소의 Pages 공개 범위를 먼저 확인해야 하므로 **P1-A에서는 구현하지 않는다.** 수집 워크플로우에 주석으로 자리만 남긴다.

---

## 6. 정적 대시보드 계약 (신규)

### 6.1 템플릿과 생성 결과 분리

```
web/templates/dashboard.html   # 템플릿
site/index.html                # 생성 결과
```

같은 파일을 템플릿이자 결과물로 쓰지 않는다.

### 6.2 데이터 주입 지점

템플릿에 주입 지점을 **하나만** 둔다.

```html
<script id="rate-monitor-data" type="application/json">
{...}
</script>
```

게시된 페이지는 외부 fetch가 차단될 수 있으므로 런타임에 JSON을 불러오지 않는다. 빌더가 인라인한다.

### 6.3 빌드 후 자체 검증

빌더가 다음을 assert하고, 하나라도 실패하면 산출물을 쓰지 않는다.

```
치환 마커 잔존 0건
P0 하드코딩 수치 잔존 0건
인라인 JSON 파싱 성공
SQLite 집계값 == 화면 집계값
```

기존 P0 대시보드의 디자인 토큰·레이아웃·다크모드 대응은 그대로 옮긴다. **수치와 상태는 전부 생성 데이터로 교체한다.**

### 6.4 표기 규율

finlife 기반 저축은행 데이터를 표시할 때 다음 문구를 쓴다.

```
저축은행 공시금리 — 전국 본점 기준 참고값
```

다음 표현은 쓰지 않는다. finlife만으로는 부산 구·군 및 지점별 적용금리를 판단할 수 없다.

```
부산 저축은행 금리
부산 지역별 최고금리
부산에서 가입 가능한 최고상품
```

---

## 7. 원본 추적성 — 행 단위 (v3 §5.9·§6.1 확장)

`raw_artifact_id`만으로는 원본 JSON의 어느 행에서 나온 값인지 알 수 없다.

### 7.1 `ParsedRateRow` 추가 필드

v3 §6.1의 `ParsedRateRow`에 다음을 추가한다.

```python
raw_artifact_id: str | None        # 오케스트레이터가 채움
base_source_locator: str           # 예: "$.result.baseList[4]"
option_source_locator: str | None  # 예: "$.result.optionList[17]"
source_record_hash: str            # 예: "sha256:…"
```

`source_record_hash`는 결합된 원천 레코드(base + option)의 정규화 직렬화에 대한 해시다. 값 변화 감지에 쓴다.

### 7.2 `rate_observations` 추가 컬럼

v3 §5.9 표에 다음을 추가한다.

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `base_source_locator` | TEXT | 원본 내 기본정보 위치 |
| `option_source_locator` | TEXT NULL | 원본 내 옵션 위치 |
| `source_record_hash` | TEXT | 원천 레코드 해시 |
| `source_effective_at` | DATE NULL | 원천기관이 표시한 기준일·공시일 |

### 7.3 시각 필드 분리

| 필드 | 의미 |
|---|---|
| `collected_at` | 우리 수집기가 실제로 가져온 시각 |
| `source_effective_at` | 원천기관이 표시한 기준일·공시일 (finlife는 `dcls_month`) |

**원천 기준일이 없으면 `NULL`로 유지한다.** `collected_at`으로 대체하지 않는다. 두 값을 섞으면 최신성 판단이 조용히 틀어진다.

### 7.4 인증키 마스킹

`request_meta_json`, 로그, 테스트 fixture 어디에도 인증키를 남기지 않는다.

```
auth=[REDACTED]
```

저장 직전 마스킹을 강제하고 테스트로 검증한다.

---

## 8. 스키마 변경 감지 2등급 (v3 §6.2 정정)

v3는 "필수 구조가 사라지면 `SchemaChangedError`"라고만 규정해, 선택 필드 추가에도 수집이 멈출 수 있었다. 등급을 나눈다.

| 등급 | 조건 | 처리 |
|---|---|---|
| `compatible_schema_change` | 새로운 선택 필드 추가 / 필드 순서 변경 / 알 수 없는 필드 추가 | **수집 계속.** `review_items`에 경고 기록 |
| `breaking_schema_change` | 필수 필드 삭제 / 필수 필드 타입 변경 / `baseList`·`optionList` 소실 / 결합키 구조 변경 / 금리 필드 숫자 변환 실패 | `SchemaChangedError`. 이전 정상값 유지 |

`compatible` 변경은 실행 상태를 `success`로 두되 `warning_count`를 올린다.

---

## 9. 기술 스택 (v3 §2 대체)

| 영역 | 기술 | 비고 |
|---|---|---|
| 언어 | Python 3.12+ | 타입힌트 필수 |
| DB | SQLite WAL | 단일 writer |
| ORM | SQLAlchemy 2.x | 명시적 모델·트랜잭션 |
| 마이그레이션 | Alembic | |
| 검증 | Pydantic v2 | |
| HTTP | httpx | timeout·retry 제어 |
| 설정 | YAML + 환경변수 | 비밀키는 환경변수 |
| CLI | `argparse` | 별도 CLI 프레임워크를 넣지 않는다 |
| 테스트 | pytest | golden fixture 중심 |
| 린트 | ruff | |
| 패키징 | uv | `uv.lock` 커밋 |
| 실행 | GitHub Actions | 로컬 서버 없음 |

**넣지 않는 것:** FastAPI, uvicorn, Jinja2, HTMX, Tabulator (§1), `openpyxl` (P1 범위에 Excel 없음. P2에서 추가).

개발·운영 런타임을 일치시킨다. 개발 컨테이너 기본 Python이 3.11이므로 `uv python pin 3.12`로 고정하고, CI·수집 워크플로우도 3.12로 맞춘다.

### 9.1 CLI

```bash
rate-monitor collect --source finlife
rate-monitor build-dashboard
rate-monitor validate --run <RUN_ID>
```

`serve`는 만들지 않는다.

---

## 10. 워크플로우 계약 (신규)

### 10.1 CI — 외부 네트워크 없음

```
트리거: push / pull_request
→ ruff
→ pytest (fixture 기반)
→ alembic upgrade head
```

CI는 외부 API를 호출하지 않고 시크릿도 쓰지 않는다. 원천 사이트 장애가 코드 검증을 막으면 안 된다.

### 10.2 수집 — 단일 writer

```
트리거: workflow_dispatch / schedule
concurrency:
  group: rate-data-writer
  cancel-in-progress: false
```

**`cancel-in-progress: false`가 중요하다.** 각 실행은 하나의 금리 관측 이력이므로 자동 취소하지 않고 직렬 대기시킨다.

커밋 직전에 최신 `rate-data`를 다시 fetch하고, push 충돌 시 1회 재시도한다.

---

## 11. 부산 지역 seed (v3 §8.2 보완)

`config/regions.yaml`에 부산 16개 구·군 **이름**은 넣되, **행정구역 코드는 공식 출처로 확인되기 전까지 `null`로 둔다.**

```yaml
- sido_name: 부산광역시
  sigungu_name: 부산진구
  sido_code: null
  sigungu_code: null
```

새마을금고 참고 저장소의 내부 지역정보(`r1`/`r2`)를 행정구역 공식 코드로 간주하지 않는다. 그것은 해당 사이트의 표시 문자열이지 행정안전부 코드가 아니다.

주소 파싱 실패 시 지역을 추측 저장하지 않고 검수항목을 만든다 (v3 §8.2 유지).

---

## 12. P1 단계 분리와 완료 게이트 (v3 §18 대체)

저축은행 1차 원천인 저축은행중앙회(FSB)는 아직 표본이 없다. "실물 표본 없이 파서를 추정 구현하지 않는다"(v3 §22)를 지키기 위해 P1을 둘로 나눈다.

```
P1-A: finlife 기반 저축은행 참고공시 파이프라인
P1-B: 저축은행중앙회 FSB 1차 원천 연결
```

P1-A는 완성형 저축은행 수집이 아니다. 화면·문서에 §6.4 표기 규율을 적용한다.

### 12.1 P1-A 완료 게이트

실제 Actions 실행으로 검증한다. 확인하지 못한 항목은 "미검증"으로 표기한다.

```
alembic upgrade head 성공
SQLite 테이블 13종 생성
finlife 저축은행 실제 데이터 수집 성공
원본 JSON Artifact 업로드 성공
원본 추적 locator 누락 0
max_rate NULL 규칙 위반 0
동일 표본 재수집 시 정규 엔터티 증가 0
PRAGMA integrity_check = ok
PRAGMA foreign_key_check 결과 0건
manifest SHA256 == 실제 DB 파일 해시
manifest 행 수 == SQL COUNT
대시보드 표시 수치 == summary.json
FINLIFE_API_KEY 노출 0건
```

### 12.2 재수집 중복 — 정확한 기대값

동일 표본을 다시 수집할 때 `rate_observations`까지 0건 증가하는 것이 **아니다.** 실행 이력은 남아야 한다.

```
institution      증가 0
product          증가 0
product_variant  증가 0

collection_run   증가 1
rate_observation 해당 실행 기준으로 variant당 1건 생성
동일 run 내부 observation 중복 0
```

마지막 항목은 `rate_observations(variant_id, run_id)` 유니크 제약으로 보장한다.

### 12.3 P1-B 완료 게이트

FSB 표본 확보 후 별도로 정의한다. 최소 요건은 v3 §7.2의 필수 필드 전부와, finlife 값과의 `cross_source_difference` 검수항목 생성이다.

---

## 13. 미해소 항목

| 항목 | 상태 |
|---|---|
| 행정구역 공식 코드 | 미확보. §11대로 `null` 유지 |
| `rate-data` 브랜치 누적 용량 | **실측 완료.** 1회분 1.36 MB. gzip은 델타 압축이 안 되므로 일 1회 기준 연 약 500 MB. 정리 정책은 수집 주기 결정 시 함께 정한다 (`docs/p1a-completion.md` §4) |
| 원본 1년 보존 | **미충족.** Artifact 상한이 90일로 확인됨 (§4). v3 §16.2 요구를 채우려면 별도 보관소 결정 필요 |
| private 저장소 Pages 공개 범위 | §5 옵션 경로 결정 전제 |
| finlife HTTPS 지원 여부 | **해소.** 지원한다. `http`는 307로 `https`에 넘기므로 클라이언트가 리다이렉트를 따라가야 한다 |
| finlife 일일 호출 한도 | 미확인. run 30988197006은 7회 호출로 끝나 한도에 닿지 않았다 |
| 정적 대시보드에서의 수기 편집(P2.5) | v3 §11 오버라이드 모델이 서버 API를 전제한다. P2 화면 후 재설계 |
| 참고 저장소 LICENSE 파일 부재 | `package.json`의 ISC 선언만 존재 |
