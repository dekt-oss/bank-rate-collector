# 명세서: 2금융권 수신금리 통합 모니터 (rate-monitor)

- 상태: **draft** (아래 "freeze 전 확정 필요" 항목 해소 후 frozen 전환)
- 대상 레포: `dekt-oss/bank-rate-collector` — 경로 `docs/specs/20260805-rate-monitor.md`
- 관련 문서: 기획서 v2 (2026-08-05) / v1 (2026-08-05)

> **원칙**: 이 문서가 커밋되기 전에는 어떤 에이전트도 코드 작업을 시작하지 않는다. 계약(3장)은 Claude Code만 변경한다.

### freeze 전 확정 필요 (남은 1건)
1. ~~수집 지역 범위~~ — 기본값 채택: 부산 전 구·군 (+추가 지역은 `config.yaml`로 확장 가능)
2. ~~GitHub 레포명~~ — `dekt-oss/bank-rate-collector` 확정
3. **P0′ 정찰 결과 반영** — T3 소스 3종(새마을금고·신협·농협) 각각 자동/반자동 판정 미완. 판정 전까지 collector 3종은 "반자동(파일 파싱)" 가정으로 계약을 고정하고 진행

---

## 1. 목적 (한 줄)

저축은행·새마을금고·신협·지역농축협의 수신금리를 부산 구 단위까지 단일 스키마로 수집·비교·편집·엑셀 산출하는 로컬 웹앱.

---

## 2. 아키텍처 개요

### 모듈 구성

```
rate-monitor/
├─ app.py                    # 로컬 웹서버 진입점 (FastAPI + uvicorn, localhost:8000)
├─ config.yaml               # 수집 지역·우리회사 지정·경로 설정
├─ core/                     # [Claude Code] 뼈대·배선
│  ├─ models.py              #   ★ 계약 파일: RateRecord, Override, Snapshot 타입
│  ├─ store.py               #   스냅샷 저장/로드 (JSON, 날짜별)
│  ├─ overlay.py             #   원본 ⊕ 오버라이드 병합 + 충돌 감지
│  ├─ registry.py            #   collector 등록·실행 오케스트레이션
│  └─ api.py                 #   웹 API 라우트 (조회/수집/편집/내보내기)
├─ collectors/               # [Codex] 격리 수집·파싱 모듈 (순수 함수)
│  ├─ finlife_api.py         #   T1: 금감원 API → RateRecord[]
│  ├─ fsb_excel.py           #   T2: 저축은행중앙회 엑셀 5종 파서
│  ├─ kfcc.py                #   T3: 새마을금고 (반자동 가정)
│  ├─ cu.py                  #   T3: 신협 (반자동 가정)
│  └─ nh.py                  #   T3: 지역농축협 (반자동 가정)
├─ modules/                  # [Codex] 격리 변환 모듈 (순수 함수)
│  ├─ pref_parser.py         #   우대조건 텍스트 → 구조화
│  └─ xlsx_export.py         #   RateRecord[] → xlsx bytes
├─ web/                      # [Claude Code] 프론트 (정적 HTML+JS 단일 페이지)
│  └─ index.html
├─ data/
│  ├─ snapshots/YYYY-MM-DD.json
│  ├─ overrides.json
│  └─ inbox/                 #   T2/T3 수동 다운로드 파일 투입 폴더 (감시 대상)
└─ tests/                    # 소유권은 대상 모듈을 따름
```

### 데이터 흐름

```
[T1 finlife API] ──┐
[T2/T3 inbox 파일] ─┤→ collectors/* → RateRecord[] → store.py (스냅샷 저장)
                                                        ↓
                                     overlay.py (⊕ overrides.json)
                                                        ↓
                              api.py → web/index.html (조회·편집)
                                     → xlsx_export.py (다운로드)
```

핵심 설계 판단 (초심자용 설명):
- **collector는 전부 "입력 → RateRecord 배열"의 순수 함수**로 만든다. 순수 함수란 "같은 입력이면 항상 같은 출력, 바깥 세상(파일·전역변수)을 안 건드리는 함수"다. 이렇게 하면 각 collector를 저장·화면과 완전히 분리해 따로 만들고 따로 테스트할 수 있다 — 두 에이전트가 대화 없이 병렬 작업하는 전제 조건.
- **저장(스냅샷)과 편집(오버라이드)을 다른 파일로 분리**한다. 수집이 스냅샷을 덮어써도 편집 내용은 살아남는다.
- 웹서버는 배포용 서버가 아니라 브라우저가 로컬 파이썬과 대화하기 위한 통로일 뿐이다 (`python app.py` → `localhost:8000`).

