# 기관별 수신잔액 Strategy UI 구현명세 — production 실측 보강

- Date: 2026-08-30 KST
- Repository: `dekt-oss/bank-rate-collector`
- Base: `main@f2a07a04cb163fd4a940306e8db3a56a912ddabf`
- Current UI PR: #245 `feat: Strategy 기관 수신 포지션 UI`
- Status: 구현 기준 확정

## 0. 목적

기관별 수신잔액 프로젝트의 다음 단계를 production DB 실측에 맞춰 고정한다.

최종 흐름:

```text
공식 원천 수집
→ L0 raw evidence
→ L1 institution_funding_observations
→ L2 6M/12M·percentile·peer-relative metrics
→ L3 Strategy payload
→ 기관 수신 포지션 UI
→ Rate × Funding Peer Matrix
→ 지역 + 유사 수신규모 Direct Peer
→ 경쟁기관 요약 / 금리 의사결정 연결
```

이 구현은 단순 합계 화면이 아니라 다음 질문에 답해야 한다.

- 어느 기관의 수신규모가 큰가?
- 최근 6개월/12개월 성장 속도는 어떠한가?
- 동일 업권에서 규모·성장 위치는 어디인가?
- 현재 선택한 업권/지역/상품/기간에서 실제 경쟁기관은 누구인가?
- 비슷한 수신규모 기관 중 금리와 수신성장이 동시에 공격적인 기관은 누구인가?

## 1. Repository Source of Truth

`AGENTS.md`가 과거 handoff보다 우선한다.

- Strategy는 established production surface다.
- 정상 Strategy 변경을 merge할 때 별도 Release Gate ON 승인을 다시 요구하지 않는다.
- PR/merge 성공은 runtime verification이 아니다.
- Strategy UI 변경은 applicable한 production-data/preview browser E2E를 수행한다.
- UI 정리 작업으로 source precedence, stable identity, ranking population, persistent contract를 임의 변경하지 않는다.

## 2. Production DB 실측 기준

현재 유효 R2 authoritative snapshot은 마지막 canonical `collect-institution-funding` 성공 run의 readback으로 검증됐다.

### 2.1 업권별 canonical 보유량

| 항목 | 저축은행 | 농·축협 | 신협 |
|---|---:|---:|---:|
| active observation | 1,840 | 11,273 | 0 |
| 기관 수 | 80 | 1,137 | 0 |
| 시계열 범위 | 2020-09 ~ 2026-03 | 2020-12 ~ 2025-12 | — |
| 보고 주기 | 분기 | 반기 | — |
| 최신 기준월 데이터 나이 | 약 5개월 | 약 8개월 | — |

### 2.2 신협

전국 신협 candidate에서는 848개 대상, 828개 성공, 7,069 points가 검증됐으나 아직 production canonical R2 DB에 반영되지 않았다.

따라서 현재 Strategy production UI에서 신협을 대표 데이터로 전제하지 않는다.

- canonical CU 0건이면 CU tab을 만들지 않는다.
- CU collector가 merge되고 전국 canonical collection/R2 publish가 완료되면 자동 등장하게 한다.

### 2.3 저축은행 aggregate 제한

기관합계와 ECOS 간 약 2× 현상이 관측됐고 원인은 별도 조사에서 확인됐다.

원인 조치가 canonical DB에 반영됐다는 readback 확인 전까지 다음은 보류한다.

- 업권 기관합계
- 시장점유율
- 업권 총액 성장
- 기관합계와 ECOS의 직접 비교

다음 institution-relative metric은 독립적으로 표시 가능하다.

- 기관별 잔액
- 업권 내 규모 percentile
- 6M/12M 성장률
- 성장 percentile
- peer median 대비 상대성장

## 3. PR #245 실측 기반 보강

### 3.1 기본 탭

사용 가능한 업권 중 우선순위:

```text
savings_bank → nh_local → cu
```

단 실제 payload가 있는 업권만 tab을 생성한다.

현재 production에서는 저축은행이 기본 tab이다.

### 3.2 Freshness를 일급 정보로 표시

기준월만 표시하지 않는다.

예:

```text
2025-12 기준 · 반기 공시 · 8개월 경과
```

가능한 경우 expected cadence도 표시한다.

목표는 `원천 공시 주기 때문에 오래된 값`과 `수집 장애`를 구분하는 것이다.

업권 cadence:

- 저축은행: 분기
- 농·축협: 반기
- 신협: 반기/정기공시 기반

### 3.3 Coverage 두 종류 분리

한 개의 coverage 숫자로 혼합하지 않는다.

1. `collection coverage`
   - source target 중 어떤 기관에서라도 검증 가능한 funding history를 확보했는가
