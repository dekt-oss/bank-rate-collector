# Search UX Phase 3 closure v1

기준일: 2026-08-24

## 목적

`20260824-post-merge-improvement-master-plan-v3.md`의 Search UX Phase 3를 이번 변경으로 닫는다.

선행 완료:
- #202 Search pre-change production-backed runtime baseline
- #203 D0/D1 main-group empty/toggle contract

이번 범위:
- D1b nested parent-child 의미 최종 결정
- D2 exact 12개월 업무 프리셋
- desktop 1440 / mobile 390 production-backed browser 재검증

## D1b 최종 결정 — nested group은 select-only narrowing으로 유지

부산 구·군과 세부 우대조건은 main filter group과 같은 독립 축이 아니다.
부모가 켜져 있을 때만 의미가 있는 하위 narrowing이다.

최종 계약:

| 상태 | 의미 |
|---|---|
| parent OFF | child state 즉시 clear, filtering 비활성 |
| parent ON + child all | 하위 제한 없음 |
| parent ON + child partial | 선택 child로 명시적 narrowing |
| parent ON + child empty | 허용하지 않음. 기존 select-all recovery로 all 복구 |

따라서 nested의 `전체 선택`은 main group처럼 `전체 해제` 토글로 바꾸지 않는다.
이 결정으로 hidden stale child state와 `parent ON + child empty`의 모호한 0건/무제약 의미를 만들지 않는다.

D1b는 별도 구현 backlog가 아니라 **현행 select-only contract 유지 결정으로 closed**한다.

## D2 exact 12개월 업무 프리셋

신규 프리셋을 맨 앞에 둔다.

1. `1년 예금 · 12개월`
2. `1년 적금 · 12개월`

상태 계약:

- 예금: `type=term_deposit`, `term=7-12`, `tmin=12`, `tmax=12`
- 적금: `type=installment_savings`, `term=7-12`, `tmin=12`, `tmax=12`
- `region` / `sector`는 현재 선택을 보존
- 초기 default filter는 바꾸지 않음

`term=7-12`는 UI bucket 선택이고 `tmin=tmax=12`가 exact month constraint다.
둘을 함께 보존해야 checkbox와 scalar 입력, URL, active 상태가 같은 의미를 가진다.

## 기존 4개 프리셋 라벨 교정

동작은 기존 `term=[7-12]` 그대로 유지하고 이름만 실제 의미와 맞춘다.

- `부산 저축은행 · 7~12개월 정기예금`
- `부산 저축은행 · 7~12개월 적금`
- `부산 상호금융 · 7~12개월 정기예금`
- `부산 상호금융 · 7~12개월 적금`

기존 4개에는 `tmin/tmax=null`을 명시하여 직전 exact-12 scalar가 숨어 남지 않게 한다.

## 하나의 preset state model

프리셋 schema:

```text
{
  pick: { ...checkbox group overrides... },
  values: { ...scalar overrides... }
}
```

다음 세 동작이 같은 `pick + values` 계약을 사용한다.

- apply
- button count
- active 판정

count는 프리셋이 덮어쓰지 않는 현재 조건(지역/업권/공시일/상세조건 등)을 보존한 target state 기준으로 계산한다.
따라서 버튼에 표시된 건수와 실제 클릭 후 결과 건수가 같아야 한다.

## 불변 조건

변경하지 않는다.

- 초기 조회 universe
- 최고금리 기준
- 최근 30일 기본값
- main-group empty render gate / explicit empty URL
- 부산 구·군 exact-filter 근거 규칙
- 우대조건 parent-child semantics
- `matches()`의 main empty=no-constraint 내부 계약
- canonical/source precedence/identity
- DB/schema/migration
- collector/scheduler
- Strategy 계산
- Production Strategy Release Gate

## Acceptance

- exact 예금/적금 두 버튼이 프리셋 영역 첫 2개
- 클릭 후 `tmin=12&tmax=12`
- region/sector 보존
- 버튼 count = 클릭 결과 count
- 클릭 직후 active=true
- URL reload 후 active/count/result 동일
- scalar 직접 수정 시 active=false
- 기존 부산 4개는 `7~12개월` 라벨, exact scalar 없음
- default tmin/tmax는 empty
- nested 부산/우대 세부조건은 select-only 유지
- desktop 1440 / mobile 390 no horizontal overflow
- browser console/page error 0
- Strategy Gate OFF build
- runner-local production DB SHA before/after 동일

브라우저 acceptance의 scalar 직접 수정 단계는 상세 조건 패널을 실제 사용자 조작처럼 펼친 뒤 입력한다. 접힌 입력에 강제 값을 쓰는 테스트 전용 우회는 사용하지 않는다.

## 비범위

- nested explicit-empty URL/state 신규 설계
- combined 예·적금 프리셋
- source/canonical 변경
- Strategy Release Gate ON
