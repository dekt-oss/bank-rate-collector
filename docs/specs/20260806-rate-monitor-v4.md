# 금리수집기 우선기능 재정비 및 확장 작업 명세서 v4
## 저축은행·새마을금고·농·축협·신협 중심 비교 / 시중은행·기준금리 참고지표

```yaml
document_type: implementation_spec
status: current
date: 2026-08-06
target_repository: dekt-oss/bank-rate-collector
target_agent: Claude Code
supersedes_product_priority: docs/specs/20260805-rate-monitor-v3.1.md의 화면·우선순위 계약
inherits_architecture_from: docs/specs/20260805-rate-monitor-v3.1.md
prerequisite: docs/specs/20260806-storage-prerequisite-v1.md
```

> **저장소 반영 메모** (2026-08-06)
>
> 이 문서는 v3.1을 **폐기하지 않는다.** 데이터 계약·식별체계·스냅샷·게이트는
> v3.1이 그대로 기준이고, v4는 **화면과 우선순위**를 바꾼다. 두 문서가
> 부딪히면 화면·우선순위는 v4, 나머지는 v3.1이다.
>
> 선행 조건인 저장소 정리는 끝났다 — `rate-data`가 177.67 → 74.41 MiB로
> 줄었고(PR #23), 상태 DB를 R2로 옮길 3단계 전환 경로가 생겼다(PR #24,
> 현재 `github_legacy`). §12의 워크플로우 설계는 그 위에 얹힌다.
>
> §5(농·축협)의 전제 하나가 기존 저장소 기록과 어긋난다.
> `docs/source-recon/nh-local.md`는 "중앙 수집 불가"라고 적고 있었는데
> **그 판정이 틀렸다.** 정정 내용은 그 문서 §0에 있다.

---

## 0. Claude Code 작업 지시

이 문서는 현재 구현을 폐기하고 새로 만드는 명세가 아니다.

먼저 `main` 브랜치의 실제 코드와 테스트를 읽고, 이미 구현된 부분은 재사용·확장한다.  
특히 다음은 현재 저장소에 존재하므로 중복 구현하지 않는다.

```text
src/rate_monitor/collectors/finlife/
src/rate_monitor/collectors/fsb/
src/rate_monitor/collectors/kfcc/
src/rate_monitor/collectors/cu/
src/rate_monitor/db/
src/rate_monitor/services/
.github/workflows/ci.yml
.github/workflows/collect.yml
web/templates/
```

`docs/roadmap.md`와 과거 완료기록에는 현재 코드와 어긋난 내용이 있을 수 있다.  
문서의 “미구현” 문구보다 실제 파일·테스트·Actions 실행 결과를 우선한다.

작업 원칙:

1. `main`에 직접 대규모 변경하지 말고 기능 단위 브랜치와 PR로 나눈다.
2. 원천 표본 없이 파서를 추정 구현하지 않는다.
3. 로그인 우회, CAPTCHA 우회, IP 차단 우회는 하지 않는다.
4. 운영 수집에 사용자의 파일 다운로드·업로드 절차를 넣지 않는다.
5. 실패한 수집이 마지막 정상 데이터를 빈값으로 대체하지 않게 한다.
6. 수집값이 없는 필드는 추정하거나 다른 필드로 메우지 않는다.
7. 코드 변경 전에 이 문서를 바탕으로 `docs/specs/20260806-rate-monitor-v4.md`를 만들고 `docs/specs/CURRENT.md`를 갱신한다.
8. 각 PR 설명에 실제 구현, 실측 검증, 미해소 사항을 구분해 적는다.

---

# 1. 제품 목표 재정의

## 1.1 전면에 내세울 핵심 서비스

메인 화면과 핵심 비교기능은 다음 네 업권의 수신상품 금리비교다.

```text
저축은행
새마을금고
농·축협
신협
```

이 네 업권을 동일한 표에 억지로 평탄화하지 않는다. 공통 비교필드는 통합하되, 원천별 범위와 제공 수준을 명확히 표시한다.

핵심 사용 질문:

```text
내가 선택한 지역에서 가입하거나 확인할 수 있는 예금·적금 중
기본금리와 최고 우대금리가 높은 상품은 무엇인가?

부산에서는 어느 구·군의 어느 금융기관·점포에서 취급하는가?

우대금리를 받으려면 어떤 조건을 충족해야 하는가?
```

## 1.2 참고정보

다음은 메인 비교대상이 아니라 판단을 돕는 참고정보로 제공한다.

```text
한국은행 기준금리
시중은행 정기예금·적금 금리 요약
```

시중은행 상세 레코드는 DB에 저장하되 메인 비교표의 기본 업권에는 포함하지 않는다.

메인 화면에서는 다음 정도만 노출한다.

```text
한국은행 기준금리
시중은행 12개월 정기예금 기본금리 범위
시중은행 12개월 정기예금 최고금리 범위
최근 갱신일
```

사용자가 참고카드를 눌러도 P2 단계에서는 별도 상세표를 만들지 않는다.  
상세 데이터는 SQLite와 CSV/JSON 내보내기에만 보존한다.

## 1.3 이번 단계의 우선순위

```text
P0  문서·현황 정합성 복구
P1  농·축협 공식 중앙 수집원 기술검증 및 수집기
P2  시중은행 finlife 수집 확장
P3  한국은행 기준금리 수집
P4  네 업권 통합 비교 데이터셋
P5  지역·부산 구·군 UI 및 우대금리 표시 강화
P6  Actions 자동화·게이트·운영 검증
```

---

# 2. 범위

## 2.1 반드시 구현