2. `same-month observation coverage`
   - 현재 analysis month에 usable exact observation이 있는가

첫 UI에서 production DB로 안정적으로 계산할 수 없는 collection coverage는 억지로 추정하지 않는다.

UI에는 최소한:

```text
동월 관측 79 / eligible 80
```

처럼 분모와 의미를 명시한다.

95% 같은 임의 quality threshold를 계약으로 만들지 않는다.

`observed < eligible`이면 사실 그대로 `부분 관측`이라고 표시할 수 있으나, 95%를 pass/fail gate로 사용하지 않는다.

### 3.4 40행 cap

`rows.slice(0, 40)`만으로 끝내지 않는다.

첫 구현 요구:

- 총 기관수 표기: `40 / 총 1,137`
- 정렬 전환:
  - 수신규모
  - 6M 성장
  - peer 대비 6M 성장
- 저축은행처럼 모집단이 작으면 전 기관을 볼 수 있어야 한다.
- 농·축협 대규모 population은 클라이언트 table에서 과도한 DOM 생성을 피한다.

검색/virtualization은 후속 가능하지만 현재 정렬 전환과 truncation disclosure는 필수다.

### 3.5 안전한 기관명 fallback

canonical name이 비어 있어도 raw UUID/institution_id를 화면에 노출하지 않는다.

```text
기관명 미확인
```

으로 표시한다.

### 3.6 Percentile 표현

raw percentile `75%`만 보여주면 사용자가 `상위 75%`로 오해할 수 있다.

표현 예:

```text
75백분위 · 상위 25%
```

성장 percentile도 동일 원칙을 적용한다.

## 4. L2/L3 hardening

### 4.1 metric_code 명시

현재 institution funding canonical metric:

```text
deposit_liabilities_total
```

L2 DB adapter는 `sector`뿐 아니라 `metric_code`도 명시적으로 필터한다.

목적:

향후 다른 institution funding metric이 같은 테이블에 추가돼도 ranking population이 오염되지 않게 한다.

### 4.2 duplicate fail-closed

pure L2의 `(institution_id, month)` dict comprehension이 복수 point를 조용히 덮어쓰지 않도록 한다.

동일 institution/month에 둘 이상의 usable exact point가 들어오면 예외로 fail-closed한다.

canonical DB의 active unique contract와 별개로 read-model boundary에서도 방어한다.

### 4.3 explicit exact identity

latest month resolver도 wildcard `LIKE 'mapped_exact_%'`를 쓰지 않고 DB adapter의 `VERIFIED_IDENTITY_STATUSES`와 같은 explicit whitelist를 사용한다.

## 5. Production-data verification gate

PR #245 merge 전:

1. authoritative/production-like DB restore
2. actual sector payload 생성
3. 저축은행 tab render
4. 농·축협 tab render 및 실제 mapped row 수 확인
5. CU canonical 0건에서 CU tab 미표시 확인
6. desktop browser render
7. mobile browser render
8. horizontal overflow
9. sorting interaction
10. freshness/coverage label
11. 기존 Strategy cockpit과 충돌 없음

CI PASS와 browser runtime PASS를 구분해서 기록한다.

## 6. R2 3단 보존정책

사용자 확정사항.

### Tier 1 — authoritative operational DB

```text
state/snapshots/
최근 7개 유지
current pointer 보호
```

현재 storage service에 구현된 snapshot pruning 계약을 유지한다.

### Tier 2 — raw evidence

```text
raw-evidence/<source>/<date-or-run>/<content-hash>...
장기보존
초기 버전 자동삭제 없음
```

대상:

- 공식 API response bytes
- disclosure HTML/JSON
- quarantine evidence
- request metadata와 연결 가능한 원본

GitHub Actions artifact를 장기보존 Source of Truth로 사용하지 않는다.

### Tier 3 — intermediate/candidate

```text
intermediate/<type>/<run>/...
30일 후 자동청소
```

대상:

- candidate SQLite
- temporary reconciliation bundle
- 재생성 가능한 중간산출물

### cleanup 안전계약

- allowlisted prefix만 delete
- `state/`, `raw-evidence/` 삭제 금지
- current pointer가 참조하는 object 보호
- dry-run 지원
- 실제 삭제 목록 report
- 시간 계산은 object last-modified 또는 명시적 generated-at 계약 사용

## 7. Rate × Funding Peer Matrix

### 7.1 업권 혼합 금지

업권마다 funding 기준월/cadence가 다르므로 하나의 Matrix에 혼합하지 않는다.

현재 선택된 업권별 Matrix를 만든다.

축 라벨에 funding analysis month를 명시한다.

### 7.2 축

```text
X = 현재 선택 상품/가입기간의 기관 대표 공시금리
Y = 6M 수신증가율
Bubble size = 수신잔액
12M growth = tooltip/supporting trend
```

