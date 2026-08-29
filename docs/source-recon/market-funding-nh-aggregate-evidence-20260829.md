# Data.go 농·축협 수신잔액 aggregate-row 전수 감사 — 2026-08-29

## 1. 결론

2026-08-28 authenticated backfill artifact(run `33179969040`)의 농업협동조합 `A1 예수부채` target table을 기준월별로 다시 전수 감사했다.

현재 DB에 기관 observation으로 저장된 농·축협 11,273행에는 **실제 단위 농·축협이 아닌 업권/지역 합계 pseudo-row 154행**이 섞여 있다.

- 실제 단위 농·축협: **11,119행**
- 지역 합계: **144행** (16개 지역 × 9개 보고월)
- 업권 합계: **9행**
- 2020 legacy 업권 합계: **1행**
- 합계: **11,273행**

2021-12 이후 보고월에서는 저장된 전체 합계가 실제 단위 농·축협 합계의 **정확히 4배**가 된다.

원인은 한 target table 안에 다음 계층이 동시에 존재하기 때문이다.

1. 실제 개별 농·축협 행
2. 16개 지역별 합계 행
3. `농협단위조합` 업권 합계 행

지역합계 16개의 합은 실제 기관합과 정확히 같고, `농협단위조합` 행은 `실제 기관합 + 지역합`과 정확히 같다. 이를 다시 모두 기관처럼 합산하면 `실제 + 지역 + 업권 = 4 × 실제`가 된다.

따라서 raw 원문은 그대로 보존하되, 검증된 aggregate hierarchy는 `InstitutionFundingObservation` 기관 후보에서 제외해야 한다.

## 2. Evidence source

- GitHub Actions run: `33179969040`
- artifact: `institution-funding-33179969040`
- artifact id: `9690450435`
- artifact digest: `sha256:35560d1f7de184adc713a0ae4ba50ffae91908ee103b18fd2020ae7a39e4461a`
- target table: `농협_재무현황_요약재무상태표(부채및자본)`
- account code: `astDebtSmryBlnshDcd=A1`
- account name: `예수부채`

이 artifact는 저축은행 canonical account 검증에는 사용할 수 없지만, 농·축협 A1 target rows에 대해서는 당시 operational backfill이 실제 저장한 source evidence다.

## 3. 식별 계약

### 3.1 실제 단위 농·축협

현재 실측 row의 실제 기관 `fncoCd`는 모두 다음 구조다.

```text
0010027 + 6자리 숫자 BRC
```

예:

```text
남부산농협
fncoCd = 0010027121020
BRC suffix = 121020
```

### 3.2 2020 legacy total

```text
fncoCd = 032120S
fncoNm = 농업협동조합
```

2020-12에서 이 행의 금액은 실제 1,118개 기관 합과 정확히 같다.

### 3.3 2021-12 이후 current hierarchy

업권 합계:

```text
fncoCd = 030801S
fncoNm = 농협단위조합
```

지역 합계 16개:

```text
0321301S 농협(서울)
0321302S 농협(부산)
0321303S 농협(대구)
0321304S 농협(인천)
0321305S 농협(광주)
0321306S 농협(대전)
0321307S 농협(울산)
0321308S 농협(경기)
0321309S 농협(강원)
0321310S 농협(충북)
0321311S 농협(충남)
0321312S 농협(전북)
0321313S 농협(전남)
0321314S 농협(경북)
0321315S 농협(경남)
0321316S 농협(제주)
```

모든 aggregate row의 `crno`는 빈 값이다.

## 4. 기준월별 전수 결과

금액 단위는 million KRW로 변환한 값이다.

