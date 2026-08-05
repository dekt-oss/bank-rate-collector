# 금리모니터 제작 명세서 v3 — 새마을금고 독립 수집모델 통합

- 프로젝트명: `rate-monitor`
- 작성일: 2026-08-05
- 상태: 구현 기준안 — 새마을금고 수집방식 검증 반영
- 관련 문서: `금리모니터_통합기획서_v3.md`, `금리모니터_제작명세서_v2.md`
- 1차 목표: 부산 16개 구·군의 저축은행·새마을금고·신협·지역농축협 수신금리를 통합 조회·편집·내보내기

---

## 0. 구현 결론

- 저장소는 **SQLite**를 사용하고, 모든 수집 결과를 시점 이력으로 누적한다.
- 수집기는 `fetch → raw 저장 → parse → normalize → validate → reconcile → persist` 단계로 분리한다.
- 새마을금고는 기존 공개 프로젝트 `if1live/shiroko-kfcc`가 검증한 공식 조회 흐름을 **기술 참고자료로 활용하되 코드는 복사하지 않고 독립 구현**한다.
- 새마을금고 운영 수집원은 `kfcc_official`이며, 공개 프로젝트의 생성 JSON은 `kfcc_reference`라는 **검증·비상용 보조 수집원**으로만 사용한다.
- 공식 직접수집, 공개 참고데이터, 수동 파일 수입을 동일한 표준 스키마로 변환하되 출처와 신뢰등급을 절대 합치지 않는다.
- 공식 수집 실패 시 이전 정상값을 삭제하지 않는다. 참고데이터를 표시할 경우 반드시 `비공식 참고값` 배지를 붙인다.
- 새마을금고는 금고 법인과 본점·지점을 분리하고, 공식 `gmgoCd`를 기관 식별키의 최우선 원천값으로 사용한다.
- 기존 프로젝트보다 우위에 두는 핵심은 **동적 지역목록, 요청 제어, 원본 보존, 구조변경 탐지, 전체 상품·기간 수집, 우대금리 확장, 이중원천 대조, 데이터 편집·이력관리**다.
- 저축은행·신협·농축협의 기존 수집방식과 동일한 Source Adapter 계약으로 통합하여 하나의 화면·DB·엑셀 파이프라인에서 처리한다.

### 0.1 새마을금고 수집 전략 한 줄

```text
새마을금고 공식 공개조회 → 자체 수집기 → 원본 HTML → 표준화 DB
                                      ↘ 공개 참고 JSON과 자동 대조
```

### 0.2 사용 원칙

| 구분 | 적용 |
|---|---|
| 기존 프로젝트의 요청 순서·식별자 구조 참고 | 허용 |
| 공식 페이지 요청 파라미터와 응답구조 재검증 | 필수 |
| 기존 소스코드·함수·주석 직접 복사 | 금지 — 명시적 라이선스 확인 전 |
| 공개 JSON 초기 적재·교차검증 | 허용 |
| 공개 JSON을 유일한 운영 원천으로 사용 | 금지 |
| 차단·캡차·접근통제 우회 | 금지 |

---

## 1. 시스템 구성

```text
┌─────────────────────────────┐
│ Scheduler / Manual Collect  │
└──────────────┬──────────────┘
               ↓
┌─────────────────────────────┐
│ Source Adapter              │
│ API / HTTP / Browser / File │
└──────────────┬──────────────┘
               ↓
┌─────────────────────────────┐
│ Raw Artifact Store          │
│ response/file/hash/query    │
└──────────────┬──────────────┘
               ↓
┌─────────────────────────────┐
│ Parser → Normalizer         │
└──────────────┬──────────────┘
               ↓
┌─────────────────────────────┐
│ Validator / Entity Resolver │
└──────────────┬──────────────┘
               ↓
┌─────────────────────────────┐
│ SQLite                      │
│ canonical + history + edits │
└──────────────┬──────────────┘
               ↓
┌─────────────────────────────┐
│ FastAPI / Web UI / XLSX     │
└─────────────────────────────┘
```

---

## 2. 권장 기술 스택

| 영역 | 기술 | 비고 |
|---|---|---|
| 언어 | Python 3.12+ | 타입힌트 필수 |
| API | FastAPI | 조회·수집·편집·내보내기 |
| DB | SQLite WAL | 단일 사용자·소수 사용자 |
| ORM | SQLAlchemy 2.x | 명시적 모델·트랜잭션 |
| 마이그레이션 | Alembic | 스키마 변경 관리 |
| 검증 | Pydantic v2 | API·설정·수집 결과 |
| HTTP | httpx | timeout·retry 제어 |
| HTML 파싱 | selectolax 또는 lxml | 구조 지문 지원 |
| 브라우저 자동화 | Playwright | 필요 소스만 선택 적용 |
| Excel | openpyxl | 입력·출력 모두 사용 |
| 설정 | YAML + 환경변수 | 비밀키는 환경변수 |
| 테스트 | pytest | golden fixture 중심 |
| 프론트 | Jinja2 + HTMX/경량 JS + Tabulator | 정렬·필터·인라인 편집 |
| 패키징 | uv 또는 Poetry | lock 파일 커밋 |
| 배포 | 로컬 실행 / Docker Compose | 외부 공개 금지 기본 |

프론트 라이브러리 자산은 사내망·오프라인 실행을 고려해 CDN이 아니라 프로젝트에 포함한다.

---

## 3. 디렉터리 구조

```text
rate-monitor/
├─ pyproject.toml
├─ alembic.ini
├─ README.md
├─ .env.example
├─ config/
│  ├─ app.yaml
│  ├─ regions.yaml
│  └─ sources.yaml
├─ src/rate_monitor/
│  ├─ main.py
│  ├─ cli.py
│  ├─ settings.py
│  ├─ db/
│  │  ├─ session.py
│  │  ├─ models.py
│  │  ├─ repositories/
│  │  └─ migrations/
│  ├─ domain/
│  │  ├─ enums.py
│  │  ├─ schemas.py
│  │  ├─ identifiers.py
│  │  ├─ normalization.py
│  │  ├─ validation.py
│  │  ├─ overlays.py
│  │  └─ changes.py
│  ├─ collectors/
│  │  ├─ base.py
│  │  ├─ registry.py
│  │  ├─ finlife/
│  │  │  ├─ adapter.py
│  │  │  ├─ parser.py
│  │  │  └─ fixtures.py
│  │  ├─ fsb/
│  │  │  ├─ adapter.py
│  │  │  ├─ parser.py
│  │  │  └─ mapping.py
│  │  ├─ kfcc/
│  │  │  ├─ official_adapter.py     # 공식 직접수집, 주 수집원
│  │  │  ├─ reference_adapter.py    # 공개 JSON 수입, 검증·비상용
│  │  │  ├─ manual_adapter.py       # 저장 HTML/JSON 수동 수입
│  │  │  ├─ client.py               # 속도제어·재시도·회로차단기
│  │  │  ├─ region_discovery.py     # 공식 지역·점포 목록 수집
│  │  │  ├─ rate_parser.py          # 상품군·기간·금리 파싱
│  │  │  ├─ reference_parser.py     # banks/details/report JSON 파싱
│  │  │  ├─ reconciler.py           # 공식값과 참고값 대조
│  │  │  ├─ mapping.py              # 상품군·필드 매핑
│  │  │  └─ fingerprints.py         # 구조 지문·필수 선택자
│  │  ├─ cu/
│  │  │  ├─ adapter.py
│  │  │  ├─ parser.py
│  │  │  └─ mapping.py
│  │  └─ nh_local/
│  │     ├─ adapter.py
│  │     ├─ parser.py
│  │     └─ site_profiles.py
│  ├─ services/
│  │  ├─ collection_service.py
│  │  ├─ query_service.py
│  │  ├─ edit_service.py
│  │  ├─ coverage_service.py
│  │  ├─ export_service.py
│  │  └─ review_service.py
│  ├─ api/
│  │  ├─ router.py
│  │  ├─ records.py
│  │  ├─ collections.py
│  │  ├─ edits.py
│  │  ├─ reviews.py
│  │  └─ exports.py
│  ├─ web/
│  │  ├─ templates/
│  │  └─ static/
│  └─ jobs/
│     ├─ scheduler.py
│     └─ commands.py
├─ data/
│  ├─ rate_monitor.sqlite3
│  ├─ raw/
│  │  └─ YYYY/MM/DD/{run_id}/
│  ├─ inbox/
│  ├─ exports/
│  └─ backups/
├─ tests/
│  ├─ fixtures/
│  ├─ golden/
│  ├─ unit/
│  ├─ integration/
│  └─ e2e/
└─ docs/
   ├─ architecture.md
   ├─ source-recon.md
   ├─ data-dictionary.md
   └─ operations.md
```