- 저축은행·새마을금고·농·축협·신협을 메인 업권으로 표시
- 금융기관별 필터
- 상품 유형별 필터
- 상품명 검색
- 가입기간 필터
- 가입채널 필터
- 단리·복리 필터
- 시도 필터
- 부산 선택 시 16개 구·군 필터
- 기본금리
- 최고 우대금리
- 기본금리 대비 우대폭
- 우대조건 원문
- 원천 기준일
- 마지막 수집시각
- 데이터 범위·지역근거 표시
- 시중은행 데이터 자동수집 및 DB 저장
- 한국은행 기준금리 자동수집 및 DB 저장
- 농·축협 공식 중앙 금리조회 자동수집
- 수집 실패 시 마지막 정상값 유지
- GitHub Actions 무인 실행
- fixture 기반 CI

## 2.2 이번 단계에서 제외

- 수기 파일 업로드 운영
- 사용자 직접 데이터 수정
- 로그인·본인인증이 필요한 데이터 수집
- 대출상품
- 보험·펀드·카드
- 실시간 금리 알림
- 회원가입
- 개인화 추천
- 모바일 앱
- 모든 우대조건을 기계적으로 완전 판정하는 기능
- 시중은행 상세 비교화면
- 한국은행 모든 거시지표 수집

---

# 3. 원천별 데이터 계약

## 3.1 원천 우선순위

```text
1. 공식 API
2. 공식 중앙 홈페이지의 공개 HTTP/JSON/HTML 조회
3. 공식 중앙 다운로드
4. 공개 브라우저 세션 자동화
5. 제3자 데이터는 교차검증용
```

운영 정상경로에 사용자의 수동 파일 처리를 넣지 않는다.

## 3.2 원천별 역할

| 업권 | 1차 원천 | 보조 원천 | 화면 역할 |
|---|---|---|---|
| 저축은행 | 저축은행중앙회 FSB | finlife | 메인 |
| 새마을금고 | 새마을금고 공식 금고위치·금리조회 | 공개 참고저장소는 검증만 | 메인 |
| 농·축협 | NH농협 금융상품몰 농·축협별 예금금리 | 개별 조합 홈페이지는 사용하지 않음 | 메인 |
| 신협 | 신협중앙회 예금 금리비교 AJAX | 없음 | 메인 |
| 시중은행 | finlife 오픈API `020000` | 없음 | 참고·DB |
| 한국은행 기준금리 | 한국은행 ECOS Open API | 한국은행 공식 기준금리 화면 | 참고·DB |

## 3.3 데이터 제공 수준

| 원천 | 지역 기준 | 기본금리 | 최고 우대금리 | 우대조건 |
|---|---|---:|---:|---:|
| FSB 저축은행 | 가입 가능 시도 + 본점 기준 | 있음 | 있음 | 있음 |
| 새마을금고 | 점포 주소로 시도·구군 판정, 금리는 금고 단위 | 있음 | 공식 열 없음 | 공식 열 없음 |
| 농·축협 | 점포 주소, 상세화면은 점포 단위로 우선 저장 | 실측 필요 | 실측 필요 | 비고·우대항목 실측 필요 |
| 신협 | 공식 조회지역 조건, 조합 단위 | 있음 | 있음 | 있음 |
| finlife 시중은행 | 전국 공시 | 있음 | 있음 | 있음 |
| 한국은행 | 전국 단일 지표 | 해당 없음 | 해당 없음 | 해당 없음 |

중요:

- `max_rate`가 원천에 없으면 `NULL`이다.
- `max_rate = base_rate`로 임의 보정하지 않는다.
- 우대조건이 없으면 “우대조건 없음”으로 단정하지 않고 `원천 미제공`으로 표시한다.
- 금리 적용 범위가 다른 자료를 같은 의미로 표시하지 않는다.

---

# 4. 지역 모델과 필터 계약

## 4.1 지역을 한 종류로 취급하지 않는다

현재 원천별 지역 의미가 다르므로 다음 열거형을 추가한다.

```python
class GeoBasis(StrEnum):
    OUTLET_ADDRESS = "outlet_address"
    INSTITUTION_ADDRESS = "institution_address"
    SOURCE_QUERY_REGION = "source_query_region"
    AVAILABILITY_REGION = "availability_region"
    HEAD_OFFICE = "head_office"
    NATIONWIDE = "nationwide"
    NONE = "none"
```

의미:

| 값 | 의미 |
|---|---|
| `outlet_address` | 실제 점포 주소에서 파생 |
| `institution_address` | 기관 본점 주소에서 파생 |
| `source_query_region` | 공식 사이트 조회조건으로만 확인 |
| `availability_region` | 해당 지역에서 가입 가능하다는 공식 필터 |
| `head_office` | 본점 기준 공시 |
| `nationwide` | 전국 단일 공시 |
| `none` | 지역근거 없음 |

## 4.2 DB 마이그레이션

`institutions`와 `outlets`에 표시용 지역명을 추가한다.

```text
region_sido       TEXT NULL
region_sigungu    TEXT NULL
geo_basis         TEXT NOT NULL DEFAULT 'none'
geo_confidence    REAL NULL
```

공식 행정구역 코드 필드는 기존대로 별도 유지한다.

```text
sido_code
sigungu_code
```

주소 문자열을 파싱했다고 공식 행정구역 코드를 추정 입력하지 않는다.

권장 인덱스:

```sql
CREATE INDEX ix_institutions_region
ON institutions(sector, region_sido, region_sigungu);

CREATE INDEX ix_outlets_region
ON outlets(region_sido, region_sigungu);
```

## 4.3 부산 구·군 필터

