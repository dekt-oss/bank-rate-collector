# 소스 정찰: 금융감독원 finlife 오픈API

- 조사일: 2026-08-05
- 대상: 금융상품통합비교공시 오픈API (`finlife.fss.or.kr`)
- 명세서 v3 §7.1 대응 문서
- 실행 검증 결과 원본: `docs/source-recon/finlife-verify.json` (워크플로우 `P0 finlife API verify` 산출)

---

## 1. 인증·접근

| 항목 | 값 |
|---|---|
| 인증키 | 32자리, `auth` 쿼리 파라미터 |
| 보관 위치 | GitHub 레포지토리 시크릿 `FINLIFE_API_KEY` |
| 주입 경로 | Actions 워크플로우 `env:` → 프로세스 환경변수 |
| 코드 내 하드코딩 | 없음 (명세서 v3 §16.1 준수) |
| 프로토콜 | `http` (공식 문서 기준. https 지원 여부 미확인 — **미해소**) |

인증키 신청: `finlife.fss.or.kr/finlife/api/finlifeApiKey/list.do?menuNo=700034`

---

## 2. 엔드포인트

기본 형식:

```
http://finlife.fss.or.kr/finlifeapi/{서비스명}.{json|xml}
  ?auth={인증키}&topFinGrpNo={권역코드}&pageNo={페이지}
```

공식 제공 8종 중 본 프로젝트 사용 대상:

| 서비스명 | 용도 | 본 프로젝트 사용 |
|---|---|---|
| `companySearch` | 금융회사 목록·점포 소재 지역 | 지역 판정용 |
| `depositProductsSearch` | 정기예금 | 수집 |
| `savingProductsSearch` | 적금 | 수집 |
| `annuitySavingProductsSearch` | 연금저축 | 범위 밖 |
| 주택담보/전세자금/개인신용/개인사업자 대출 4종 | 여신 | **범위 밖** (기획서 v3 §2.2 제외 범위) |

### 2.1 권역코드 (`topFinGrpNo`)

| 코드 | 권역 | 본 프로젝트 |
|---|---|---|
| `020000` | 은행 | 벤치마크 |
| `030200` | 여신전문 | 미사용 |
| `030300` | 저축은행 | 교차검증 |
| `050000` | 보험 | 미사용 |
| `060000` | 금융투자 | 미사용 |

### 2.2 선택 파라미터

`financeCd` — 금융회사 코드 또는 명칭(예: `0010587`, `국민`, `상호`)

---

## 3. 응답 구조

```json
{
  "result": {
    "err_cd": "000",
    "err_msg": "정상",
    "total_count": 0,
    "max_page_no": 0,
    "now_page_no": 0,
    "baseList": [],
    "optionList": []
  }
}
```

### 3.1 상품 API — `baseList` (상품 기본정보)

`dcls_month`(공시 제출월 YYYYMM), `fin_co_no`(금융회사코드), `kor_co_nm`(금융회사명),
`fin_prdt_cd`(상품코드), `fin_prdt_nm`(상품명), `join_way`(가입방법),
`mtrt_int`(만기후 이자율), `spcl_cnd`(**우대조건 원문**), `join_deny`(가입제한),
`join_member`(가입대상), `max_limit`(최고한도)

### 3.2 상품 API — `optionList` (기간별 금리)

| 필드 | 의미 | 매핑 대상 (명세서 v3 §5.9) |
|---|---|---|
| `intr_rate_type` | 이율 유형 (S=단리, M=복리) | `product_variants.interest_method` |
| `save_trm` | 저축기간(개월) | `product_variants.term_months` |
| `intr_rate` | 기본 이자율(%) | `rate_observations.base_rate` |
| `intr_rate2` | 우대 이자율(%) | `rate_observations.max_rate` |

결합키: `fin_co_no` + `fin_prdt_cd`

### 3.3 금융회사 API — `optionList`

`area_cd`(지역구분코드), `area_nm`(지역이름), `exis_yn`(점포소재여부 Y/N)

---

## 4. 실행 검증 결과

### 4.1 1차 연결 테스트 (2026-08-05, 저축은행 정기예금)

`P0 finlife API test` 워크플로우 실행 로그:

```
page 1/4: companies=100 options=647
page 2/4: companies=100 options=660
page 3/4: companies=100 options=687
page 4/4: companies=95  options=658
완료: topFinGrpNo=030300 total_companies=395 total_options=2652
```