---

## 4. 도메인 열거형

```python
from enum import StrEnum

class Sector(StrEnum):
    BANK = "bank"
    SAVINGS_BANK = "savings_bank"
    KFCC = "kfcc"
    CU = "cu"
    NH_LOCAL = "nh_local"

class ProductType(StrEnum):
    TERM_DEPOSIT = "term_deposit"
    INSTALLMENT_SAVINGS = "installment_savings"
    FLEXIBLE_SAVINGS = "flexible_savings"
    DEMAND_DEPOSIT = "demand_deposit"
    OTHER = "other"

class JoinChannel(StrEnum):
    BRANCH = "branch"
    INTERNET = "internet"
    MOBILE = "mobile"
    TELEPHONE = "telephone"
    AGENT = "agent"
    ANY = "any"
    UNKNOWN = "unknown"

class InterestMethod(StrEnum):
    SIMPLE = "simple"
    COMPOUND = "compound"
    UNKNOWN = "unknown"

class AvailabilityScope(StrEnum):
    NATIONWIDE = "nationwide"
    LOCAL_MEMBERS = "local_members"
    WORKPLACE_MEMBERS = "workplace_members"
    SPECIFIC_REGION = "specific_region"
    UNKNOWN = "unknown"

class RateScope(StrEnum):
    NATIONWIDE = "nationwide"
    INSTITUTION = "institution"
    OUTLET = "outlet"
    HEAD_OFFICE_REFERENCE = "head_office_reference"
    UNKNOWN = "unknown"

class CollectionMode(StrEnum):
    API = "api"
    HTTP = "http"
    BROWSER = "browser"
    FILE = "file"
    MANUAL = "manual"

class SourceRole(StrEnum):
    PRIMARY_OFFICIAL = "primary_official"
    SECONDARY_OFFICIAL = "secondary_official"
    REFERENCE_THIRD_PARTY = "reference_third_party"
    MANUAL_OFFICIAL_IMPORT = "manual_official_import"
    MANUAL_OVERRIDE = "manual_override"

class TrustLevel(StrEnum):
    OFFICIAL_DIRECT = "official_direct"
    OFFICIAL_IMPORTED = "official_imported"
    THIRD_PARTY_REFERENCE = "third_party_reference"
    USER_ENTERED = "user_entered"

class RunStatus(StrEnum):
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL = "partial"
    NO_CHANGE = "no_change"
    BLOCKED = "blocked"
    SCHEMA_CHANGED = "schema_changed"
    FAILED = "failed"

class ValidationStatus(StrEnum):
    VALID = "valid"
    WARNING = "warning"
    ERROR = "error"
    REVIEWED = "reviewed"
```

---

## 5. DB 스키마 계약

### 5.1 `sources`

| 컬럼 | 타입 | 제약/설명 |
|---|---|---|
| `id` | TEXT PK | `finlife`, `fsb`, `kfcc`, `cu`, `nh_local:*` |
| `name` | TEXT | 공식 소스명 |
| `sector` | TEXT | Sector |
| `mode` | TEXT | API/HTTP/BROWSER/FILE/MANUAL |
| `source_role` | TEXT | primary_official/secondary_official/reference_third_party/manual_official_import |
| `trust_level` | TEXT | official_direct/official_imported/third_party_reference |
| `priority` | INT | 낮을수록 우선. 동일 상품옵션의 표시값 선택에 사용 |
| `base_reference` | TEXT NULL | 출처 식별용 주소 또는 설명 |
| `enabled` | BOOL | 수집 활성화 |
| `schedule_cron` | TEXT NULL | OS 스케줄 생성 참고 |
| `policy_status` | TEXT | allowed/review/manual_only |
| `coverage_status` | TEXT | complete/high/partial/manual/unknown |
| `parser_version` | TEXT | 파서 버전 |
| `created_at` | DATETIME | UTC |
| `updated_at` | DATETIME | UTC |

### 5.2 `collection_runs`

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `id` | UUID PK | 실행 ID |
| `source_id` | FK | 수집원 |
| `mode` | TEXT | 실제 실행 방식 |
| `started_at`, `finished_at` | DATETIME | UTC |
| `status` | TEXT | RunStatus |
| `query_context_json` | JSON | 지역·기간·채널·페이지 등 |
| `raw_count` | INT | 원천 행 수 |
| `parsed_count` | INT | 파싱 건수 |
| `valid_count` | INT | 정상 건수 |
| `warning_count` | INT | 경고 건수 |
| `error_count` | INT | 오류 건수 |
| `message` | TEXT | 요약 |
| `schema_fingerprint` | TEXT | 구조 지문 |
| `previous_run_id` | FK NULL | 이전 정상 실행 |
| `fallback_used` | BOOL | 참고·수동 원천 사용 여부 |
| `blocked_until` | DATETIME NULL | 회로차단기 해제 예정 시각 |

### 5.3 `raw_artifacts`

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `id` | UUID PK | 원본 ID |
| `run_id` | FK | 실행 ID |
| `artifact_type` | TEXT | json/html/xlsx/csv/pdf/text |
| `relative_path` | TEXT | `data/raw` 하위 경로 |
| `sha256` | TEXT | 원본 해시; `(run_id, sha256)` 유니크 |
| `content_length` | INT | 크기 |
| `encoding` | TEXT NULL | 문자 인코딩 |
| `request_meta_json` | JSON | URL 대신 요청 메타 포함 가능 |
| `captured_at` | DATETIME | UTC |

원본 파일은 DB BLOB이 아니라 파일로 저장하고 DB에는 경로와 해시를 저장한다.

### 5.4 `institutions`

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `id` | UUID PK | 내부 표준 기관 ID |
| `sector` | TEXT | 권역 |
| `canonical_name` | TEXT | 표준 기관명 |
| `normalized_name` | TEXT | 검색·중복용 |
| `institution_type` | TEXT | 은행/저축은행/지역금고/직장금고/신협/농협/축협 |
| `sido_code`, `sigungu_code` | TEXT NULL | 행정구역 코드 |
| `address` | TEXT NULL | 본점 주소 |
| `phone` | TEXT NULL | 대표번호 |
| `availability_scope` | TEXT | 가입 범위 |
| `active` | BOOL | 운영 여부 |
| `first_seen_at`, `last_seen_at` | DATETIME | 발견 이력 |

기관 테이블은 특정 수집원에 종속시키지 않는다. 저축은행 한 곳이 저축은행중앙회와 금융감독원에 동시에 존재할 수 있으므로 공식 소스 키는 `source_entity_links`에서 관리한다.

### 5.5 `outlets`

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `id` | UUID PK | 내부 표준 지점 ID |
| `institution_id` | FK | 소속 기관 |
| `name` | TEXT | 본점·지점명 |
| `outlet_type` | TEXT | head_office/branch/office |
| `sido_code`, `sigungu_code` | TEXT | 지역 |
| `address`, `phone` | TEXT NULL | 연락처 |
| `active` | BOOL | 운영 여부 |

