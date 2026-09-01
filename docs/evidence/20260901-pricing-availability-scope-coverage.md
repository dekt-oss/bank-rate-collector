# Pricing Availability Scope Coverage — R0 evidence gate

```yaml
document_type: runtime_evidence
status: partially_reverified_current_rate_data
as_of: 2026-09-01
scope: pricing_peer_availability_scope
source_of_truth:
  - repository_schema
  - published_rate_data
  - prior_production_census
code_change: none
```

## 1. 결론

Pricing Peer의 모집단을 만들 때 현재 `availability_scope` 문자열을 곧바로 동일 경쟁권으로 해석하면 안 된다.

- `전국`은 전국 가입을 표현하는 source/display label로 사용할 수 있다.
- `지역금고`는 **어느 지역의 금고인지**를 말하지 않으므로 그 문자열 하나만으로 두 기관을 peer로 묶을 수 없다.
- `직장금고` 역시 어느 직장/common bond인지 식별하지 못한다.
- `미상`/`unknown`은 경쟁범위 증거가 아니다.
- 따라서 raw/display `availability_scope`와 evidence-backed `availability_match_key`를 분리한다.
- unresolved scope를 `nationwide`로 silent fallback하지 않는다.

R0 구현은 이 결론을 fail-closed 계약으로 반영한다.

---

## 2. 현재 repository 계약

main 기준 `Institution.availability_scope`는 기본값이 `unknown`이다.

즉 repository 자체가 모든 기관의 가입범위를 알고 있다는 전제를 두지 않는다. `unknown`을 전국가입으로 바꾸는 것은 현재 persistent contract보다 강한 추정이 된다.

현재 implementation branch의 신규 계약은:

```text
availability_scope      source/display label
availability_match_key  evidence-backed pricing comparison key
```

로 분리한다.

`availability_match_key`가 다음과 같으면 fail-closed한다.

```text
""
unknown
none
unavailable
미상
자료없음
```

또한 raw label이 둘 다 `지역금고`여도 match key가 `local:busan` / `local:seoul`처럼 다르면 같은 pricing peer population으로 합치지 않는 테스트를 둔다.

---

## 3. 현재 published rate-data pin

2026-09-01 재확인한 published `rate-data` branch:

```text
rate-data commit
6154a60fafea758d57041b8064031b322ec28fc1

commit message
data: NH 독립 수집 갱신 (run 33439208473, attempt 1)

published file
site-public/data/strategy-table.json

blob sha
e66bc17052b9e186b6de251e6a3c1490fa8eaa48

size
8,799,229 bytes
```

현재 published Strategy table의 columns에는 `availability_scope`가 포함되어 있음도 직접 확인했다.

### 현재 전수 census의 검증 한계

`strategy-table.json`은 약 8.8MB의 단일 JSON 행이다. 이번 connector 경로에서는 현재 SHA의 파일 metadata와 내용 시작부는 재확인했지만, 파일 전체를 로컬 파서로 내려받아 업권별 count를 다시 계산하는 경로는 확보하지 못했다.

따라서 아래의 업권별 숫자는 **직전 R0 production 전수실측 결과**로 보존하되, `6154a60...`에서 독립 재계산 완료라고 표현하지 않는다.

---

## 4. 직전 production census — 보존 evidence

12개월 정기예금 기준 직전 production 전수실측에서는 다음이 관측됐다.

```text
savings_bank  institutions 79    raw availability_scope: 전국
nh_local      institutions 4,821 raw availability_scope: 미상
cu            institutions 834   raw availability_scope: 지역금고
bank          institutions 18    raw availability_scope: 전국
kfcc          institutions 1,151 raw availability_scope: 지역금고 중심, 일부 직장금고
```

이 숫자는 현재 `6154a60...` 파일 전체를 다시 파싱한 값이 아니다. current SHA에 대한 exact census 재현은 후속 runtime/data diagnostic으로 남긴다.

그럼에도 정책적 결론은 숫자의 미세변동과 무관하게 유지된다.

1. NH의 `미상`은 evidence-backed peer scope가 아니다.
2. CU/KFCC의 `지역금고`는 지역 식별자가 아니므로 전국의 지역금고를 한 모집단으로 합칠 근거가 아니다.
3. `직장금고` 역시 common-bond identifier 없이 같은 peer scope라고 볼 수 없다.
4. Savings Bank/Bank의 `전국`도 향후 source별 가입채널/상품 scope와 함께 검증해야 하며 단순 기관 소재지로 축소하지 않는다.

---

## 5. R0 acceptance

Pricing Peer 관련 서비스는 다음을 만족해야 한다.

- raw `availability_scope`를 peer key로 직접 사용하지 않는다.
- evidence-backed `availability_match_key`를 별도 입력으로 요구한다.
- unresolved key는 fail-closed한다.
- 같은 raw `지역금고`라도 다른 resolved key면 peer가 아니다.
- pricing peer는 임의 N cap 없이 resolved scope 내 eligible institution 전수를 기본으로 한다.
- funding observation 부재는 pricing peer 탈락 사유가 아니다.
- known funding은 `funding_as_of` 없이는 허용하지 않는다.
- `rate_as_of`와 `funding_as_of`는 별도로 보존한다.

이 acceptance는 `tests/test_institution_rate_reduction.py`와 `tests/test_pricing_peer_selection.py`에서 고정한다.

---

## 6. 아직 미검증

1. current `rate-data@6154a60...`의 업권별 availability scope exact count 재계산
2. NH 각 institution/product의 가입가능범위를 공식 evidence로 resolved key에 매핑하는 방법
3. CU `지역금고`의 실제 common-bond/가입지역 규칙을 canonical key로 만드는 방법
4. KFCC `지역금고`/`직장금고`의 실질 가입가능범위 resolution
5. historical point-in-time availability scope history

특히 5번이 없으면 과거 Historical Peer에 현재 가입범위를 소급하면 look-ahead bias가 생길 수 있으므로 R2에서 현재값 carry-back을 금지한다.

---

## 7. 금지 해석

이 evidence로 다음을 주장하면 안 된다.

- NH는 전국 경쟁이다.
- 모든 `지역금고`는 서로 직접 경쟁한다.
- 기관 소재지가 곧 상품 가입가능지역이다.
- current availability scope가 historical 시점에도 동일했다.
- current `rate-data` exact census를 이번 세션에서 완전히 재계산했다.

현재 R0의 목적은 **불완전한 가입범위 데이터가 조용히 잘못된 경쟁군으로 변환되는 경로를 차단하는 것**이다.
