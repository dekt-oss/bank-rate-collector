# Savings-bank funding identity — 13 blocked rows evidence

```yaml
document_type: runtime_evidence
status: investigated_fail_closed
as_of: 2026-09-01
scope: data_go_savings_bank_funding_identity
persistent_mapping_change: false
production_write_back: false
```

## 1. 결론

2026-03 Data.go 저축은행 funding population은 실제 저축은행 79개이며, Strategy/canonical institution에 exact mapping된 observation은 66개다. 남은 13개는 **source identity가 없는 기관이 아니다.**

13개 모두 현재 production DB에 동일한 형태의 `savings_bank:<fncoCd>` key가 이미 `fsb`와 `finlife_savings_bank` 양쪽에 존재하고, 두 기존 link가 같은 canonical institution을 가리킨다. 그러나 Data.go의 한글/법인식 기관명과 canonical/FSB의 현행 표시명이 정규화 후 일치하지 않아 기존 identity guard를 통과하지 못한다.

현재 저장소의 cross-source identity 계약은 과거 오병합 위험 때문에 **exact code + normalized name**을 함께 요구한다. 따라서 `fncoCd` 숫자가 같다는 이유만으로 이 13개를 persistent identity로 자동 연결하지 않는다.

이번 조사에서는 mapping/backfill을 하지 않고 `blocked_exact_code_name_mismatch` 상태를 유지한다.

정확한 remediation은 다음 중 하나가 추가로 증명된 뒤 별도 변경으로 수행한다.

1. FSB `FINAN_COMP_CODE`, Finlife `fin_co_no`, Data.go `fncoCd`가 동일한 FSS financial-company-code namespace라는 **공식 cross-source 계약 증거**, 또는
2. canonical institution과 Data.go `crno`를 연결하는 **독립적인 official CRNO bridge**.

이 중 하나가 없으면 기존 name guard를 제거하지 않는다.

---

## 2. Production census provenance

별도 branch에서 production DB artifact를 복원한 뒤 read-only census를 수행했다.

```text
branch
chore/savings-bank-identity-census-20260901

census input HEAD
feb35d97587c17ede809252db81b3a820a1b883c

workflow run
33463407687  success

artifact
savings-bank-identity-census-33463407687
artifact id 9784017658
artifact digest sha256:5774152e4c1f560a8c3efd73c23011a0c91219a5d6b4002f0b22c5934d1b8b82

source_id
data_go_savings_bank_funding

latest source_effective_month
2026-03
```

DB before/after hash:

```text
9048718f0d932c1017504b355081314a956897a16829c9a7e5f25990701e57d8
```

before와 after가 동일하다. Census는 production artifact의 DB를 영구 변경하지 않았다.

```text
source_population             79
observation_mapped_count      66
observation_unmapped_count    13
write_back_performed          false
```

13건 classification은 모두:

```text
blocked_exact_code_name_mismatch
```

---

## 3. Data.go official identity fields

공공데이터포털의 공식 `금융위원회_금융통계저축은행정보` 데이터셋은 저축은행 일반현황 output에서 아래 필드를 명시한다.

```text
crno    법인등록번호
fncoCd  금융감독원 금융회사 금융코드
fncoNm  금융감독원 금융회사명
```

Official source:

```text
https://www.data.go.kr/data/15061316/openapi.do
```

Repository의 current Data.go funding collector도 `fncoCd`를 primary identity key로 보존하고, 코드가 다른 기관을 이름만으로 자동 합병하지 않는다고 명시한다.

그러나 이 공식 Data.go 정의만으로 **FSB `FINAN_COMP_CODE`와 Finlife `fin_co_no`가 동일 namespace라는 사실까지 독립적으로 증명되지는 않는다.**

---

## 4. Current FSB naming evidence

저축은행중앙회 current directory는 약어/브랜드형 기관명을 사용한다.

공식 directory:

```text
https://www.fsb.or.kr/sabfindquic_0100.act
```

검색 안내 자체가 다음처럼 명시한다.

```text
BNK(○) 비엔케이(X)
은행명 뒤 저축은행 입력 시 검색되지않습니다.
```

실제 directory에는 `BNK`, `OSB` 등의 현행 표시가 나온다. 따라서 Data.go의 `비엔케이저축은행`, `오에스비저축은행`과 FSB/canonical의 `BNK저축은행`, `OSB저축은행` 차이는 실재하는 source naming convention 차이다.

이 사실은 name mismatch의 원인을 설명하지만, **이름 alias 자체만으로 persistent identity를 확정하는 근거로 사용하지 않는다.**

---

## 5. 13개 exact gap