### 5.6 `products`

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `id` | UUID PK | 내부 표준 상품 ID |
| `institution_id` | FK | 판매기관 |
| `product_type` | TEXT | ProductType |
| `name` | TEXT | 원문 상품명 |
| `normalized_name` | TEXT | 비교용 명칭 |
| `is_special_sale` | BOOL | 특판 여부 |
| `sale_start`, `sale_end` | DATE NULL | 판매기간 |
| `active` | BOOL | 최신 판매 여부 |
| `first_seen_at`, `last_seen_at` | DATETIME | 이력 |

### 5.7 `source_entity_links`

공식 소스의 기관·점포·상품 키를 내부 표준 엔터티에 연결한다. 한 내부 기관이 여러 소스 키를 가질 수 있고, 한 소스 키는 한 시점에 하나의 내부 엔터티만 가리킨다.

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `id` | UUID PK | 매핑 ID |
| `source_id` | FK | 수집원 |
| `entity_type` | TEXT | institution/outlet/product |
| `source_entity_key` | TEXT | 공식 내부 키 또는 안정적 복합키 |
| `entity_id` | UUID | 내부 표준 엔터티 ID |
| `source_name` | TEXT NULL | 해당 소스의 원문명 |
| `source_payload_json` | JSON NULL | 식별에 사용한 원천 메타 |
| `confidence` | DECIMAL | 자동 매핑 신뢰도 |
| `match_method` | TEXT | exact_code/manual/name_address 등 |
| `valid_from`, `valid_to` | DATE NULL | 통폐합·키 변경 대응 |
| `created_at`, `updated_at` | DATETIME | 이력 |

유니크: `(source_id, entity_type, source_entity_key, valid_to IS NULL)`에 해당하는 활성 매핑은 하나만 허용한다.

### 5.8 `product_variants`

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `id` | UUID PK | 비교 단위 ID |
| `product_id` | FK | 상품 |
| `outlet_id` | FK NULL | 지점 적용 시 |
| `term_months` | INT NULL | 개월 |
| `term_days` | INT NULL | 일 |
| `join_channel` | TEXT | 가입방식 |
| `interest_method` | TEXT | 단리·복리 |
| `payment_method` | TEXT NULL | 정액·자유적립 |
| `amount_min`, `amount_max` | DECIMAL NULL | 가입금액/구간 |
| `customer_scope` | TEXT NULL | 개인·법인 등 |
| `rate_scope` | TEXT | nationwide/institution/outlet/reference |
| `variant_key` | TEXT UNIQUE | 결정적 내부 키 |

`variant_key`는 가능한 공식 키를 사용하고, 없으면 다음 정규화 값의 해시로 생성한다.

```text
sector | institution stable key | product stable key/name |
term | channel | interest method | amount band | outlet key
```

지역명은 기관 식별자에 이미 포함되지 않는 한 상품옵션 키에 넣지 않는다. 이름·주소 변경만으로 금리 이력이 끊기지 않게 한다.

### 5.9 `rate_observations`

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `id` | UUID PK | 관측 ID |
| `variant_id` | FK | 상품옵션 |
| `run_id` | FK | 수집 실행 |
| `raw_artifact_id` | FK | 원본 |
| `as_of` | DATE NULL | 공시 기준일 |
| `observed_at` | DATETIME | 수집 시각 |
| `base_rate` | DECIMAL(7,4) NULL | 기본금리 |
| `max_rate` | DECIMAL(7,4) NULL | 최고금리 |
| `rate_basis` | TEXT | annual_pre_tax 등 |
| `source_detail_json` | JSON | 원천별 추가 필드 |
| `raw_preference_text` | TEXT | 우대조건 원문 |
| `validation_status` | TEXT | 검증상태 |
| `validation_message` | TEXT NULL | 경고·오류 |
| `content_hash` | TEXT | 값 중복 검출 |

유니크: `(variant_id, run_id)`을 기본으로 한다. `content_hash`는 이전 실행과 동일 값인지 판정하는 용도이며, 실행 이력을 잃지 않도록 전역 중복 제거 키로 사용하지 않는다.

### 5.10 `preference_conditions`

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `id` | UUID PK | 조건 ID |
| `observation_id` | FK | 원본 관측 |
| `condition_type` | TEXT | 분류 |
| `description` | TEXT | 원문 조각 |
| `add_rate` | DECIMAL NULL | 가산 %p |
| `mandatory` | BOOL NULL | 필수 여부 |
| `stackable` | BOOL NULL | 중복 적용 |
| `parser_confidence` | DECIMAL NULL | 0~1 |
| `parse_status` | TEXT | parsed/partial/raw_only |

### 5.11 `manual_overrides`

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `id` | UUID PK | 수정 ID |
| `target_type` | TEXT | institution/product/variant/observation/condition |
| `target_id` | UUID NULL | 수집 대상 ID |
| `action` | TEXT | edit/add/hide/annotate |
| `field_name` | TEXT NULL | 수정 필드 |
| `original_value_json` | JSON NULL | 생성 당시 원본값 |
| `override_value_json` | JSON NULL | 표시값 |
| `reason` | TEXT | 수정 사유 |
| `memo` | TEXT NULL | 메모 |
| `effective_from`, `effective_to` | DATE NULL | 적용기간 |
| `conflict_status` | TEXT | none/conflict/resolved |
| `created_by` | TEXT | 기본 `local-user` |
| `created_at`, `updated_at` | DATETIME | UTC |
| `active` | BOOL | 적용 여부 |

### 5.12 `entity_aliases`

기관·상품 이름 변경과 중복 해결에 사용한다.

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `id` | UUID PK | 별칭 ID |
| `entity_type` | TEXT | institution/product |
| `entity_id` | UUID | 표준 엔터티 |
| `source_id` | FK NULL | 소스별 별칭 |
| `alias` | TEXT | 원문명 |
| `normalized_alias` | TEXT | 정규화명 |
| `valid_from`, `valid_to` | DATE NULL | 유효기간 |

### 5.13 `review_items`

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `id` | UUID PK | 검수 항목 |
| `run_id` | FK NULL | 관련 실행 |
| `entity_type`, `entity_id` | TEXT/UUID NULL | 대상 |
| `issue_type` | TEXT | parse_error/duplicate/rate_anomaly/conflict/stale/missing_region |
| `severity` | TEXT | info/warning/error |
| `message` | TEXT | 사용자 설명 |
| `payload_json` | JSON | 비교값 |
| `status` | TEXT | open/resolved/ignored |
| `created_at`, `resolved_at` | DATETIME | 이력 |


### 5.14 `cross_source_comparisons`

동일한 새마을금고 상품옵션을 `kfcc_official`과 `kfcc_reference`에서 비교한 결과다. 참고원천의 값을 공식 관측값에 덮어쓰지 않는다.

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `id` | UUID PK | 비교 ID |
| `official_observation_id` | FK NULL | 공식 직접수집 관측 |
| `reference_observation_id` | FK NULL | 공개 참고데이터 관측 |
| `comparison_key` | TEXT | `gmgoCd|category|product|term|amount_band` |
| `official_rate` | DECIMAL NULL | 공식 수집 금리 |
| `reference_rate` | DECIMAL NULL | 참고 수집 금리 |
| `difference_pp` | DECIMAL NULL | 절대 차이 %p |
| `status` | TEXT | match/mismatch/official_only/reference_only/stale_reference |
| `official_as_of`, `reference_as_of` | DATE NULL | 기준일 |
| `compared_at` | DATETIME | 비교시각 |
| `review_item_id` | FK NULL | 불일치 검수항목 |

유니크: `(comparison_key, official_as_of, reference_as_of)`.

표준 허용오차는 `0.01%p`다. 날짜가 다르면 금리값이 같아도 `match`가 아니라 기준일 차이를 별도로 기록한다.

---

## 6. 수집기 인터페이스 계약

### 6.1 공통 타입