부산 선택 시 다음 16개 구·군을 표시한다.

```text
강서구
금정구
기장군
남구
동구
동래구
부산진구
북구
사상구
사하구
서구
수영구
연제구
영도구
중구
해운대구
```

단, 원천이 구·군 근거를 제공할 때만 적용한다.

| 업권 | 부산 구·군 필터 |
|---|---|
| 새마을금고 | 가능 — 점포 주소 |
| 농·축협 | 가능 — 검색결과 점포 주소 |
| 신협 | 제한적 — 공식 하위지역 조회조건, 실제 점포 주소로 표현 금지 |
| 저축은행 | 불가 — 본점 기준/시도 가입가능 필터 |
| 시중은행 참고 | 불가 — 전국 공시 |

UI 규칙:

- 저축은행에서 부산 구를 선택하면 결과가 없는 것처럼 보이지 않게 필터를 비활성화한다.
- 비활성화 사유를 `본점 기준 공시로 구·군별 금리를 제공하지 않음`이라고 표시한다.
- 신협은 `소재지`가 아니라 `공식 조회지역`으로 표시한다.
- 농·축협 검색어 `부산` 결과에 기관명만 부산이고 주소가 경남인 점포가 포함될 수 있으므로 반드시 실제 주소로 재필터링한다.

---

# 5. 농·축협 수집기 명세

## 5.1 공식 화면

사용자가 비로그인 상태에서 확인한 공식 흐름:

```text
SFDPW0160R.view  농·축협별 예금금리 검색
SFDPW0161R.view  농·축협·점포 검색 결과
SFDPW0162R.view  점포별 금리 상세
```

상품 분류:

```text
입출금
예금(거치식)
적금(적립식)
```

검색 결과 필드:

```text
농·축협명/지점명
주소
전화번호
금리조회 동작
```

상세 화면 필드:

```text
농·축협·지점명
원천 기준일
상품명
기간 또는 금액구간
금리
비고
변동금리 여부
```

## 5.2 선행 정찰

아직 정확한 HTTP 계약은 저장소에 확정되지 않았다.  
파서를 먼저 만들지 말고 다음을 자동 정찰한다.

```text
scripts/p2_nh_local_recon.py
docs/source-recon/nh-local-v2.md
docs/source-recon/nh-local-recon-v2.json
tests/fixtures/nh_local/
```

확인 항목:

1. 최초 GET에서 필요한 세션 쿠키
2. 검색 버튼의 실제 method와 payload
3. 목록의 페이지네이션 파라미터
4. 검색 총건수
5. 농·축협 기관 식별자
6. 점포 식별자
7. 금리조회 버튼의 hidden input 또는 JavaScript 인수
8. 상세조회 method와 payload
9. 세 상품분류 탭이 별도 요청인지 동일 HTML인지
10. 기준일 필드
11. 기본금리와 최고금리 구분 가능 여부
12. 우대조건·비고 필드
13. GitHub Actions에서 동일 요청 재현 가능 여부
14. 공개 이용약관 및 자동접근 정책
15. 검색결과에 개인정보성 담당자 정보가 포함되는지

표본은 최소 다음을 확보한다.

```text
부산광역시 주소의 농협 본점 1건
부산광역시 주소의 지점 1건
기관명에 부산이 있지만 주소는 타 시도인 점포 1건
거치식예금 상세 1건
적립식예금 상세 1건
입출금 상세 1건
```

## 5.3 수집 범위

1차 운영범위는 부산이다.

```text
검색어 후보:
부산
부산광역시
부산 16개 구·군명
```

각 검색 결과의 합집합을 만들고 실제 주소로 다음을 적용한다.

```text
주소 시도 == 부산광역시
```

기관명에 `부산`이 들어가더라도 주소가 경남이면 부산 데이터에서 제외한다.

완전성 검증:

```text
부산 검색 결과
∪ 부산광역시 검색 결과
∪ 16개 구·군 검색 결과

→ 점포 식별자로 중복 제거
→ 신규 점포가 더 이상 늘지 않는지 확인
```

전국 수집은 부산 E2E 통과 후 별도 게이트로 확장한다.

## 5.4 구현 구조

```text
src/rate_monitor/collectors/nh_local/
├── __init__.py
├── adapter.py
├── client.py
├── parser.py
└── selectors.py

tests/
├── fixtures/nh_local/
├── test_nh_local_parser.py
└── test_nh_local_collection.py
```

어댑터 동작:

```text
create public session
→ search outlets
→ save raw list HTML/JSON
→ parse institution/outlet identifiers
→ deduplicate outlets
→ fetch each outlet detail
→ save raw detail HTML
→ parse three product categories
→ normalize
→ persist
```

## 5.5 식별체계

가능하면 공식 hidden 값 또는 요청 파라미터를 사용한다.

```text
institution source key = 공식 농·축협 코드
outlet source key      = 공식 점포 코드
product source key     = 공식 상품 코드
```

공식 코드가 없을 때만 임시 해시를 사용한다.

```text
institution fallback key:
normalize(institution_name)

outlet fallback key:
sha256(normalized institution name + normalized outlet name + normalized address)

product fallback key:
sha256(outlet key + product category + normalized product name)
```

주소나 이름이 바뀌어 이력이 끊길 수 있으므로 fallback 사용 레코드는 `review_items`에 남긴다.

## 5.6 금리 해석

첫 구현에서는 상세화면 제목이 점포명까지 포함되므로 다음처럼 저장한다.

```text
rate_scope = outlet
product_variant.outlet_id = 해당 점포
```