판정: **인증키 정상, 망분리 통과, 페이지네이션 정상.**

### 4.2 2차 수집범위 검증 (2026-08-05)

`P0 finlife API verify` 워크플로우가 은행·저축은행 × 정기예금·적금·금융회사 6개 조합을 전 페이지 순회했다.
실행 로그 실측값:

| 서비스 / 권역 | baseList | optionList | total_count |
|---|---:|---:|---:|
| 정기예금 / 은행 | 38 | 152 | 38 |
| 적금 / 은행 | 58 | 181 | 58 |
| 금융회사 / 은행 | 18 | 306 | 18 |
| 정기예금 / 저축은행 | 395 | 2,652 | 395 |
| 적금 / 저축은행 | 277 | 1,358 | 277 |
| 금융회사 / 저축은행 | 80 | 1,360 | 80 |

**6개 조합 전부 `err_cd=000` 정상 응답.** 상품 API 4종 합계 768개 상품 / 4,343개 기간별 금리옵션을 수집했다.

판정 결과:

```json
{
  "product_api_has_region_field": false,
  "busan_gu_filter_possible_from_finlife_alone": false,
  "company_api_area_granularity": "시도"
}
```

원본 응답과 판정 JSON은 실행 아티팩트 `p0-finlife-verify`(13개 파일)에 보존되어 있다.
상세 판정값(`orphan_option_keys`, `option_with_max_rate`, `base_with_pref_text` 등)은
아티팩트 내 `docs/source-recon/finlife-verify.json` 참조.

---

## 5. 핵심 제약 — 부산 구 단위 필터 불가

2026-08-05 실행 검증으로 확정된 사항이다 (`product_api_has_region_field: false`).

finlife 상품 API(`depositProductsSearch`, `savingProductsSearch`)의 `baseList`·`optionList`에는
**지역 필드가 없다.** 공시는 금융회사(본점) 단위 전국 기준이다.

지역 정보는 `companySearch`의 `optionList`에만 `area_cd`/`area_nm`/`exis_yn` 형태로 존재하며,
검증 결과 그 단위는 **시도**(`company_api_area_granularity: "시도"`)였다.
즉 "해당 금융회사가 그 시도에 점포를 두는가"라는 Y/N 플래그이지,
특정 구·군의 지점별 금리가 아니다.

따라서:

1. finlife만으로는 **부산 구·군 단위 비교가 불가능**하다.
2. finlife에서 얻은 저축은행 금리는 `rate_scope=head_office_reference`로 저장한다
   (명세서 v3 §4.3, `RateScope.HEAD_OFFICE_REFERENCE`).
3. `companySearch`는 "부산에 점포가 있는 저축은행" 목록을 좁히는 용도로만 쓴다.
4. 부산 구 단위 데이터는 새마을금고·신협·농축협 등 **권역별 자체 소스**에서 확보해야 한다.
   이것이 기획서 v3가 4개 권역 독립 수집기를 두는 이유다.

---

## 6. 구현 시 준수사항

- 페이지 끝까지 순회한다 (`now_page_no >= max_page_no`까지).
- 요청 간격 1.0초 이상 (명세서 v3 §15.3 `request_interval_seconds: 1.0`).
- `err_cd != "000"`이면 저장하지 않고 실행을 `failed`로 기록한다.
- `dcls_month`(공시 제출월)와 수집시각(`observed_at`)을 분리 저장한다.
- `intr_rate2`가 비어 있으면 `max_rate`를 `base_rate`와 같게 두지 않고 `NULL`로 둔다
  (명세서 v3 §8.4).
- 원본 JSON은 `data/raw/` 아래 그대로 보존하고 레포에는 커밋하지 않는다.

---

## 7. 미해소 항목

1. HTTPS 지원 여부 — 현재 공식 문서상 `http`. 평문 전송 시 인증키 노출 위험 검토 필요.
2. 일일 호출 한도 — 공식 문서에 명시 없음. 연속 호출 시 제한 응답 발생 여부 미확인.
3. 저축은행 금리값이 저축은행중앙회 공시와 일치하는지 — 교차검증은 저축은행중앙회 수집기 구현 후 가능
   (명세서 v3 §7.2의 `cross_source_difference` 검수항목).