```python
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol

@dataclass(frozen=True)
class CollectionRequest:
    source_id: str
    regions: tuple[str, ...] = ()
    product_types: tuple[str, ...] = ()
    terms: tuple[int, ...] = ()
    channels: tuple[str, ...] = ()
    as_of: date | None = None
    input_files: tuple[str, ...] = ()
    options: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class RawArtifactData:
    artifact_type: str
    content: bytes
    filename: str
    request_meta: dict[str, Any]
    schema_fingerprint: str
    source_role: str
    trust_level: str

@dataclass(frozen=True)
class ParsedRateRow:
    source_id: str
    source_role: str
    trust_level: str
    source_institution_key: str | None
    source_outlet_key: str | None
    source_product_key: str | None
    institution_name: str
    outlet_name: str | None
    institution_type: str | None
    sido: str | None
    sigungu: str | None
    address: str | None
    product_type: str
    product_name: str
    term_months: int | None
    term_days: int | None
    join_channel: str
    interest_method: str
    payment_method: str | None
    amount_min: int | None
    amount_max: int | None
    customer_scope: str | None
    availability_scope: str
    rate_scope: str
    base_rate: float | None
    max_rate: float | None
    preference_raw: str
    as_of: date | None
    source_row_ref: str
    extra: dict[str, Any] = field(default_factory=dict)

class SourceAdapter(Protocol):
    source_id: str

    async def fetch(self, request: CollectionRequest) -> list[RawArtifactData]: ...
    def parse(self, artifact: RawArtifactData) -> list[ParsedRateRow]: ...
```

### 6.2 설계 규칙

- `fetch`는 네트워크·브라우저·파일 읽기만 담당하는 비동기 함수다. 파일 모드도 동일 인터페이스를 유지한다.
- `parse`는 동일 원본에서 항상 동일 결과를 반환하는 순수 함수다.
- DB 저장은 어댑터에서 하지 않는다.
- 이름 정규화와 엔터티 매칭은 공통 서비스에서 수행한다.
- 파싱 실패 행은 버리지 않고 `review_item`으로 남기되, 금리 숫자는 `NULL`로 반환한다.
- 필수 구조가 사라지면 빈 배열을 반환하지 않고 `SchemaChangedError`를 발생시킨다.
- 페이지 일부 실패는 정상 페이지를 보존하고 실행 상태를 `partial`로 한다.
- 비공식 참고데이터가 공식 직접수집을 자동으로 덮어쓰게 해서는 안 된다.
- 네트워크 태스크는 생성한 Promise/Coroutine을 모두 반환·수집하고 `await`해야 한다. fire-and-forget 방식은 금지한다.

### 6.3 새마을금고 클린룸 재구현 원칙

- 공개 저장소는 동작 검증과 공식 요청흐름 분석에만 사용한다.
- 개발자는 공식 페이지의 요청·응답을 자체 캡처한 fixture를 기준으로 새 코드를 작성한다.
- 변수명·함수명·주석·테스트를 기존 저장소에서 복사하지 않는다.
- 구현 완료 후 기존 공개 JSON과 결과만 비교한다.
- 구현 근거는 `docs/source-recon/kfcc.md`에 요청경로, 파라미터, 필수 선택자, 검증일을 기록한다.

### 6.4 예외

```python
class CollectorError(Exception): ...
class SourceBlockedError(CollectorError): ...
class SchemaChangedError(CollectorError): ...
class ParseError(CollectorError): ...
class ValidationError(CollectorError): ...
```

---

## 7. 소스별 명세

### 7.1 금융감독원 API

대상:

- 은행 정기예금·적금
- 저축은행 교차검증

요구사항:

- 페이지 끝까지 순회
- 기본정보와 옵션정보를 공식 상품 키로 결합
- 기간·저축금리·최고우대금리를 옵션 단위로 저장
- 공시 제출월과 수집시각 분리
- API 오류코드와 호출 한도 기록
- 인증키는 환경변수로만 주입

테스트:

- base/option 결합
- 페이지네이션
- 옵션 없는 상품
- 동일 상품 다기간
- 금리 문자열·NULL

### 7.2 저축은행중앙회 소비자포털

대상 화면:

- 정기예금
- 정기적금
- 입출금자유예금

수집 전략 우선순위:

1. 공식 엑셀 다운로드 요청 재현
2. 공식 조회 응답 파싱
3. 브라우저 자동화로 다운로드
4. 사용자가 다운로드한 파일 수입

필수 조회차원:

- 조회일
- 가입기간
- 가입방법
- 단리·복리

필수 필드:

- 저축은행명
- 상품명
- 기본금리
- 최고우대금리
- 가입방법
- 상품 상세·우대조건
- 조회일·공시일

주의:

- 본점 기준 공시를 부산 지점 금리로 복제하지 않는다.
- 동일 상품이 단리·복리로 중복 노출되는 경우 옵션으로 분리한다.
- 금융감독원 값과 불일치하면 한 값을 덮지 않고 `cross_source_difference` 검수항목을 생성한다.

### 7.3 새마을금고 — 독립 수집 + 참고원천 대조

#### 7.3.1 기술 결정

기존 공개 프로젝트가 사용하는 다음 수집모델을 참고한다.

```text
지역별 금고·점포 목록 조회
→ 공식 금고코드(gmgoCd)와 본점·분점 코드 확보
→ 금고코드별 상품군 상세 조회
→ 상품명·가입기간·기본이율·기준일 파싱
→ JSON/CSV 산출
```

우리 구현은 이 흐름을 그대로 복사하지 않고 다음 기능을 추가한 독립 수집기로 작성한다.

1. 부산 16개 구·군을 우선 수집하되 지역목록을 공식 화면에서 동적으로 발견
2. 모든 원본 HTML과 요청조건 저장
3. 저동시성·속도제어·지수 백오프·회로차단기
4. 금고와 지점을 분리하고 `gmgoCd` 기준으로 금리 중복 제거
5. 주요 3개 상품의 12개월 금리뿐 아니라 전체 상품·전체 기간 수집
6. 거치식·적립식 외 요구불예탁금 수집 프로파일 추가
7. 기본금리 외 다른 금리영역·우대조건의 존재를 탐색하되 의미를 추정하지 않고 검수
8. 공개 JSON을 교차검증·비상용으로 연결
9. SQLite 시점 이력·변경탐지·수기편집과 통합

#### 7.3.2 수집원 정의

| source_id | 역할 | 우선순위 | 설명 |
|---|---|---:|---|
| `kfcc_official` | 주 수집원 | 10 | 새마을금고 공식 공개조회 직접수집 |
| `kfcc_manual` | 공식 수입 | 20 | 사용자가 저장한 공식 HTML/JSON 수입 |
| `kfcc_reference` | 참고·검증 | 80 | `if1live/shiroko-kfcc` 생성 JSON |
| `manual_override` | 업무 보정 | 100 | 특판·우대조건 등 사용자 편집 |

`kfcc_reference`는 `TrustLevel.THIRD_PARTY_REFERENCE`로 저장한다. 공식 수집 성공 시 화면 대표값으로 선택하지 않는다.

#### 7.3.3 공식 요청 프로파일

구현 시점에 실제 응답을 다시 확인한 뒤 `config/sources.yaml`로 관리한다. 현재 참고 구현에서 확인된 경로 패턴은 다음과 같다.

```yaml
region_list:
  path: /map/list.do
  params: [r1, r2]

rate_detail:
  path: /map/goods_19.do
  params: [OPEN_TRMID, gubuncode]

product_categories:
  demand_deposit: 12       # 실험 프로파일, 실제 응답 재검증 후 활성
  deferred_deposit: 13     # 거치식예탁금
  installment_savings: 14  # 적립식예탁금
```

경로와 숫자는 공식 API 계약이 아니라 공개 웹페이지의 현재 구현 세부사항이다. 구조 지문이 바뀌면 자동으로 `schema_changed` 처리한다.

#### 7.3.4 지역·기관 수집

1. 공식 위치안내의 시도·시군구 선택값을 조회한다.
2. 부산광역시 16개 구·군을 실행대상으로 만든다.
3. 목록 행에서 다음 원천값을 추출한다.