---

## 3. 인터페이스 계약 (FREEZE — Claude Code만 변경)

### 3.1 공유 타입 (`core/models.py`)

```python
from dataclasses import dataclass, field
from typing import Literal, Optional

Sector = Literal["bank", "sb", "kfcc", "cu", "nh"]
# bank=은행, sb=저축은행, kfcc=새마을금고, cu=신협, nh=지역농축협

ProductType = Literal["deposit", "savings", "free_savings", "parking"]
# deposit=정기예금(예탁금), savings=정기적금, free_savings=자유적금, parking=입출금자유

JoinMethod = Literal["branch", "online", "any", "unknown"]

@dataclass
class PrefCondition:
    desc: str                      # 조건 설명 (예: "급여이체")
    add_rate: Optional[float]      # 가산 %p. 파싱 실패 시 None

@dataclass
class RateRecord:
    record_id: str                 # 결정적 키: make_record_id()로만 생성
    sector: Sector
    org_id: str                    # 규칙: f"{sector}:{region_sigungu}:{org_name}" 정규화
    org_name: str
    region_sido: str               # 예: "부산" (finlife 전국상품은 "전국")
    region_sigungu: str            # 예: "부산진구" (없으면 "")
    product_type: ProductType
    product_name: str
    term_months: Optional[int]     # parking은 None
    base_rate: float               # 기본금리 %
    max_rate: float                # 최고금리 % (우대 미공시 시 base와 동일)
    pref_conditions: list[PrefCondition] = field(default_factory=list)
    pref_conditions_raw: str = ""  # 우대조건 원문 (항상 보존)
    join_method: JoinMethod = "unknown"
    source: str = ""               # "finlife" | "fsb_excel" | "kfcc" | "cu" | "nh"
    source_url: str = ""
    as_of: str = ""                # 공시 기준일 "YYYY-MM-DD", 불명 시 ""
    collected_at: str = ""         # 수집 시각 ISO8601 (registry가 채움, collector는 비움)

def make_record_id(r: RateRecord) -> str: ...
# sha1(f"{sector}|{org_id}|{product_name}|{term_months}|{join_method}")[:16]
# 구현·변경 권한: Claude Code. Codex는 호출만 한다.

@dataclass
class Override:
    record_id: str
    action: Literal["edit", "add", "hide", "memo"]
    field_name: Optional[str]      # action=edit일 때 대상 필드
    value: Optional[str]           # 새 값 (문자열 직렬화)
    original_value: Optional[str]  # 오버라이드 생성 시점의 원본값 (충돌 감지 기준)
    memo: str = ""
    created_at: str = ""
    added_record: Optional[RateRecord] = None   # action=add일 때
```

### 3.2 collector 계약 (Codex 구현 대상)

모든 collector는 아래 시그니처를 지키는 **순수 함수**다. 파일을 직접 읽지 않는다 — bytes/str을 받는다. 네트워크를 직접 부르지 않는다 — T1은 응답 JSON을 받는다. (I/O는 전부 `registry.py`가 담당)

```python
# collectors/finlife_api.py
def parse_finlife(resp_json: dict, product_type: ProductType) -> list[RateRecord]: ...

# collectors/fsb_excel.py  (저축은행중앙회 엑셀 5종)
def parse_fsb_excel(content: bytes, screen: Literal[
    "deposit", "savings", "parking", "midrate_loan", "biz_loan"
]) -> list[RateRecord]: ...
# v2 범위는 deposit/savings/parking만 화면에 사용. loan 2종은 파싱만 하고 미표시.

# collectors/kfcc.py, cu.py, nh.py  (T3 — 반자동 가정: 저장된 파일을 파싱)
def parse_kfcc(content: bytes, filename: str) -> list[RateRecord]: ...
def parse_cu(content: bytes, filename: str) -> list[RateRecord]: ...
def parse_nh(content: bytes, filename: str) -> list[RateRecord]: ...
# filename은 지역·상품유형 추정 힌트로만 사용. 
# P0' 결과 자동화 가능 판정 시: fetch 함수를 계약에 추가(Claude Code가 spec 갱신 후) 
```