같은 농·축협의 모든 지점이 동일 금리라는 실측이 확보되기 전에는 기관 단위로 합치지 않는다.

기간·금액 구간:

```text
계약기간 → term_months / term_days
금액구간 → amount_min / amount_max
```

비고에 우대조건이 있으면 원문을 보존한다.

```text
raw_preference_text = 공식 비고/우대조건 원문
```

화면에 금리가 하나만 있으면:

```text
base_rate = 해당 금리
max_rate = NULL
```

명확히 `기본금리`, `최고금리`, `우대금리`가 분리돼 있을 때만 각각 매핑한다.

## 5.7 수집 부하

- 기본 요청 간격 1초
- 동시성 기본 1
- 429·5xx는 지수 백오프
- 한 점포 실패가 전체 수집을 즉시 폐기하지는 않되 `partial`로 기록
- 점포 목록 자체가 급감하면 전체 실행을 실패 처리하고 이전 정상값 유지
- 개발 초기 전국 1,100개 점포 일괄실행 금지
- 부산 실제 점포수·요청수·소요시간을 먼저 실측

## 5.8 농·축협 완료 게이트

```text
비로그인 세션으로 Actions 수집 성공
부산 점포 목록 원본 저장
주소가 부산이 아닌 검색결과 제외 확인
기관·점포 공식키 또는 fallback 상태 확인
거치식·적립식 최소 1개 이상 파싱
금리 NULL 비율 보고
기준일 파싱률 보고
원본 추적률 100%
같은 표본 재수집 시 기관·점포·상품 중복 증가 0
동일 run 내 variant observation 중복 0
구·군 파싱률 95% 이상
구·군 미파싱은 review_items 생성
마지막 정상값 보호 테스트
```

---

# 6. 시중은행 수집 확장 명세

## 6.1 난이도

새 수집기를 처음부터 만들지 않는다.  
기존 finlife 어댑터와 파서가 이미 `020000=은행`, `030300=저축은행`을 구분할 수 있으므로 구성과 소스 ID를 분리하는 작업이다.

## 6.2 소스 분리

현재 단일 `source_id="finlife"` 구조를 다음처럼 분리한다.

```text
finlife_savings_bank
finlife_bank
```

호환성 처리:

- 기존 `finlife` 레코드를 삭제하지 않는다.
- 기존 레코드가 저축은행임을 확인한 뒤 마이그레이션 또는 source alias로 연결한다.
- 이미 발행된 DB를 새 마이그레이션에서 안전하게 변환한다.
- 파서의 전역 `SOURCE_ID` 하드코딩을 요청 컨텍스트 또는 어댑터 인자로 바꾼다.

권장 구조:

```python
FinlifeAdapter(
    source_id="finlife_bank",
    sector=Sector.BANK,
    groups=("020000",),
    source_role=SourceRole.SECONDARY_OFFICIAL,
)
```

저축은행:

```python
FinlifeAdapter(
    source_id="finlife_savings_bank",
    sector=Sector.SAVINGS_BANK,
    groups=("030300",),
)
```

## 6.3 수집 범위

```text
depositProductsSearch
savingProductsSearch
companySearch
topFinGrpNo=020000
```

저장 필드:

```text
은행명
상품명
가입기간
단리·복리
가입방법
기본금리
최고금리
우대조건 원문
가입대상
가입제한
최고한도
공시일
```

시중은행은 전국 공시로 저장한다.

```text
rate_scope = nationwide
geo_basis = nationwide
```

finlife의 `companySearch` 지역정보는 시도별 점포 존재 여부이며 상품별 지역금리가 아니다.  
시중은행 금리 레코드를 부산 구·군에 연결하지 않는다.

## 6.4 화면 노출

> **정정 (2026-08-06, 사용자 결정)**
>
> 아래 원문은 시중은행을 메인 비교표에서 뺐다. **사용자가 넣기로 정했다.**
> 시중은행도 메인 비교표에 선다.
>
> 원문을 지우지 않는 이유는 이 저장소의 규칙이다 — 판정이 바뀌어도 원문을
> 남긴다. 지운 자리에는 같은 판단을 다시 하게 된다.
>
> **뺐던 이유는 여전히 유효하다.** 시중은행 행은 `rate_scope=nationwide`,
> `geo_basis=nationwide`, `region_sido`가 비어 있다. 점포 주소로 얻은
> 새마을금고 행과 같은 줄에 서면 "부산 금리"를 비교하는 것처럼 보인다.
> 그래서 넣되 **조건을 단다.**
>
> 1. 지역근거 배지(`전국 공시`)를 반드시 함께 표시한다. 배지 열을 빼면
>    이 결정은 그 순간부터 사람을 오도한다.
> 2. 시도 필터를 걸어도 전국 공시 행은 남긴다. 전국 공시는 그 시도에서도
>    가입할 수 있다는 뜻이지 "지역 정보가 없어서 해당 없음"이 아니다.
>    구·군 필터의 `GU_EXACT` 규칙(§10.3)과 같은 취지다.
> 3. §6.3의 「시중은행 금리 레코드를 부산 구·군에 연결하지 않는다」는
>    **그대로다.** 표에 세우는 것과 구에 귀속시키는 것은 다른 일이다.
>
> 참고카드(§10.6)는 그대로 둔다. 카드의 「12개월 정기예금 중앙값」은
> 표의 한 행과 다른 질문에 답한다.

시중은행 상세 전체표는 DB에만 저장한다.

메인 참고카드 계산:

```text
대상: 12개월 정기예금
기준금리: base_rate
최고금리: max_rate
집계: 최솟값 / 중앙값 / 최댓값
공시일: 최신 source_effective_at
```