```text
gmgoCd  공식 금고 코드
gmgoNm  금고명
divCd   본점·분점 구분 코드
divNm   본점·지점명
r1      시도
r2      시군구
```

4. `(gmgoCd, divCd)`를 점포 원천키로 사용한다.
5. `gmgoCd`가 같으면 같은 `institution`, `divCd`가 다르면 별도 `outlet`이다.
6. 금리는 `gmgoCd`별 한 번만 수집한다. 점포 수만큼 금리행을 복제하지 않는다.
7. 직장금고·일반지역금고 여부는 명칭만으로 확정하지 않고 공식 유형 또는 검수결과로 저장한다.
8. 전국 확장 시 하드코딩 지역목록만 사용하지 않는다. 공식 화면에서 발견한 목록과 행정구역 seed를 대조한다.

#### 7.3.5 금리 상세 수집

각 고유 `gmgoCd`와 활성 상품군에 대해 상세 페이지를 조회한다.

필수 파싱:

- 조회 기준일
- 상품군
- 상품명 원문
- 가입기간
- 기본금리
- 금리 단위·세전 여부
- 금액구간이 존재할 경우 하한·상한
- 원본 표의 제목과 행·열 위치

기존 참고 파서는 `.tblWrap` 상품영역, `.tbl-tit` 상품명, `#divTmp1` 기본이율 표를 사용한다. 우리 파서는 이 선택자를 초기 구조지문으로 삼되 다음을 추가한다.

- 상품영역 수·열 헤더·ID 목록을 구조지문에 포함
- `divTmp2` 등 추가 금리영역이 존재하면 원본을 보존하고 P0에서 의미를 확인
- 의미가 확인되지 않은 영역을 최고우대금리로 임의 매핑하지 않음
- 기본이율이 없거나 `별도 문의`이면 `NULL`과 원문 상태 저장
- 0.00 금리는 실제 공시값인지 미공시 표시인지 검수규칙으로 확인

#### 7.3.6 참고데이터 수입

`kfcc_reference`는 다음 공개 산출물을 읽을 수 있게 구현한다.

```text
summary/banks.json                  기관·점포 목록
details/rate_{gmgoCd}.json          금고별 전체 상품·기간
summary/report_mat.json             주요 3상품 12개월 요약
summary/report_euckr.csv             사용자 검산용 CSV
```

수입 우선순위:

1. `banks.json`으로 기관 코드·지역 대조
2. `details/rate_{gmgoCd}.json`으로 상품·기간별 비교
3. `report_mat.json`은 상세파일 부재 시에만 요약 검증
4. CSV는 자동원천이 아니라 수기 검산·백업용

참고데이터의 기준일, 저장소 커밋시각, 파일 SHA를 원본 메타데이터로 저장한다.

#### 7.3.7 공식값·참고값 대조

비교키:

```text
gmgoCd | product_category | normalized_product_name |
term_months | amount_min | amount_max
```

판정:

| 조건 | 상태 | 조치 |
|---|---|---|
| 기준일 동일, 금리차 ≤ 0.01%p | `match` | 정상 |
| 기준일 동일, 금리차 > 0.01%p | `mismatch` | 검수항목 생성 |
| 공식만 존재 | `official_only` | 신규·참고누락 가능성 기록 |
| 참고만 존재 | `reference_only` | 공식 파싱누락 또는 참고 stale 검토 |
| 참고 기준일이 공식보다 오래됨 | `stale_reference` | 비교값만 보존, 대표값 제외 |

기본 표시값 선택:

```text
공식 직접수집 정상값
> 공식 파일 수입값
> 이전 공식 정상값
> 공개 참고값(설정에서 fallback 허용 시, 비공식 배지 필수)
> 사용자 추가값
```

사용자 오버라이드는 표시값을 보정하지만 원본 신뢰도 순위를 바꾸지 않는다.

#### 7.3.8 요청 제어

부산만 수집하는 기본 운영값:

```yaml
concurrency: 2
request_interval_ms: 1000
request_jitter_ms: 300
connect_timeout_seconds: 10
read_timeout_seconds: 20
retry_count: 3
retry_backoff_seconds: [3, 10, 30]
max_consecutive_blocked: 3
circuit_breaker_minutes: 360
```

- 동일 금고의 상품군 요청은 순차 또는 동시성 1로 처리한다.
- HTTP 403·429·캡차·차단 문구가 연속 발생하면 즉시 수집을 중단한다.
- User-Agent 위장이나 프록시 순환으로 차단을 우회하지 않는다.
- 실행 중 생성한 모든 coroutine/task는 반드시 `await`한다.
- 스케줄 기본값은 평일 1회이며, 수동 즉시수집 버튼을 제공한다.

#### 7.3.9 장애·구조변경 처리

| 상황 | 처리 |
|---|---|
| 일부 구 목록 실패 | 성공 구만 `partial` 반영, 실패 구 명시 |
| 금고 상세 1건 실패 | 해당 금고 이전 정상값 유지 |
| 필수 선택자 소실 | `schema_changed`, 신규 데이터 대표값 전환 금지 |
| 전체 차단 | `blocked`, 회로차단기 작동 |
| 참고원천만 정상 | 설정 허용 시 비공식 배지로 임시 표시 |
| 금리 급변 | 정상 저장하되 `rate_anomaly` 검수 생성 |

#### 7.3.10 구현 완료 기준

- 부산 16개 구·군의 금고·점포 목록을 공식 화면 기준으로 수집
- `gmgoCd` 중복 제거 후 금고별 상품군 조회
- 거치식·적립식 전체 상품과 전체 기간 저장
- 요구불예탁금은 최소 3개 금고 표본으로 금액구간 파싱 검증 후 활성화
- 원본 HTML 추적률 100%
- 동일 표본 재파싱 결정성 100%
- 공식값과 참고값의 비교 가능 레코드 중 99% 이상 일치 또는 불일치 사유 검수
- 공식 수집 실패 시 이전 공식 정상값 유지
- 참고값 사용 시 화면·엑셀에 출처 배지와 기준일 표시


### 7.4 신협

수집 단계:

1. 거치식·적립식 탭별 요청
2. 지역 부산 및 하위지역 전체 순회
3. 가입방식별 조회
4. 페이지네이션
5. 상세정보 우대조건 수집
6. 신협찾기 기관 주소와 매핑

필수 처리:

- 조합명과 공식 내부 키 확보
- 기본금리·최고우대금리 분리
- 단리·복리 분리
- 창구·인터넷·모바일 분리
- 같은 상품의 기간별 옵션 분리

### 7.5 지역농축협

P0 산출물에 따라 프로파일을 선택한다.

```yaml
nh_local_profiles:
  - id: central_market
    mode: http
    enabled: false
  - id: cooperative_site_table
    mode: http
    enabled: true
    parser_profile: generic_nonghyup_table_v1
  - id: uploaded_excel
    mode: file
    enabled: true
```

범용 파서 지원 형태:

- HTML 표
- 엑셀
- CSV
- 사용자가 복사한 표 형식 텍스트

개별 사이트 프로파일에는 다음만 둔다.

- 도메인·기관 매핑
- 페이지 경로 또는 수입 파일 규칙
- 헤더 별칭
- 날짜 선택자
- 금리표 선택자

사이트별 코드를 무제한 증식시키지 않고, 동일 구조는 하나의 프로파일로 묶는다.

농축협 수집완전도는 기관 마스터 대비 계산하며, 중앙 전수 소스가 없으면 화면에 `partial`을 표시한다.

---

## 8. 정규화 계약

### 8.1 기관명

정규화 시 제거 또는 통일:

- 앞뒤 공백·연속 공백
- `주식회사`, `(주)` 등 법인표기
- `신용협동조합` ↔ `신협` 표기
- `새마을금고` 접미사 중복
- 괄호 안 본점·지점 표기
- Unicode 정규화

원문은 항상 별도로 보존한다.

### 8.2 지역