공통 규칙 (collector 구현 시 준수):
- 반환 레코드의 `record_id`는 `make_record_id()` 호출로 채운다 (직접 조립 금지)
- 금리 파싱 실패 행은 버리지 말고 `base_rate=-1.0`으로 표기해 반환 (검수 화면에서 노출)
- `pref_conditions_raw`는 어떤 경우에도 원문 그대로 보존
- `collected_at`은 비워서 반환 (registry가 채움)
- 알 수 없는 컬럼 구조를 만나면 예외를 던지지 말고 `CollectorResult`가 아닌 빈 리스트 + 로그 대신, **`ParseError` 예외를 던진다** — registry가 잡아서 사용자에게 "파일 구조 변경됨"을 알린다

```python
class ParseError(Exception):
    """공시 파일/응답 구조가 예상과 다를 때. message에 어긋난 지점 명시."""
```

### 3.3 변환 모듈 계약 (Codex)

```python
# modules/pref_parser.py
def parse_pref_text(raw: str) -> list[PrefCondition]: ...
# "급여이체 시 0.2%p, 카드실적 30만원 이상 0.3%p" → 구조화 시도.
# 실패 항목은 PrefCondition(desc=원문조각, add_rate=None)으로 반환. 예외 금지.

# modules/xlsx_export.py
def export_xlsx(records: list[RateRecord], overrides: list[Override],
                sheets: list[Literal["raw", "by_org", "by_region", "diff"]]) -> bytes: ...
# 오버라이드 반영값 기준. edit된 셀은 배경색 표시. diff 시트는 P3 전까지 미구현 허용(빈 시트).
```

### 3.4 웹 API (Claude Code 소유 — Codex는 의존하지 않음)

```
GET  /api/records?snapshot=YYYY-MM-DD&sector=&sido=&sigungu=&product_type=&term=&q=
POST /api/collect            # T1 즉시 수집 + inbox 재파싱 → 새 스냅샷
GET  /api/snapshots          # 저장된 스냅샷 목록
POST /api/overrides          # Override 추가
DELETE /api/overrides/{id}
GET  /api/export.xlsx?<동일 필터>
```

---

## 4. 파일·모듈 소유권 표

| 경로 | 소유 | 설명 |
|---|---|---|
| `app.py`, `config.yaml` | Claude Code | 진입점·설정 |
| `core/models.py` | Claude Code | **계약 파일. Codex는 import만** |
| `core/store.py`, `core/overlay.py`, `core/registry.py`, `core/api.py` | Claude Code | 뼈대·배선·I/O 전담 |
| `web/index.html` | Claude Code | 프론트 |
| `collectors/finlife_api.py` | Codex | T1 파서 |
| `collectors/fsb_excel.py` | Codex | T2 파서 |
| `collectors/kfcc.py`, `cu.py`, `nh.py` | Codex | T3 파서 3종 |
| `modules/pref_parser.py`, `modules/xlsx_export.py` | Codex | 변환 모듈 |
| `tests/test_collectors_*.py`, `tests/test_modules_*.py` | Codex | 자기 모듈 테스트 |
| `tests/test_core_*.py`, `tests/fixtures/` 배치 | Claude Code | 통합 테스트·픽스처 관리 |

공유 파일: **0개.** `core/models.py`는 인터페이스 파일이며 Claude Code 단독 소유.

---

## 5. 작업 분할

### Claude Code 태스크
- [ ] 레포 초기화, 디렉토리 골격, `config.yaml` 스키마
- [ ] `core/models.py` 확정 (3.1) → **freeze 커밋** (이후 병렬 착수 신호)
- [ ] `make_record_id()` 구현 + 안정성 테스트 (같은 입력 → 항상 같은 id)
- [ ] `store.py`: 날짜별 스냅샷 저장/로드, 평탄 레코드 배열 포맷
- [ ] `overlay.py`: 병합 + 충돌 감지 (원본값 ≠ override.original_value → conflict 플래그)
- [ ] `registry.py`: finlife HTTP 호출, inbox 폴더 스캔 → 파일을 collector에 bytes로 전달, 결과 취합, collected_at 스탬프, ParseError 사용자 알림
- [ ] `api.py` 라우트 6종 + `app.py`
- [ ] `web/index.html`: 필터(권역·시도·시군구·상품·기간·검색), 정렬, 우리회사 강조, 인라인 편집, 오버라이드 일람, 스냅샷 선택, 지금수집 버튼, 엑셀 다운로드
- [ ] 통합 테스트: 픽스처 파일 → 수집 → 병합 → API 응답 end-to-end
- [ ] **최종 통합** (Codex 브랜치 머지)