이상치가 참고카드를 왜곡하지 않도록 다음을 함께 계산한다.

```text
record_count
institution_count
p10
median
p90
max
```

메인에는 기본적으로 `median`, `max`, `record_count`만 표시한다.

## 6.5 시중은행 완료 게이트

```text
finlife_bank source 생성
020000 정기예금·적금 실제 수집
기존 저축은행 source와 레코드 혼합 0
은행 레코드 sector=bank 100%
rate_scope=nationwide 100%
우대조건 원문 추적
참고카드 집계와 SQL 검산 일치
```

`대시보드 메인 비교표 기본 데이터에서 bank 제외`는 §6.4 정정으로 뒤집혔다.
대신 이것을 검사한다.

```text
bank 행에 전국 공시 배지가 붙는다
시도 필터를 걸어도 bank 행이 남는다
bank 행의 region_sigungu 가 채워진 것 0건
```

---

# 7. 한국은행 기준금리 수집 명세

## 7.1 별도 지표 모델

기준금리를 금융상품으로 저장하지 않는다.  
다음 테이블을 신규 추가한다.

```sql
CREATE TABLE market_indicators (
    id TEXT PRIMARY KEY,
    indicator_code TEXT NOT NULL,
    indicator_name TEXT NOT NULL,
    source_id TEXT NOT NULL REFERENCES sources(id),
    observed_at DATETIME NOT NULL,
    source_effective_at DATE,
    value TEXT NOT NULL,
    unit TEXT NOT NULL,
    raw_artifact_id TEXT NOT NULL REFERENCES raw_artifacts(id),
    source_locator TEXT,
    content_hash TEXT NOT NULL,
    validation_status TEXT NOT NULL DEFAULT 'valid',
    UNIQUE(indicator_code, source_effective_at, source_id)
);
```

기준금리 코드:

```text
indicator_code = bok_base_rate
indicator_name = 한국은행 기준금리
unit = percent
```

## 7.2 원천

1차는 한국은행 ECOS Open API다.

필요 환경변수:

```text
BOK_ECOS_API_KEY
```

구현 전에 실제 ECOS 통계표 코드·항목 코드·주기·응답 구조를 정찰한다.  
확인하지 않은 통계코드를 명세에 추정 하드코딩하지 않는다.

선행 산출물:

```text
scripts/p2_bok_ecos_recon.py
docs/source-recon/bok-ecos.md
tests/fixtures/bok_ecos/
```

확인사항:

```text
통계표 코드
항목 코드
일별/월별 주기
적용일
정책금리 변경일의 반영 시차
최신값 조회 방법
공식 기준금리 화면과 값 대조
```

## 7.3 수집 주기

기준금리는 하루 1회면 충분하다.

```text
schedule: daily
```

수집값이 전일과 같아도 새 관측을 매일 만들 필요는 없다.

권장:

```text
값 또는 source_effective_at 변경
→ 새 market_indicators 행

변경 없음
→ collection_run=no_change
```

## 7.4 화면 노출

상단 참고바:

```text
한국은행 기준금리  X.XX%
적용일 YYYY-MM-DD
마지막 확인 YYYY-MM-DD HH:mm
```

기준금리와 예금금리의 차이를 자동으로 “수익” 또는 “마진”으로 표현하지 않는다.  
단순 참고지표다.

## 7.5 완료 게이트

```text
공식 ECOS 실제 응답 fixture 확보
공식 기준금리 화면과 최신값 대조
중복 없는 시점 이력
단위 percent 고정
값 범위 검증
원본 추적률 100%
API 키 노출 0
변경 없음 실행 no_change 검증
참고카드 값과 DB 최신행 일치
```

---

# 8. 우대금리·우대조건 계약

## 8.1 공통 표시

각 비교행은 다음을 독립적으로 가진다.

```text
base_rate
max_rate
preference_spread
raw_preference_text
```

계산:

```text
preference_spread =
    max_rate - base_rate
    단, 둘 중 하나가 NULL이면 NULL
```

## 8.2 원천별 처리

### 저축은행 FSB

다음 공식 필드를 결합해 보존한다.

```text
SWEETENER
ETC_NOTE_MATTER
JOIN_TARGET
JOIN_LOCATION
```

`SWEETENER`를 우대조건 원문 1차값으로 사용하고, 나머지는 상세정보로 구분한다.

### finlife 은행·저축은행

```text
spcl_cnd → raw_preference_text
intr_rate → base_rate
intr_rate2 → max_rate
```

### 신협

```text
baseRate → base_rate
highRate → max_rate
prefCondMemo → raw_preference_text
joinSubjMemo → 가입대상
etcAtntMatt → 유의사항
```

### 새마을금고

공식 금리표에 최고우대금리 열이 없다.

```text
base_rate = 공식 기본이율
max_rate = NULL
raw_preference_text = ""
```

UI:

```text
최고금리: 원천 미제공
우대조건: 원천 미제공
```

### 농·축협

상세화면 실측 후 매핑한다.

- 명시된 기본금리와 최고금리가 있으면 분리
- 금리 하나만 있으면 기본금리만 저장
- 비고·우대항목은 원문 보존
- `최고금리`라는 근거 없이 최고값을 max_rate로 만들지 않음

## 8.3 `preference_conditions` 활성화

현재 테이블은 있으나 원문 표시가 우선이다.

이번 단계:

```text
원문 100% 표시
구조화 파싱은 부분 지원
```

구조화 대상 예:

```text
급여이체
카드실적
자동이체
첫거래
비대면가입
조합원/준조합원
마케팅동의
목표금액 달성
```