| 기준월 | 전체행 | 실제기관 | 지역합계 | 업권합계 | legacy | 실제기관 합 | 지역합계 합 | 업권합계 값 | 전체/실제 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2020-12 | 1,119 | 1,118 | 0 | 0 | 1 | 362,138,879.135540 | 0 | - | 2.0x |
| 2021-12 | 1,134 | 1,117 | 16 | 1 | 0 | 383,595,275.270240 | 383,595,275.270240 | 767,190,550.540480 | 4.0x |
| 2022-06 | 1,131 | 1,114 | 16 | 1 | 0 | 397,655,380.009289 | 397,655,380.009289 | 795,310,760.018578 | 4.0x |
| 2022-12 | 1,129 | 1,112 | 16 | 1 | 0 | 408,256,003.463658 | 408,256,003.463658 | 816,512,006.927316 | 4.0x |
| 2023-06 | 1,127 | 1,110 | 16 | 1 | 0 | 424,026,978.625572 | 424,026,978.625572 | 848,053,957.251144 | 4.0x |
| 2023-12 | 1,127 | 1,110 | 16 | 1 | 0 | 431,434,611.920051 | 431,434,611.920051 | 862,869,223.840102 | 4.0x |
| 2024-06 | 1,127 | 1,110 | 16 | 1 | 0 | 444,479,466.723153 | 444,479,466.723153 | 888,958,933.446306 | 4.0x |
| 2024-12 | 1,127 | 1,110 | 16 | 1 | 0 | 452,411,066.746983 | 452,411,066.746983 | 904,822,133.493966 | 4.0x |
| 2025-06 | 1,126 | 1,109 | 16 | 1 | 0 | 464,978,775.317558 | 464,978,775.317558 | 929,957,550.635116 | 4.0x |
| 2025-12 | 1,126 | 1,109 | 16 | 1 | 0 | 473,023,786.997895 | 473,023,786.997895 | 946,047,573.995790 | 4.0x |

2021-06 및 2026-06은 artifact에서 target rows 0건이라 위 검증 denominator에서 제외했다. 빈 응답을 이전 값으로 보간하지 않는다.

## 5. Exact invariants

2020-12:

```text
legacy_total(032120S) == sum(real institution rows)
```

2021-12 이후 9개 관측월 전부:

```text
sum(16 regional aggregate rows) == sum(real institution rows)
sector_total(030801S) == sum(real institution rows) + sum(16 regional aggregate rows)
sector_total(030801S) == 2 * sum(real institution rows)
```

금액 equality는 Decimal 기준 exact equality다. tolerance를 사용하지 않았다.

## 6. ECOS sanity check

기존 backfill reconciliation에서 2022-12~2025-12의 잘못된 전체 합은 ECOS 광의 상호금융 대비 약 3.56배였다.

aggregate rows를 제거한 실제 단위 농·축협 합 / ECOS 광의 상호금융 비율은 같은 기간 약 **0.8897~0.8927**이다.

이는 ECOS 광의 상호금융이 농·수·산림계 등을 포함하는 더 넓은 모집단이라는 기존 계약과 방향상 일치한다. 다만 이 비율을 equality gate로 사용하지 않는다.

## 7. 구현 Gate

기관 observation에서 aggregate를 제외할 때 다음을 모두 만족해야 한다.

1. raw artifact는 수정/삭제하지 않는다.
2. aggregate code/name/CRNO 계약을 exact 검증한다.
3. 2020 legacy shape와 2021+ current hierarchy를 구분한다.
4. current hierarchy가 일부만 존재하면 fail-closed한다.
5. regional sum / sector total의 exact arithmetic invariant가 깨지면 fail-closed한다.
6. 이미 DB에 저장된 aggregate active rows는 `valid_to`로 retire하고 삭제하지 않는다.
7. 신규 수집에서는 persistence 전에 제외하여 pseudo-row revision을 더 만들지 않는다.
8. 실제 단위 농·축협 row는 삭제/퇴역시키지 않는다.

## 8. 기대 active count

기존 authenticated backfill 기준:

```text
NH active observations: 11,273 -> 11,119
removed active aggregate rows: 154
```

저축은행 sector-total 수정 후 예상 1,817행과 합치면, 신협 funding이 아직 없는 현재 기관별 funding active total의 기대값은:

```text
1,817 + 11,119 = 12,936
```

이 수치는 fresh canonical backfill + authoritative R2 readback으로 다시 검증하기 전까지 runtime 완료값으로 선언하지 않는다.