- 행정안전부 법정/행정구역 코드를 기준 마스터로 사용
- `부산`, `부산시`, `부산광역시` → `부산광역시`
- 부산 16개 구·군 코드를 고정 seed로 제공
- 주소 파싱 실패 시 지역을 추측 저장하지 않고 검수항목 생성

### 8.3 상품명

상품 정체성용 `normalized_name`과 사용자 표시용 `name`을 분리한다.

정규화 예:

- 공백·특수문자 통일
- 기간·금리·특판 문구 분리
- `정기예금`·`정기예탁금`을 같은 상품유형으로 분류하되 원래 상품명은 유지

서로 다른 공식 상품명을 임의로 하나의 상품으로 합치지 않는다.

### 8.4 금리

- `%`, `연`, 공백 제거 후 Decimal 변환
- `%p`는 우대 가산폭으로 변환
- `기본금리 없음`, `별도 문의`는 NULL + 상태 저장
- 소수점 4자리까지 보존, 화면은 기본 2자리
- `max_rate`가 없으면 base와 같다고 단정하지 않고 NULL로 둔다. 소스가 명시적으로 우대 없음이라고 할 때만 같게 처리한다.

---

## 9. 우대조건 파서

### 9.1 출력 타입

```python
@dataclass(frozen=True)
class ParsedPreference:
    condition_type: str
    description: str
    add_rate: float | None
    mandatory: bool | None
    stackable: bool | None
    confidence: float
    parse_status: str
```

### 9.2 1차 지원 패턴

- `급여이체 시 0.2%p`
- `카드실적 30만원 이상 0.3%p`
- `첫 거래 고객 연 0.1%p`
- `모바일 가입 0.2%p`
- `자동이체 N회 이상 0.1%p`
- `마케팅 동의 0.05%p`
- `조합원 가입 시 0.1%p`
- `만기 유지 시 0.2%p`

### 9.3 원칙

- 규칙 기반 파서를 우선 사용한다.
- 문장 분리 실패 시 원문 전체를 `raw_only`로 반환한다.
- 가산금리 합계가 공시 우대폭을 초과하면 검수 경고를 만든다.
- 우대조건을 AI로 자동 해석하는 기능은 MVP 필수가 아니다.

---

## 10. 수집 오케스트레이션

### 10.1 처리 순서

```python
async def collect_source(request: CollectionRequest) -> CollectionRunResult:
    run = create_run(request)
    try:
        artifacts = await adapter.fetch(request)
        save_raw_artifacts(run, artifacts)
        rows = []
        for artifact in artifacts:
            rows.extend(adapter.parse(artifact))
        normalized = normalize_rows(rows)
        resolved = resolve_entities(normalized)
        validated = validate_rows(resolved)
        persist_transactionally(run, validated)
        create_change_events(run)
        calculate_coverage(run)
        finalize_run(run)
    except SchemaChangedError:
        mark_schema_changed(run)
        raise
```

### 10.2 새마을금고 통합 실행 흐름

```python
async def collect_kfcc(request: CollectionRequest) -> CollectionRunResult:
    official = await collect_with_adapter("kfcc_official", request)

    reference = None
    if request.options.get("run_reference_check", True):
        reference = await collect_with_adapter("kfcc_reference", request)

    comparison = reconcile_kfcc(official, reference)
    create_review_items(comparison)

    return finalize_kfcc_run(
        official=official,
        reference=reference,
        comparison=comparison,
        allow_reference_fallback=request.options.get(
            "allow_reference_fallback", False
        ),
    )
```

공식 수집과 참고수집은 서로 다른 `collection_run`으로 저장한다. 하나의 실행이 실패해도 다른 실행의 상태를 덮지 않는다.

### 10.3 트랜잭션

- 원본 파일 저장과 DB 메타데이터 저장을 먼저 완료
- 표준 데이터 저장은 한 실행 단위 트랜잭션
- `failed` 또는 `schema_changed` 실행은 최신 정상 관측값을 대체하지 않음
- `partial`은 성공 지역만 반영하되 실패 지역을 별도 기록

### 10.4 재시도

- 네트워크 오류: 지수 백오프 최대 3회
- HTTP 4xx: 자동 재시도 제한
- 차단·캡차: 즉시 `blocked`
- 브라우저 셀렉터 실패: `schema_changed`
- 다운로드 파일이 동일 해시: `no_change`

---

## 11. 유효 데이터와 오버라이드 병합

### 11.1 최신 관측 선택

상품옵션별로 다음 순서로 선택한다.

1. 검증상태가 error가 아닌 관측
2. 가장 최신 `as_of`
3. `as_of`가 같으면 가장 최신 수집
4. `sources.priority`가 낮은 공식 원천
5. 참고원천은 공식 정상값이 없고 명시적 fallback이 허용된 경우에만 선택

### 11.2 오버라이드 적용

```text
원본 최신값
  → 활성 edit 적용
  → hide 제거
  → add 결합
  → annotate 부가정보 결합
  → conflict 상태 포함
```

### 11.3 충돌 판정

`original_value_json`과 현재 원본값이 다르고 활성 수정값이 존재하면 충돌이다.

사용자 선택:

- 새 원본 수용 후 수정 해제
- 기존 수정 유지
- 수정값 갱신
- 원본과 수정값을 모두 보관하고 메모

---

## 12. API 명세

### 12.1 조회

```http
GET /api/v1/rates
```

쿼리:

- `sector[]`
- `sido_code`
- `sigungu_code[]`
- `region_basis=institution|outlet|availability`
- `product_type[]`
- `term_months[]`
- `join_channel[]`
- `interest_method[]`
- `base_rate_min`, `base_rate_max`
- `max_rate_min`, `max_rate_max`
- `preference_type[]`
- `special_sale`
- `source_status[]`
- `validation_status[]`
- `q`
- `sort`
- `page`, `page_size`

응답 핵심:

```json
{
  "items": [],
  "total": 0,
  "coverage": {},
  "freshness": {},
  "applied_filters": {}
}
```

### 12.2 상세

```http
GET /api/v1/rates/{variant_id}
GET /api/v1/rates/{variant_id}/history
```

### 12.3 수집

```http
POST /api/v1/collections
GET  /api/v1/collections
GET  /api/v1/collections/{run_id}
POST /api/v1/collections/{source_id}/retry
```

요청 예:

```json
{
  "source_ids": ["fsb", "kfcc", "cu"],
  "regions": ["26000"],
  "product_types": ["term_deposit"],
  "force": false
}
```

동일 소스가 실행 중이면 중복 실행을 거절한다.

### 12.4 편집

```http
POST   /api/v1/overrides
PATCH  /api/v1/overrides/{override_id}
DELETE /api/v1/overrides/{override_id}
POST   /api/v1/overrides/{override_id}/resolve-conflict
```

### 12.5 검수

```http
GET   /api/v1/reviews
PATCH /api/v1/reviews/{review_id}
```

### 12.6 메타·커버리지

```http
GET /api/v1/meta/regions
GET /api/v1/meta/institutions
GET /api/v1/meta/sources
GET /api/v1/coverage
GET /api/v1/dashboard
```

### 12.7 내보내기

```http
GET /api/v1/exports/rates.xlsx
GET /api/v1/exports/changes.xlsx
```

조회 필터를 그대로 받는다.

---

## 13. 웹 화면 명세

### 13.1 공통 레이아웃

- 좌측: 메뉴와 필터
- 상단: 수집 상태·최신성·커버리지
- 중앙: 데이터 그리드
- 우측: 상세 패널
- 하단 또는 별도 화면: 검수 대기

### 13.2 통합 비교 그리드

필수 기능:

- 다중 필터
- 다중 정렬
- 컬럼 고정·숨김·순서 변경
- 행 상세 열기
- 인라인 편집 진입
- 수정·충돌·오류 배지
- 현재 필터 엑셀 저장
- 페이지네이션 또는 가상 스크롤

기본 컬럼 순서:

1. 상태
2. 권역
3. 시군구
4. 기관
5. 상품
6. 기간
7. 가입방식
8. 기본금리
9. 최고금리
10. 우대폭
11. 우대조건 요약
12. 특판 종료
13. 기준일
14. 출처
15. 수집시각

### 13.3 편집 UX

- 기본은 읽기 전용
- `편집 모드` 진입 후 수정 가능
- 저장 전 원본값·수정값·사유 확인
- 수집값은 직접 UPDATE하지 않고 override API 호출
- 수정 셀에 아이콘과 원본 툴팁
- 충돌은 빨간 배지와 검토 버튼

### 13.4 커버리지 UX

예:

```text
새마을금고 부산: 54/54 기관 수집, 최신 2026-08-05
신협 부산: 31/33 기관 수집, 2개 실패
농축협 부산: 8/20 기관 수집, 부분 수집
```

숫자는 기관 마스터가 확정된 뒤 계산한다. 미확정이면 `모집단 확인 중`으로 표시한다.

---

## 14. 엑셀 명세

### 14.1 시트

1. `비교표`: 현재 필터·오버라이드 적용값
2. `우대조건`: 조건별 한 행
3. `기관별요약`: 기관·기간별 최고/기본금리
4. `지역별요약`: 부산 구·군별 통계와 기관 수
5. `변경내역`: 선택 기간 내 변경
6. `원본추적`: 출처·실행·원본 참조
7. `검수항목`: 오류·충돌·미수집

### 14.2 표시 규칙

- 수정 셀: 배경 표식
- 충돌 셀: 별도 강조
- 오류 레코드: 경고 열
- 금리: 숫자 셀 + `0.00%` 표시 형식
- 필터와 자동필터 설정
- 첫 행 고정
- 출처·기준일·수집시각 포함

---

## 15. 설정 파일

### 15.1 `config/app.yaml`

```yaml
app:
  name: rate-monitor
  timezone: Asia/Seoul
  bind_host: 127.0.0.1
  port: 8000

database:
  url: sqlite:///data/rate_monitor.sqlite3
  wal: true

storage:
  raw_dir: data/raw
  inbox_dir: data/inbox
  export_dir: data/exports
  backup_dir: data/backups

ui:
  default_sectors: [savings_bank, kfcc, cu, nh_local]
  benchmark_sector: bank
  default_region: "26000"
  page_size: 100
```

### 15.2 `config/regions.yaml`

부산광역시와 16개 구·군 코드를 seed로 포함한다. 지역명은 화면용이고 내부 필터는 코드로 처리한다.

### 15.3 `config/sources.yaml`

```yaml
sources:
  finlife:
    enabled: true
    mode: api
    schedule: "0 7 * * 1-5"
    request_interval_seconds: 1.0

  fsb:
    enabled: true
    mode: file
    fallback_modes: [browser]
    schedule: "30 7 * * 1-5"

  kfcc_official:
    enabled: true
    mode: http
    source_role: primary_official
    trust_level: official_direct
    priority: 10
    policy_status: review
    schedule: "0 7 * * 1-5"
    regions: ["26000"]
    concurrency: 2
    request_interval_seconds: 1.0
    request_jitter_seconds: 0.3
    retry_count: 3
    allow_reference_fallback: false

  kfcc_reference:
    enabled: true
    mode: http
    source_role: reference_third_party
    trust_level: third_party_reference
    priority: 80
    schedule: "20 7 * * 1-5"
    purpose: reconcile_and_emergency

  kfcc_manual:
    enabled: true
    mode: file
    source_role: manual_official_import
    trust_level: official_imported
    priority: 20

  cu:
    enabled: false
    mode: http
    policy_status: review

  nh_local:
    enabled: true
    mode: file
    coverage_status: partial
```

새마을금고는 기술적 자동수집 가능성이 확인되었으므로 구현대상으로 활성화하되, 실제 운영 배포 전 이용정책·호출부하 검토를 완료해야 한다. 다른 미검증 자동 수집원은 기본 비활성화한다.

---

## 16. 보안·운영

### 16.1 보안

- API 키는 `.env`에 저장하고 커밋 금지
- 기본 바인딩은 `127.0.0.1`
- 외부 공개 시 인증 없이 실행 금지
- 브라우저 자동화 프로필에 개인 인터넷뱅킹 로그인 정보 저장 금지
- 수집 원본에 개인정보가 포함되면 저장 중단 또는 마스킹
- 비공개 페이지·캡차·차단 우회 금지

### 16.2 백업

- SQLite 일일 백업
- 수집 원본 최소 1년 보존
- 월 1회 백업 복원 테스트
- DB와 raw 파일의 세트 백업

### 16.3 로그

구조화 로그 필드:

- timestamp
- run_id
- source_id
- region
- step
- status
- duration_ms
- item_count
- error_type
- message

금리 원문 전체를 로그에 반복 출력하지 않는다.

### 16.4 CLI

```bash
rate-monitor serve
rate-monitor collect --source fsb --region 26000
rate-monitor collect --all-enabled
rate-monitor collect --source kfcc_official --region 26000 --reference-check
rate-monitor import-reference --source kfcc_reference
rate-monitor reconcile --source-group kfcc
rate-monitor import data/inbox/file.xlsx --source fsb
rate-monitor validate --run <RUN_ID>
rate-monitor export --preset busan-12m-deposit
rate-monitor backup
```

---

## 17. 테스트 명세

### 17.1 단위 테스트

각 파서:

새마을금고 전용:

- 부산 구·군별 목록과 `gmgoCd/divCd` 파싱
- 동일 `gmgoCd` 다지점 중복 제거
- 거치식·적립식 전체 상품·기간
- 요구불예탁금 금액구간
- `.tblWrap/.tbl-tit/#divTmp1` 구조지문
- 알 수 없는 `divTmp*` 영역 원본 보존
- 공식·참고 JSON 비교키 안정성
- 기준일 불일치·금리 불일치 판정
- 생성된 모든 비동기 태스크가 종료 전 await되는지 검증
- 403/429 연속 시 회로차단기

공통:

- 정상 표본
- 헤더 위치 변경
- 빈 셀
- 합쳐진 셀
- 쉼표·퍼센트·한글 금리 문자열
- 다기간·다채널
- 금액구간
- 우대조건 원문
- 예상 구조 누락

정규화:

- 기관명 변형
- 지역명 변형
- 상품명 특수문자
- 동일 옵션 키 안정성

오버라이드:

- edit/add/hide/annotate
- 원본 변경 충돌
- 기간 만료
- 되돌리기

### 17.2 통합 테스트

```text
표본 원본
→ raw 저장
→ parse
→ normalize
→ institution/product/variant 생성
→ rate observation 저장
→ API 조회
→ override 생성
→ 재수집
→ conflict 확인
→ xlsx 검증
```

### 17.3 E2E 테스트

- 부산진구 12개월 정기예금 필터
- 최고금리 정렬
- 상세 우대조건 확인
- 기본금리 수정 및 사유 입력
- 재수집 후 수정 유지
- 원본 변경 시 충돌 표시
- 현재 화면 엑셀 다운로드

### 17.4 골든 데이터

- 실제 공식 표본을 익명화하지 않고 원본 그대로 보관할 수 있는지 정책 확인
- 원본을 저장할 수 없으면 구조를 재현한 최소 fixture와 SHA 기록
- 각 소스별 기대 기관 수·행 수·대표 금리값을 golden JSON으로 관리
- 새마을금고는 공식 HTML fixture와 같은 날짜의 참고 JSON fixture를 쌍으로 보관
- 최소 1개 동일값, 1개 불일치, 1개 공식누락, 1개 참고 stale 사례를 golden에 포함

---

## 18. 품질 게이트

### P0 완료

- [ ] 공식 소스 5종 정찰 문서 작성
- [ ] 저축은행·신협 실제 표본 확보
- [ ] 새마을금고 부산 목록·거치식·적립식·요구불 표본과 공개 참고 JSON 확보
- [ ] 농축협 수집 범위 판정
- [ ] 자동화 정책 상태 기록
- [ ] 새마을금고 공식 직접수집과 참고수입의 역할·우선순위 확정
- [ ] 기관 공식 코드 존재 여부 기록