Y축은 6M을 primary로 한다.

12M은 최근 성장의 지속/가속/둔화를 확인하는 보조값이다.

### 7.3 X축 금리 계약

구현 전에 반드시 대표금리 정의를 코드 contract로 고정한다.

최소 결정사항:

- 기본금리 vs 최고우대금리
- 특판 포함 여부
- 예금/적금 분리
- 가입기간 정확 일치
- 동일 기관 복수상품 대표값 선정 규칙

임의로 섞지 않는다.

### 7.4 사분면

인과효과가 아니라 descriptive association이다.

```text
저금리 + 고성장 = 자연유입 강함
고금리 + 고성장 = 공격적 수신 경쟁
저금리 + 저성장 = 경쟁력 약함
고금리 + 저성장 = 비용효율 낮음
```

절대 threshold를 임의로 만들지 않고 peer population median 등 데이터 기반 기준선을 우선한다.

## 8. 현재 Strategy filter 자동 추종

Peer Matrix/Direct Peer는 별도 scope selector를 기본으로 만들지 않는다.

현재 사용자가 선택한:

- 업권
- 지역
- 예금/적금
- 가입기간

을 자동 상속한다.

필터가 바뀌면 peer population도 즉시 다시 계산/렌더한다.

## 9. Direct Peer — 지역 + 유사 수신규모

사용자 확정 구현사항.

### 9.1 기본 population

```text
현재 Strategy scope
→ 동일 업권
→ 동일 지역 우선
→ 유사 수신규모
```

### 9.2 규모 거리

고정 금액 band보다 log-balance distance를 우선 검증한다.

```text
distance = abs(log(peer_balance) - log(target_balance))
```

현재 production의 농·축협 대규모 모집단을 이용해 N과 표본 안정성을 실측한다.

후보값:

```text
direct peer target N = 12~20
minimum usable = 8
```

이 값은 상수가 아니라 실데이터 분포를 본 뒤 확정한다.

### 9.3 표본 부족 fallback

silent fallback 금지.

예:

```text
부산 동일업권 유사규모 4개
→ 비교 표본 확보를 위해 전국 동일업권 유사규모 15개로 확장
```

지역 fallback 단계는 실제 region taxonomy를 재사용한다.

새로운 임의 지역권역을 UI layer에서 만들지 않는다.

### 9.4 시각적 계층

- 선택/대상기관: strongest emphasis
- Direct Peer: primary emphasis
- 동일 업권 reference: subdued

## 10. 경쟁기관 요약

Matrix 옆/아래에 chart 해석을 자동 제공한다.

예:

```text
직접 Peer 16개 중
당사 금리 상위 31%
당사 6M 수신성장 상위 18%

공격적 경쟁기관
1. OO기관  금리 +10bp / 6M +8.2% / 규모 1.1x
2. XX기관  금리 +5bp  / 6M +7.5% / 규모 0.9x
```

복합 0~100 경쟁점수는 이번 범위에서 만들지 않는다.

## 11. 구현 순서

### Stage A — production 실측 보강 / PR #245 hardening

1. 농·축협 canonical actual mapping률 실측
2. L2 metric filter
3. duplicate fail-closed
4. latest month explicit identity whitelist
5. 기본 tab 저축은행
6. freshness
7. coverage 의미 분리
8. 95% threshold 제거
9. table sort/truncation disclosure
10. safe name fallback
11. percentile 표현 보강
12. production-data browser E2E

### Stage B — CU canonical

1. CU disclosure collector 변경분 최신 main과 충돌 검토
2. 필요한 변경만 main 계열 branch로 이식
3. 전국 collection candidate
4. QC/idempotency
5. canonical R2 publish
6. readback
7. CU tab 자동 등장 검증

### Stage C — R2 lifecycle

1. raw-evidence durable upload
2. checksum/provenance verification
3. intermediate 30-day cleanup
4. dry-run/protected-prefix tests

### Stage D — Peer Matrix

1. rate representative contract
2. Strategy filters 상속
3. rate/funding exact institution join
4. 업권별 scatter payload
5. 6M primary / 12M auxiliary
6. population median axes
7. browser UI

### Stage E — Direct Peer

1. 농·축협 실분포로 log-distance/N 검증
2. 지역 scope
3. minimum sample/fallback
4. Direct Peer highlight
5. 경쟁기관 요약

## 12. Merge gate

PR #245는 다음이 모두 끝난 뒤 merge 후보가 된다.

- data-contract hardening tests PASS
- full CI PASS
- production-data browser desktop PASS
- production-data browser mobile PASS
- actual production sectors/rows/freshness/coverage가 문서와 일치

자동 merge하지 않는다.