### Codex 태스크
- [ ] `parse_finlife` (상품유형별 응답 → RateRecord)
- [ ] `parse_fsb_excel` (5개 화면 엑셀. 헤더 행 위치 자동 탐지 포함)
- [ ] `parse_kfcc` / `parse_cu` / `parse_nh` (P0′ 확보 표본 파일 기준)
- [ ] `parse_pref_text` (정형 패턴 5종 이상 + 실패 시 원문 보존)
- [ ] `export_xlsx` (시트 3종 + 수정 셀 표시)
- [ ] 각 모듈 단위 테스트 (픽스처는 `tests/fixtures/`의 실물 표본 사용)
- [ ] 마지막: **read-only 검증** `/codex:adversarial-review` (통합 코드 대상, 쓰기 없음)

---

## 6. 통합 지점 & 순서

1. Claude Code: 3장 계약 + `core/models.py` 확정 → **freeze** → `spec: rate-monitor` 커밋
2. **선행 조건**: P0(망분리 확인) + P0′(T3 표본 파일 확보)이 끝나 `tests/fixtures/`에 실물 표본이 있어야 Codex 착수 가능 — 표본 없이 파서를 만들면 상상으로 만들게 됨
3. 병렬: Claude Code(뼈대·UI) / Codex(파서·변환 모듈) 각자 브랜치에서 구현
4. Claude Code: wiring — registry에 collector 등록, API·UI 연결, 통합 커밋
5. Codex: read-only adversarial review
6. 계약 변경 필요 시: Codex는 코드로 우회하지 않고 에스컬레이션 → Claude Code가 spec 갱신(`spec: rate-monitor (contract update)`) 후 재동기화

---

## 7. 검증 기준

- 단위: 각 collector가 표본 파일에서 기대 행 수·기대 금리값을 정확 추출 (픽스처별 golden 값 비교)
- 결정성: `make_record_id` — 동일 레코드 재수집 시 id 불변 (오버라이드·시점비교의 전제)
- 병합: 오버라이드 edit/add/hide/memo 각각 반영 + 충돌 케이스 1건 재현 테스트
- E2E: `python app.py` → 브라우저에서 부산 구 필터 → 4권역 레코드 표시 → 셀 수정 → 엑셀 다운로드에 수정값+표식 반영
- read-only 리뷰 대상: `core/overlay.py`(데이터 무결성 최위험), `core/registry.py`(I/O 경계)

## 8. Definition of Done (P2.5 기준)

- [ ] 부산 전 구·군 범위, 4권역(저축은행·새마을금고·신협·농축협) 수신 레코드가 한 화면에 표시
- [ ] 구 단위 필터 동작 (예: "부산진구"만 선택 시 해당 소재 기관만)
- [ ] 모든 행에 기본금리·최고금리·우대폭 표시, 우대조건 원문 열람 가능
- [ ] 셀 수정 → 재수집 후에도 수정 유지, 원본 변경 시 충돌 표시
- [ ] 필터 상태 그대로 xlsx 다운로드 (수정 셀 표식 포함)
- [ ] T2/T3 수동 파일을 inbox에 넣으면 다음 수집 때 자동 병합

## 9. 리스크 / 열린 질문 (가정으로 두고 진행)

- **T3 자동화 판정 전** collector 3종은 "저장된 파일 파싱" 계약으로 고정. 자동화 확정 시 fetch 함수 추가는 contract update로 처리 — 파서 코드는 재사용되므로 낭비 없음
- 새마을금고 기관 식별: 중앙회 코드 존재 여부 미확인 → 임시 규칙 `sector:시군구:정규화된금고명` 사용, 통폐합 발생 시 org alias 테이블(P4) 검토
- 농축협 수신 공시 화면의 필드 구성 미확인 → `parse_nh`는 P0′ 표본 확보 후 착수 (5장 Codex 태스크 중 가장 후순위)
- 우대조건 구조화율 목표 미설정 → P1 종료 시 실측 후 "구조화율 ≥ 60%" 여부로 우대조건 필터 기능 존치 결정
- 여신(loan) 파서 2종은 구현하되 API·UI 미노출 (v2 범위 밖)
