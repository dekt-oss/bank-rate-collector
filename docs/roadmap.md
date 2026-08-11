# Roadmap — 현재 상태와 다음 작업

기준일: 2026-08-11

이 문서는 **최신 `main` 코드, `rate-data` 발행본, GitHub Actions 실행 결과**를 기준으로 한다.
과거 기획서·정찰 문서에 남아 있는 미완료 표현을 그대로 작업지시로 사용하지 않는다.

원칙:

1. 이미 구현·검증된 항목은 다시 만들지 않는다.
2. 현재 상태(Current)와 다음 목표(Target)를 분리한다.
3. 원천에 없는 값은 추정하지 않는다.
4. 신규 제품 기능과 운영·성능 최적화를 섞지 않는다.
5. PR/CI 통과만으로 완료로 보지 않고 가능한 runtime evidence까지 확인한다.

---

## 1. 현재 canonical 상태

### 1.1 코드 / 발행

- `main`: `f3abe429a82008897b84c6a193748a96d2d112ab` (PR #72 merge)
- `rate-data`: `adb53af075cada92a57869f32e717884af690a46` (Collect #61 publish)
- Stabilization v1: Issue #66 완료/종료
- 저장소 상태 DB backend: `r2`
- Vercel은 `rate-data` 발행본을 배포한다.

### 1.2 수집원

현재 실제 collector가 있는 원천은 다음 7개다.

- `finlife_savings_bank`
- `finlife_bank`
- `bok_ecos`
- `fsb`
- `cu`
- `kfcc`
- `nh_local`

FSB 수집기와 NH local 전국 수집은 이미 구현돼 있으므로 더 이상 "미구현"으로 취급하지 않는다.

### 1.3 정기 실행 구조

평일 수집은 GitHub Actions 작업당 6시간 제한 때문에 두 실행으로 나뉜다.

- 02:00 KST: KFCC를 제외한 원천 수집
- 06:00 KST: KFCC-only
- `concurrency: rate-data-writer`, `cancel-in-progress: false`로 직렬 발행
- `main` push는 원천 재수집 없이 publish-only로 화면을 다시 낸다.

현재 구조는 긴 NH/KFCC 수집을 한 job에 억지로 합치지 않는 것을 전제로 한다.

### 1.4 최신 발행 데이터

2026-08-11 08:56 KST 발행본 기준:

- institutions: 7,046
- products: 80,847
- variants: 329,286
- observations(history): 849,496
- latest KFCC: 93,382 parsed / 93,382 valid / error 0

`observations`는 change-only 이력이며 공개표 행 수와 같은 의미가 아니다.

### 1.5 운영 가시성

Stabilization v1에서 다음이 들어갔다.

- source별 latest attempt / latest success / freshness
- warning taxonomy
- `/api/health`
- 공개 화면 `수집 상태` 신호등
- collection workflow 단계 표시
- 금융기관 분류 `sector` 사용자 라벨 `업권`

오늘 NH local 최신 시도가 실패해 RED가 표시되는 것은 후속 운영 개선 대상으로 분리한다. 이 incident 자체는 Stabilization v1 재개 사유가 아니다.

---

## 2. 완료됨 — 다시 구현하지 않는다

다음 항목은 과거 roadmap에 미완료처럼 남아 있었지만 현재 완료 상태다.

- FSB 수집기
- NH local 전국 수집 경로
- 평일 core / KFCC split schedule
- BOK ECOS 인증키 whitespace 문제 수정
- R2 공식 상태 저장소 전환
- `rate-data` historyless publish 및 size/volume gate
- finlife/FSB 중복 노출 제어
- partial collection용 Current Run Gate / Historical Integrity Gate 분리
- 잘못된 `region_sigungu` 정규화 및 migration
- NH interest method의 evidence 기반 `simple/compound/unknown` 판정
- source health / warning taxonomy / freshness UI
- 금융기관 분류 `권역` → `업권`
- 기본 우대조건 상태 판정 및 taxonomy 분류

과거 정찰용 workflow나 문서에 이 항목이 "남은 것"으로 적혀 있어도 현재 `main`/runtime이 우선한다.

---

## 3. 아직 남은 제품 기능

이 절은 **제품 기능 후보**다. 자동 착수하지 않고 사용자 우선순위 결정 뒤 새 Issue/branch에서 시작한다.

### 3.1 기본금리 + 우대금리 + 우대조건 구조화/표출

현재:

- `base_rate`, `max_rate`, `raw_preference_text` 저장
- 우대조건 `present / none / missing` 판정
- taxonomy 분류 코드 및 화면 필터 존재
- `preference_conditions` 테이블은 스키마만 있고 조건 단위 구조화는 미구현

다음 단계 후보:

- 조건 문장 분해
- 표준 condition code 매핑
- 조건별 `add_rate`, `mandatory`, `stackable` 의미 보존
- 기본금리 / 최고금리 / 우대조건을 한 화면에서 혼동 없이 표출
- 원천 미제공과 실제 없음의 명확한 분리

주의:

- KFCC처럼 `max_rate` 자체가 없는 원천은 우대금리를 추정하지 않는다.
- NH의 일부 `raw_preference_text`는 우대조건이 아니라 상품 설명이다.
- `base_rate`로 `max_rate`를 대체하지 않는다.

### 3.2 KFCC 요구불예탁금

`gubuncode=12`의 금액 구간형 상품은 아직 대상이 아니다.
`amount_min` / `amount_max` 스키마는 있으나 단계금액 파싱·identity 검증이 필요하다.

### 3.3 NH local 입출금식 화면

`SFDPW0162R` 실물 fixture와 source contract가 없으므로 현재 수집하지 않는다.
실물을 먼저 확보하고 parser를 설계해야 한다.

### 3.4 Manual Override / 관리자 편집

DB에는 `manual_overrides` 계약이 있지만, 현재 정적 사이트 구조에서 편집 입력·병합·충돌 처리·감사 흐름은 구현하지 않았다.
서버 런타임을 새로 만들지, GitHub/설정 파일 기반 운영으로 유지할지 제품 결정이 선행되어야 한다.

### 3.5 교차대조

finlife와 FSB가 같은 저축은행 상품을 동시에 제공할 때 차이를 `review_items`로 남기는 정식 cross-source difference 경로는 별도 기능 후보로 남긴다.

### 3.6 Excel 내보내기

CSV/JSON은 존재한다. XLSX는 P2 성격의 편의 기능으로 남긴다.

---

## 4. 운영상 아직 남은 것

### 4.1 원본 1년 보존

현재 `data/raw`는 GitHub Actions artifact에 90일 보존된다.
R2는 현재 canonical 상태 DB 저장에 사용되며, raw 원본 1년 보존 계약을 충족하는 별도 경로는 아직 확정하지 않았다.

따라서 "원본 최소 1년" 요구를 계속 유지한다면 별도 retention 설계가 필요하다.

### 4.2 공식 행정구역 코드

`sido_code` / `sigungu_code`는 공식 코드 확보 전까지 NULL 계약이다.
현재 화면 지역은 검증된 주소 파생값이다. 외부 행정코드 도입은 별도 source/evidence 작업으로 본다.

### 4.3 이용약관 / policy status

원천별 자동 수집 허용성에 대해 과거 문서에 `review` / `unknown`이 남아 있는 부분은 제품 기능과 분리해 운영·법무 확인 항목으로 관리한다.

### 4.4 NH transient failure

2026-08-11 core run의 `nh_local` latest attempt가 connection failure였다.
직전 정상 데이터를 유지하고 RED로 표시하는 관측 경로는 정상 동작했다.

원인·retry/backoff·timeout 정책 개선은 별도 운영 이슈로 분석한다. Stabilization v1을 다시 열지 않는다.

---

## 5. 다음 최적화·마무리 작업 후보

신규 제품 기능에 들어가기 전에 아래를 **Optimization v1** 후보로 둔다.

### O1. Production smoke 자동화 — 우선 권고

목표:

- publish 후 실제 배포가 살아 있는지 자동 확인
- `/api/health` 응답 contract 확인
- `업권` 등 필수 사용자 문구 확인
- latest `rate-data`와 production deploy가 어긋나면 실패/경고

이유:

현재 CI와 publish gate는 강하지만, 마지막 production HTTP smoke는 도구 권한·브라우저 환경에 따라 수동 확인이 남을 수 있다.
코드가 아니라 **실제 배포 결과**를 자동 증거로 남기는 것이 마무리 단계에서 가장 가치가 크다.

### O2. 정적 사이트 payload / 브라우저 성능 baseline

최신 `rate-data` 기준:

- `site-public/data/table.json`: 약 21.25 MB raw
- `table.json.gz`: 약 1.79 MB
- `index.html`: 약 444 KB

먼저 실제 브라우저에서 다음을 측정한다.

- fetch + decompress + JSON parse 시간
- 초기 render 시간
- 필터 1회 latency
- peak memory
- 모바일/저속 회선 체감

측정치가 기준을 넘을 때만 sharding / lazy loading / index 분리를 적용한다.
"파일이 크다"는 이유만으로 구조를 복잡하게 만들지 않는다.

### O3. Repository / workflow hygiene

현재 main에는 과거 evidence/recon용 수동 workflow가 남아 있다.
예: `p0-kfcc-capture.yml`, `p2-ecos-recon.yml`.

삭제를 전제로 하지 않고 먼저 다음을 감사한다.

- 아직 recovery/debug에 쓰이는가
- 문서에서 호출하는가
- active workflow와 이름/목적이 겹치는가
- 남길 경우 이름과 설명이 현재 상태를 오해하게 만들지 않는가

불필요한 것만 제거하고, runtime 복구에 유용한 probe는 유지한다.

### O4. 수집 runtime / reliability 최적화 — 별도 고위험 트랙

NH/KFCC는 외부 원천 부하가 크므로 무작정 병렬화하지 않는다.

검토 순서:

1. 요청별 latency / timeout / retry 분포 측정
2. transient failure 유형 분리
3. bounded retry + jitter/backoff 검토
4. source-friendly request pacing 유지 여부 확인
5. 병렬화가 필요하면 원천별 허용 근거를 확보한 뒤 제한적으로 적용

오늘 NH RED 분석은 이 트랙에서 별도 진행한다.

### O5. 장기 보존 / 복구 drill

- R2 current restore 정기 검증
- snapshot 무결성 확인
- raw 1년 보존 필요 여부 확정
- 필요 시 raw archive 경로 설계

---

## 6. 권고 실행 순서

현재 권고 순서는 다음이다.

1. **Optimization v1 준비**
   - O1 production smoke automation
   - O2 static payload/browser baseline
   - O3 repo/workflow hygiene
2. O4 NH/KFCC reliability는 별도 운영 세션에서 병행
3. O5 retention은 요구사항 유지 여부 확인 후 착수
4. Optimization v1 종료 뒤 사용자와 다음 제품 기능 우선순위 결정
5. 제품 기능 후보 중 `기본금리 + 우대금리 + 우대조건 구조화/표출`을 우선 검토하되 자동 착수하지 않음

---

## 7. 완료 판정 원칙

다음 작업도 동일한 Evidence Gate를 적용한다.

- 코드가 있음을 완료로 보지 않는다.
- test/CI만 통과했다고 runtime 완료로 보지 않는다.
- production 기능은 가능한 경우 실제 production 결과를 확인한다.
- 외부 원천 관련 변경은 실제 source evidence를 확보한다.
- 데이터 계약 변경은 migration/history/consumer를 함께 검증한다.
- 검증하지 못한 것은 미검증으로 명시한다.