| fncoCd | Data.go name | CRNO | current canonical | current result |
| --- | --- | --- | --- | --- |
| 0010346 | 오에스비저축은행 | 1101110127161 | OSB저축은행 | blocked name mismatch |
| 0010370 | 에스비아이저축은행 | 1101110121981 | SBI저축은행 | blocked name mismatch |
| 0010404 | 디에이치저축은행 | 1801110006535 | DH저축은행 | blocked name mismatch |
| 0010438 | 유니온상호저축은행 | 1701110158875 | 유니온저축은행 | blocked name mismatch |
| 0010439 | 엠에스상호저축은행 | 1701110004656 | MS저축은행 | blocked name mismatch |
| 0010468 | 세람상호저축은행 | 1344110001030 | 세람저축은행 | blocked name mismatch |
| 0010568 | 대원상호저축은행 | 1712110017218 | 대원저축은행 | blocked name mismatch |
| 0011767 | 제이티저축은행 | 1311110177442 | JT저축은행 | blocked name mismatch |
| 0012889 | 아이비케이저축은행 | 2301110182384 | IBK저축은행 | blocked name mismatch |
| 0013002 | 비엔케이저축은행 | 1801110786484 | BNK저축은행 | blocked name mismatch |
| 0013127 | 케이비저축은행 | 1101114764745 | KB저축은행 | blocked name mismatch |
| 0013308 | 제이티친애저축은행 | 1101114937780 | JT친애저축은행 | blocked name mismatch |
| 0013351 | 오케이저축은행 | 1101115062289 | OK저축은행 | blocked name mismatch |

모든 13건에서 현재 census가 확인한 구조는 동일하다.

```text
Data.go observation
  org_key = savings_bank:<fncoCd>

existing active source_entity_links
  finlife_savings_bank / same org_key / match_method=exact_code
  fsb                  / same org_key / match_method=exact_code

both existing links
  -> same canonical institution

but
  normalize(Data.go source name) != normalize(canonical name)

therefore
  candidate_institution_id = null
  classification = blocked_exact_code_name_mismatch
```

13건 모두 current census에서 `crno_links=[]`, `name_only_links=[]`였다. 즉 production canonical identity에는 이 Data.go CRNO를 independent bridge로 활용할 기존 link가 아직 없다.

---

## 6. 왜 기존 name guard를 제거하지 않는가

현재 `entity_service._find_shared_institution()`의 설계는 명시적으로 다음 두 조건을 요구한다.

1. name-hash가 아닌 공식 코드 기반 org key
2. normalized institution name 일치

주석과 도입 history는 이유도 명확하다.

> 같은 숫자를 서로 다른 source system이 우연히 사용할 수 있으므로, 잘못 합치는 것보다 갈라진 상태가 안전하다.

Historical commit:

```text
ae0117f96897069c7965df03fe077e5bab7d8c62
fix: 같은 은행이 두 기관으로 갈라지지 않게 한다
```

해당 변경은 2026-08-06 당시 저축은행 79쌍을 합칠 때도 **공식 코드 + normalized name + same sector**를 모두 요구했다. Migration `e18c4a7d9b30`도 같은 fail-closed 조건을 사용했다.

Data.go NH funding identity reconciliation 역시 exact BRC만으로 연결하지 않고 official source name이 일치해야 mapping한다. 즉 현재 repository architecture에서 `code-only cross-source merge`는 일반 계약이 아니다.

이 13건만 예외로 code-only mapping하면 기존 identity safety invariant를 깨게 된다.

---

## 7. Evidence Gate 판정

### 확인됨

- Data.go 2026-03 저축은행 funding source population = 79
- mapped = 66, unmapped = 13
- 13개 source `fncoCd`, `crno`, source name
- Data.go `fncoCd`의 공식 의미 = FSS financial company code
- 13개 각각과 같은 형태의 existing org key가 FSB/Finlife 양쪽에 존재
- 두 existing source links는 각 행에서 동일 canonical institution을 가리킴
- 13개 모두 mismatch 원인은 Data.go name과 canonical name의 normalized mismatch
- FSB current directory는 BNK/OSB 등 acronym naming을 실제 사용
- census는 read-only였고 DB before/after hash 동일

### 아직 증명되지 않음

- FSB `FINAN_COMP_CODE`가 Data.go `fncoCd`와 동일 FSS namespace라는 **공식 machine/document contract**
- Finlife `fin_co_no`가 Data.go `fncoCd`와 동일 FSS namespace라는 **공식 machine/document contract**
- 13개 Data.go CRNO와 current canonical institution을 독립적으로 연결하는 canonical CRNO link

### 따라서 하지 않음

- name guard 제거
- acronym/한글 발음 alias만으로 persistent identity merge
- existing FSB/Finlife org key를 Data.go exact mapping 증거로 자동 승격
- `mapped_exact_fss_code` 상태 쓰기
- historical observation backfill

---

## 8. Safe remediation target

후속 remediation은 별도 PR에서 아래 acceptance criteria를 모두 만족해야 한다.

1. official cross-source code namespace 또는 unique CRNO bridge 증거 확보
2. 13개 모두 1:1 canonical institution으로 결정되고 conflict 0
3. 기존 66 mapped observation의 identity 불변
4. source amount / month / revision / raw provenance 불변
5. before/after identity census에서 79/79 exact mapping
6. active canonical institution duplicate 0
7. wrong-sector / multi-candidate conflict 0
8. migration/backfill 또는 reconciler가 idempotent
9. rollback/recovery path 명시
10. production artifact에서 read-only post-write validation

증거가 부족하면 66/79 상태를 유지한다. **13개를 억지로 79/79로 만드는 것이 완료 기준이 아니다. 잘못된 identity 0건이 우선이다.**