### P1 완료

- [ ] SQLite 마이그레이션 재현
- [ ] 원본 추적률 100%
- [ ] 동일 표본 재수집 중복 0건
- [ ] 파서 구조 변경 감지
- [ ] 부산 기관 마스터와 수집완전도 계산
- [ ] 새마을금고 공식/참고 이중원천 비교와 불일치 검수

### P2 완료

- [ ] 4권역 통합 화면
- [ ] 부산 구·군 필터
- [ ] 기본·최고·우대폭 표시
- [ ] 우대조건 원문 열람
- [ ] 소스 최신성·완전도 표시
- [ ] 공식값·참고값 출처배지와 fallback 상태 표시
- [ ] 엑셀 내보내기

### P2.5 완료

- [ ] edit/add/hide/annotate
- [ ] 수정 사유 필수
- [ ] 재수집 후 수정 유지
- [ ] 충돌 검출·해결
- [ ] 편집 이력과 원본값 조회

### 최종 배포 게이트

- [ ] 테스트 전체 통과
- [ ] 실제 부산 표본 수기 대조 정확도 99% 이상
- [ ] 수집 실패 시 기존 정상값 유지
- [ ] 비밀키·개인정보 저장 없음
- [ ] 백업·복원 테스트
- [ ] README 실행 절차 검증

---

## 19. 구현 순서

### 세로 절단 1: 저축은행

1. DB·마이그레이션
2. collection run·raw artifact
3. 저축은행 파일 수입
4. 표준화·저장
5. 통합 그리드 최소 화면
6. 엑셀 출력

이 단계에서 전체 구조를 검증한다.

### 세로 절단 2: 새마을금고 우위 수집기

1. `kfcc_reference` 수입기로 부산 현재 데이터 부트스트랩
2. 공식 부산 구·군 목록 collector와 `gmgoCd/divCd` 기관·점포 적재
3. 공식 거치식·적립식 상세 collector
4. 공식 원본 HTML·구조지문·파서 버전 저장
5. 공개 상세 JSON과 자동 대조
6. 요구불예탁금·금액구간 collector
7. 우대금리·우대조건 추가 영역 정찰 및 확장
8. 회로차단기·fallback·출처배지 E2E 검증

### 세로 절단 3: 신협

- 지역·하위지역·가입방식
- 상세 우대조건

### 세로 절단 4: 농축협

- P0 결론에 맞는 프로파일
- 부분 커버리지와 미수집 기관 표시

### 세로 절단 5: 편집·이력

- 오버라이드
- 충돌
- 변경 이벤트
- 지역·기관 분석

---

## 20. 작업 분리 권장안

### 기반·통합 작업

- DB 모델과 마이그레이션
- 도메인 타입·식별키
- 수집 오케스트레이터
- API·웹 UI
- 오버라이드·충돌
- 통합 테스트·배포

### 독립 병렬 작업

- 저축은행 파서
- 새마을금고 공식 client·지역 파서·금리 파서
- 새마을금고 참고 JSON importer·reconciler
- 신협 파서
- 농축협 범용 파서
- 우대조건 파서
- 엑셀 내보내기

공유 계약은 `domain/schemas.py`, DB 모델, 수집기 프로토콜이다. 계약 변경은 명세와 마이그레이션을 먼저 수정한 뒤 구현한다.

---

## 21. 미확정 사항과 구현 기본값

| 항목 | 기본값 |
|---|---|
| 레포명 | `rate-monitor` |
| 지역 | 부산광역시 16개 구·군 |
| 은행 화면 | 벤치마크 토글 |
| 저축은행 원천 | 저축은행중앙회 1차, 금융감독원 교차검증 |
| DB | SQLite WAL |
| 프론트 | 서버 렌더링 + 경량 JS |
| 새마을금고 | 공식 직접수집 주원천 + 공개 JSON 검증원천 |
| 새마을금고 참고값 fallback | 기본 비활성, 사용 시 비공식 배지 필수 |
| 자동화 미검증 소스 | 비활성 또는 파일 모드 |
| 농축협 | 부분 수집 명시 |
| 원본 보존 | 최소 1년 |
| 시간대 | Asia/Seoul, DB는 UTC |
| 외부 공개 | 금지 기본 |

---

## 22. 착수 전 필수 산출물

- `docs/source-recon.md`: 소스별 실제 요청·정책·표본
- `docs/source-recon/kfcc.md`: 공식 요청프로파일·선택자·상품군 코드·정책 검토
- `docs/third-party/kfcc-reference.md`: 참고 저장소 파일구조·라이선스 상태·사용범위
- `tests/fixtures/<source>/`: 공식 표본
- `tests/golden/<source>.json`: 기대 결과
- `config/regions.yaml`: 부산 16개 구·군
- `docs/data-dictionary.md`: 테이블·필드 설명
- Alembic 초기 마이그레이션

이 산출물이 없으면 실제 수집기 구현을 시작하지 않는다. 특히 실물 표본 없이 HTML·엑셀 파서를 추정 구현하지 않는다.

---

## 23. 기존 공개 수집기 대비 우위 기술 정의

| 항목 | 공개 참고 수집기 | 본 시스템 v3 |
|---|---|---|
| 운영 의존성 | 제3자 GitHub Actions와 산출물 | 자체 스케줄러·자체 DB |
| 지역목록 | 코드에 하드코딩 | 공식 조회 동적 발견 + 행정구역 seed 대조 |
| 기관·지점 | 요약에서 본점 중심 | institution/outlet 분리 |
| 수집상품 | 거치식·적립식 중심 | 거치식·적립식·요구불 + 확장 프로파일 |
| 기간 | 상세에는 다기간, 요약은 12개월 | 전체 상품·전체 기간이 표준 비교단위 |
| 금리 | 기본이율 중심 | 기본·최고·우대조건을 분리, 미확인값 추정 금지 |
| 저장 | JSON/CSV 정적 산출물 | SQLite 시점이력·원본추적·변경이벤트 |
| 원본 | 캐시 중심 | 요청 메타·HTML·SHA·구조지문 100% 추적 |
| 장애 | 실행 결과 중심 | 이전 정상값 유지·partial·blocked·schema_changed |
| 검증 | 단일 수집결과 | 공식 직접수집 vs 공개 참고값 자동 대조 |
| 편집 | 없음 | 원본불변 오버라이드·충돌검출 |
| 화면 | 새마을금고 단일 비교 | 저축은행·신협·농축협과 통합 비교 |
| 요청제어 | 높은 병렬수집 가능 | 부산 저동시성·지터·백오프·회로차단기 |
| 확장성 | 정적 사이트 목적 | API·엑셀·HTTP·브라우저·수동파일 공통 계약 |

### 23.1 우위의 판단 기준

단순히 더 많은 데이터를 모으는 것이 우위가 아니다. 다음 네 조건을 모두 만족해야 한다.

1. **자립성**: 외부 프로젝트가 중단되어도 공식 직접수집이 계속된다.
2. **정확성**: 출처·기준일·기본/우대 금리를 혼합하지 않고 대조 가능하다.
3. **복구성**: 차단·구조변경·부분실패가 발생해도 이전 정상값과 원본을 보존한다.
4. **업무성**: 부산 구별 비교, 수기편집, 변경이력, 엑셀 보고까지 한 흐름으로 끝난다.

### 23.2 최종 완료 정의

새마을금고 모듈은 다음 상태일 때 완료로 판정한다.

```text
공식 사이트 직접수집 가능
+ 공개 참고데이터 없이도 독립 운영 가능
+ 공개 참고데이터와 자동 교차검증 가능
+ 실패·차단·구조변경 시 데이터 손실 없음
+ 부산 구별·상품별·기간별 통합 화면 제공
+ 기본금리와 우대정보의 출처·상태가 명확함
```