파서가 확신하지 못하면:

```text
parse_status = raw_only
parser_confidence = NULL
```

구조화 실패가 수집 실패를 만들면 안 된다.

---

# 9. 통합 비교 데이터셋

## 9.1 공개 메인 데이터와 DB 전용 데이터 분리

설정 파일을 추가한다.

```text
config/presentation.yaml
```

예시:

```yaml
main_sectors:
  - savings_bank
  - kfcc
  - nh_local
  - cu

reference_sectors:
  - bank

db_only_sources:
  - finlife_savings_bank

reference_indicators:
  - bok_base_rate
```

실제 1차 저축은행 원천은 FSB다.  
finlife 저축은행 데이터는 DB에 보존하고 교차검증에 사용하되 동일 상품을 메인에 중복 노출하지 않는다.

## 9.2 유효 레코드 선택

저축은행:

```text
FSB 정상 최신값 우선
finlife는 교차검증·fallback
```

새마을금고:

```text
kfcc_official 정상 최신값
```

농·축협:

```text
nh_local_official 정상 최신값
```

신협:

```text
cu official 정상 최신값
```

실패 시:

```text
최신 정상 run 유지
+ stale 표시
+ 마지막 성공 시각 표시
```

## 9.3 동일 비교단위

비교 기본키:

```text
sector
institution
outlet nullable
product_type
product
term
join_channel
interest_method
amount_range
customer_scope
rate_scope
```

지역명을 `variant_key`에 넣어 동일 상품 이력을 끊지 않는다.  
점포가 실제 금리 범위라면 `outlet_id`가 키에 포함된다.

---

# 10. UI 개편 명세

## 10.1 정보구조

```text
[참고지표]
한국은행 기준금리 | 시중은행 12개월 예금금리

[업권 탭]
전체 | 저축은행 | 새마을금고 | 농·축협 | 신협

[필터]
지역 | 부산 구·군 | 상품유형 | 기간 | 가입채널 | 이자방식 | 금융기관 | 검색

[정렬]
기본금리 높은순 | 최고금리 높은순 | 최신 공시순 | 기관명순

[비교표]
금융기관/점포 | 상품 | 지역 | 기간 | 기본금리 | 최고금리 | 우대폭 | 우대조건 | 기준일
```

## 10.2 기본 진입상태

```text
업권: 전체 4개
지역: 부산
구·군: 전체
상품유형: 거치식예금
기간: 12개월
정렬: 기본금리 높은순
```

지역 기반이 없는 저축은행은 부산 선택 시 다음 방식으로 포함 여부를 사용자가 이해하게 한다.

권장 옵션:

```text
[✓] 부산에서 확인 가능한 본점기준 저축은행 참고값 포함
```

기본 활성화하되 배지를 붙인다.

```text
본점 기준
부산 가입가능 필터
```

## 10.3 필터 동작

### 업권

복수선택 가능.

### 금융기관

현재 선택한 업권·지역 결과에 존재하는 기관만 표시.

### 지역

```text
전국
서울특별시
부산광역시
...
```

부산 선택 시 구·군 필터 활성화.

### 구·군

원천별 적용 가능성에 따라 결과를 분리한다.

- 주소기반: 정확 필터
- 조회지역 기반: `조회지역` 배지
- 본점기준: 구 필터 비대상

### 상품유형

```text
정기예금/거치식
적금/적립식
자유적립식
입출금/요구불
기타
```

### 가입기간

```text
1
3
6
12
24
36
직접입력
```

기간구간 상품은 해당 기간이 범위에 포함될 때 매칭한다.

### 정렬

`최고금리 높은순`에서는 `max_rate IS NULL`을 최하단에 둔다.  
NULL을 기본금리로 대체해 순위를 만들지 않는다.

## 10.4 표 행

필수 표시:

```text
업권
금융기관
점포
지역근거
상품명
상품유형
기간
금액범위
가입채널
이자방식
기본금리
최고금리
우대폭
우대조건 요약
원천 기준일
수집상태
```

우대조건은 한 줄 요약 후 펼치기로 원문 전체를 보여준다.

## 10.5 배지

```text
본점 기준
점포 기준
공식 조회지역
전국 공시
원천 미제공
우대조건 있음
비대면
영업점
직장금고
조합원 대상
stale
부분수집
```

## 10.6 참고카드

상단에 작게 표시한다.

### 한국은행 기준금리

```text
기준금리
X.XX%
적용일
```

### 시중은행 참고금리

```text
12개월 정기예금
기본금리 중앙값 X.XX%
최고금리 상단 X.XX%
N개 은행
```

참고카드는 메인 4개 업권 순위에 포함되지 않는다.

## 10.7 정적 사이트 데이터 구조

현재 정적 사이트 방식을 유지한다.

권장 `table.json` 행:

```json
{
  "sector": "nh_local",
  "institution_name": "가락농협",
  "outlet_name": null,
  "region_sido": "부산광역시",
  "region_sigungu": "강서구",
  "geo_basis": "outlet_address",
  "product_type": "term_deposit",
  "product_name": "정기예탁금",
  "term_months": 12,
  "join_channel": "branch",
  "interest_method": "unknown",
  "base_rate": "3.10",
  "max_rate": null,
  "preference_spread": null,
  "preference_raw": "",
  "rate_scope": "outlet",
  "source_effective_at": "2026-08-06",
  "freshness_status": "fresh"
}
```

참고지표는 별도 블록으로 둔다.

```json
{
  "benchmarks": {
    "bok_base_rate": {},
    "commercial_bank_12m": {}
  }
}
```

## 10.8 성능

- 표 전체를 DOM에 한 번에 렌더링하지 않는다.
- 1차 화면은 상위 100건 또는 페이지 단위 렌더링.
- 필터는 브라우저 메모리 데이터에서 동작.
- `table.json.gz` 유지.
- 부산 기본진입 데이터와 전국 데이터 분리를 검토하되, 중복 산출물은 최소화.
- 모바일에서 주요 필터는 접이식.
- 긴 우대조건은 행 높이를 고정하고 상세 패널에서 표시.

---

# 11. 교차검증

## 11.1 저축은행

FSB와 finlife를 비교한다.

매핑:

```text
기관명 정규화
상품명 정규화
가입기간
이자방식
가입채널 가능 시
```

차이가 기준치를 넘으면:

```text
review_items.type = cross_source_difference
```

메인 표시값은 FSB를 우선한다.

## 11.2 새마을금고

제3자 공개 데이터가 있더라도 공식 수집값을 대체하지 않는다.

검증 용도:

```text
금고 수
금리 행 수
금고별 대표상품 존재 여부
```

## 11.3 농·축협

초기에는 공식 중앙 상세화면만 사용한다.  
개별 조합 홈페이지와 자동 대조하지 않는다.

## 11.4 기준금리

ECOS 최신값을 한국은행 공식 기준금리 화면과 대조하는 테스트를 정찰 단계에서 1회 수행한다.

---

# 12. Actions 워크플로우

## 12.1 수집 순서

```text
1. 기존 rate-data DB 복원
2. migration
3. finlife_bank
4. FSB
5. KFCC
6. CU
7. NH_LOCAL
8. BOK_ECOS
9. validate
10. snapshot
11. build dashboard/site
12. export
13. gate
14. rate-data 발행
```

원천 하나가 실패했다고 모든 정상 원천을 버리지는 않는다.  
단, DB·스냅샷 무결성 실패는 전체 발행을 중단한다.

## 12.2 주기

초기 권장:

| 원천 | 주기 |
|---|---|
| 한국은행 기준금리 | 매일 1회 |
| finlife 시중은행 | 매일 1회 |
| FSB | 매일 1회 |
| 새마을금고 부산 | 매일 1회 |
| 신협 부산 | 매일 1회 |
| 농·축협 부산 | 매일 1회 |
| 전국 대규모 수집 | 부산 안정화 후 별도 결정 |

## 12.3 상태

```text
success
partial
no_change
blocked
schema_changed
failed
stale
```

`stale`는 실행상태가 아니라 화면의 최신성 파생상태로 계산해도 된다.

예:

```text
source_effective_at 또는 마지막 성공수집이 임계일보다 오래됨
→ stale
```

## 12.4 자동 품질검사

- 전회 대비 기관 수 급감
- 점포 수 급감
- 상품 수 급감
- 금리 전부 NULL
- 기본금리 비정상 범위
- 최고금리 < 기본금리
- 최고금리 이상치
- 우대조건 파싱 실패율 급증
- 지역 파싱 실패율 급증
- 농·축협 부산 검색결과 중 부산 주소 비율 급변
- HTML 구조 지문 변경
- API 응답 필수필드 소실

---

# 13. 테스트 명세

## 13.1 CI

외부 네트워크 없이 fixture로 실행한다.

```text
ruff
pytest
alembic upgrade head
dashboard build
site build
```

## 13.2 필수 테스트

### 공통

```text
variant_key 결정성
동일 run 중복 방지
다른 run 관측이력 생성
NULL 최고금리 보존
원본 locator 100%
마지막 정상값 보호
```

### 농·축협

```text
검색어 부산 + 경남주소 결과 제외
주소에서 부산 구·군 파싱
기관/점포 분리
상품 탭별 파싱
금액구간 파싱
기간구간 파싱
기준일 파싱
```

### 시중은행

```text
020000 → sector=bank
030300 → sector=savings_bank
source_id 분리
은행 레코드 메인 4업권 표에서 제외
```

### 기준금리

```text
최신값 선택
동일 적용일 중복 방지
값 변경 시 새 이력
변경 없음 no_change
```

### UI

```text
부산 선택 시 16개 구·군 표시
부산진구 필터 결과가 실제 region_sigungu와 일치
저축은행에서 구 필터 비활성
최고금리 정렬에서 NULL 최하단
우대조건 펼치기
원천 미제공 표시
참고카드가 메인 순위에 섞이지 않음
```

---

# 14. 완료 정의

이번 재정비 완료는 다음을 모두 충족해야 한다.

## 14.1 데이터

```text
저축은행 최신 정상 공식 데이터 존재
새마을금고 최신 정상 공식 데이터 존재
신협 최신 정상 공식 데이터 존재
농·축협 부산 공식 데이터 존재
시중은행 finlife 데이터 DB 존재
한국은행 기준금리 시점 이력 존재
```

## 14.2 UI

```text
메인 업권은 4개만 전면 표시
시중은행·기준금리는 참고카드
금융기관·상품·지역·부산 구·군 필터 동작
기본금리·최고금리·우대폭·우대조건 표시
원천별 지역근거·금리범위 배지 표시
```

## 14.3 운영

```text
모든 수집 무인 Actions 실행
사용자 수동 파일 작업 0
실패 시 이전 정상값 유지
fixture CI 통과
실제 Actions E2E 통과
DB integrity_check=ok
foreign_key_check=0
API 키 노출 0
```

---

# 15. 권장 PR 분할

## PR 1 — 계약 및 현황 정리

```text
v4 명세 작성
CURRENT.md 갱신
roadmap 실제 코드 기준 갱신
presentation.yaml 추가
```

## PR 2 — 지역·표시 데이터 모델 (끝)

```text
GeoBasis
region_sido / region_sigungu
migration
region normalizer
인덱스
```

마이그레이션 `8c1a4f2b9d07`. 주소를 자르는 규칙이 세 벌이었던 것을
`services/region_service.split_address` 한 벌로 모으고, 그 결과를
`institutions`·`outlets`의 네 칸에 저장한다.

전국 스냅샷 사본(275,714,048 bytes, 2026-08-06 rate-data `81c1c4d`)에
적용해 전후를 대조했다. 백필 30초.

| | 전 | 후 |
|---|---|---|
| 금리표 행 | 132,502 | 132,502 |
| 구·군 집계 | 314 | 314 |
| 구·군별 최고금리 | 245 | 245 |
| `validate` | 12/12 | 12/12 |

값이 달라진 것은 **한 기관 16행뿐이다.** 동양저축은행 주소가
`신동해빌딩 1,2,3층`이라 옛 SQL은 구·군을 `''`로 읽었다.

그 값은 지역이 아니다. 마이그레이션 `b47e0a91c3d5`이 지역 칸을 비운다 —
`region_service.looks_like_sido`가 시도 이름 자리에 올 수 있는 말인지
보고, 아니면 넣지 않는다. 주소 원문은 `address` 칸에 그대로 남는다.

별칭표가 모르는 이름이라고 다 버리지는 않는다. `전남광주통합특별시`는
`특별시`로 끝나고 여수시·구례군·서구 같은 시군구가 붙어 있는 진짜
주소다 — 버리면 11건의 지역이 사라진다.

`review_items`에 남는 것:

| issue_type | 건수 | 무엇 |
|---|---:|---|
| `region_unresolved` | 927 | 주소가 원래 없다 (신협 848·finlife 79) |
| `region_not_an_address` | 2 | 주소에 시도가 없어 지역 칸을 비웠다 |

## 시간 표기

**저장은 UTC, 표시는 KST** (`domain/timeutil.py`). `collection_runs`에 이미
UTC로 적힌 행이 쌓여 있어 저장 기준을 바꾸면 한 칸에 두 기준이 섞인다 —
시간대 정보가 없는 naive datetime이라 구별할 방법이 없다.

경계에서만 바꾼다. `generated_at`과 실행 시각은 `+09:00`을 달고 나가고,
내려받기 파일 이름과 원본 디렉터리는 한국 날짜를 쓴다. 저축은행중앙회
조회 날짜(`fsb/adapter._today`)도 한국 날짜다 — 정기 수집이 22:00 UTC에
도는데 그때 한국은 이미 다음 날이라, UTC를 쓰면 하루 전 공시를 물어본다.

## PR 3 — 농·축협 정찰

```text
정찰 스크립트
실물 fixture
요청 계약 문서
Actions 접근 검증
```

이 PR에서 수집 가능 여부와 정확한 식별키를 확정한다.

## PR 4 — 농·축협 부산 세로 절단

```text
adapter/parser
institution/outlet
rate parsing
tests
CLI
workflow
```

## PR 5 — 시중은행 finlife 분리

```text
finlife_bank
finlife_savings_bank
기존 source migration
참고집계
tests
```

## PR 6 — 한국은행 기준금리

```text
ECOS 정찰
market_indicators migration
adapter/parser
reference card data
tests
```

## PR 7 — 통합 비교 UI

```text
4업권 메인
부산 구·군
필터/정렬
우대조건 상세
원천범위 배지
참고카드
```

## PR 8 — 통합 Actions·E2E

```text
수집순서
부분실패 정책
게이트
실제 부산 실행
산출물 검산
완료 보고서
```

---

# 16. Claude Code 최종 보고 형식

작업 종료 시 아래 순서로 보고한다.

```markdown
## 수행한 작업

## 실제 반영 파일

## 데이터 원천별 실측 결과
- 요청 수
- 원본 수
- 기관 수
- 점포 수
- 상품 수
- 관측 수
- 소요시간
- 오류/경고

## 검증 체크리스트
- pytest
- ruff
- migration
- Actions
- DB integrity
- UI 데이터 검산

## 확인되지 않은 사항
추정하지 말고 명시

## 다음 작업 3가지
```

---

# 17. 구현 시 절대 지켜야 할 표기

허용:

```text
부산 강서구에 위치한 농·축협 점포의 공식 금리
부산에서 영업하는 신협의 조합 단위 공시금리
부산에서 가입 가능한 저축은행의 본점 기준 공시금리
새마을금고 점포 주소 기준 부산 구·군 필터
시중은행 전국 공시 참고금리
```

금지:

```text
모든 업권이 부산 구별 금리를 제공한다
최고금리가 없으면 기본금리와 동일하다
신협 조회지역을 실제 점포주소라고 표현한다
저축은행 본점금리를 부산 지점금리라고 표현한다
농·축협 검색어 부산 결과를 주소검증 없이 부산으로 저장한다
시중은행을 메인 순위에 배지 없이 섞는다
```

마지막 줄은 2026-08-06에 바뀌었다. 원래는 「시중은행을 메인 4업권 순위에
**자동** 혼합한다」였다. 금지의 핵심은 "자동"이었다 — 아무도 정하지 않았는데
지역 근거가 다른 행이 슬그머니 같은 줄에 서는 것. 사용자가 넣기로 정했으므로
자동이 아니다. 대신 **배지 없이 섞는 것**을 금지로 남긴다. 배지가 사라지면
§6.4의 조건이 무너지고, 그러면 원래 금지하려던 그 상태가 된다.
