# Data.go 농·축협 수신잔액 ↔ NH 금리원천 BRC identity 감사 — 2026-08-29

## 1. 목적

Data.go 농업협동조합 수신잔액은 `fncoCd`를 기관 식별자로 제공하지만 현재 금리 수집의 NH local 원천은 6자리 `brc`를 사용한다.

기존 funding identity resolver는 두 원천의 key 형식이 다르기 때문에 농·축협 funding observation을 canonical institution에 연결하지 못했고, authenticated backfill의 active 농·축협 observation 11,273행은 모두 unmapped 상태였다.

aggregate pseudo-row 154행은 별도 수정에서 제거했으므로, 이 문서는 남은 **실제 단위 농·축협 11,119행**에 대해 결정론적 cross-source identity가 가능한 범위를 감사한다.

## 2. Evidence source

### Data.go funding

- GitHub Actions run: `33179969040`
- artifact: `institution-funding-33179969040`
- artifact id: `9690450435`
- source: 금융위원회 금융통계 농업협동조합정보
- account: `astDebtSmryBlnshDcd=A1` / `예수부채`

### NH local rate directory

- GitHub Actions run: `31956936041`
- artifact: `nh-attempt-1-31956936041`
- artifact id: `9269227044`
- official source: `wmall.nonghyup.com/servlet/SFDPW0161R.view`
- 전국 official outlet directory: 4,871 rows

## 3. Key relation

실제 단위 농·축협 Data.go `fncoCd`는 audited rows에서 다음 구조를 가진다.

```text
0010027 + 6자리 숫자 BRC
```

예:

```text
Data.go
  fncoCd = 0010027121020
  fncoNm = 남부산농협

NH official directory
  brc = 121020
  name = 남부산농협
```

즉 Data.go key의 마지막 6자리가 NH 공식 directory의 BRC와 직접 연결된다.

중요: 이 관계는 문자열 유사도 추측이 아니라 두 공식 원천의 실제 key 값에 대한 결정론적 관계다. 다만 BRC가 현재 directory에 존재한다는 것만으로 과거 기관의 법적 동일성을 자동 확정하지 않는다. 이름까지 일치하는 observation만 자동 매핑한다.

## 4. 최신 2025-12 census

aggregate를 제외한 실제 기관 1,109행 기준:

| Gate | 결과 |
|---|---:|
| Data.go real institution rows | 1,109 |
| BRC suffix가 NH official directory에 존재 | 1,109 / 1,109 |
| BRC + source name exact match | 1,082 / 1,109 |
| BRC는 같지만 이름 불일치 | 27 |

따라서 최신 모집단에서 deterministic BRC coverage는 100%지만, **자동 identity mapping 허용 범위는 이름까지 일치하는 1,082개**로 제한한다.

이름 불일치 예시는 다음 유형을 포함한다.

- 지역 prefix 변화: `금오농협` ↔ `하동금오농협`
- 명칭 확장: `예산축협` ↔ `예산축산농협`
- 원예/능금 명칭 변경: `대구경북능금농협` ↔ `대경사과원예농협`
- 통폐합/지점화 가능성: `내남농협` ↔ `경주농협 내남지점`
- 후계/개명 가능성: `의성중부농협` ↔ `의성농협`

이 27개는 코드가 같다는 이유만으로 자동 merge하지 않는다.

## 5. 전체 backfill history census

aggregate 제거 후 실제 observation 11,119행 기준:

| Gate | 결과 |
|---|---:|
| real funding observations | 11,119 |
| BRC suffix가 current NH official directory에 존재 | 11,119 / 11,119 |
| BRC + source name exact match | 10,783 / 11,119 |
| 이름 불일치 observation | 336 |

역사 전체 distinct Data.go institution key는 1,119개다.

- 모든 관측월에서 current NH 이름과 일치: 1,052 keys
- 일부 월은 일치하고 일부 월은 불일치: 30 keys
- current NH 이름과 한 번도 일치하지 않음: 37 keys

따라서 source key 하나에 대해 한 번 exact match가 나왔다고 그 key의 모든 과거 observation을 같은 canonical institution으로 소급 연결하면 안 된다. 개명·합병·지점화가 섞일 수 있다.

## 6. 자동 매핑 계약

각 funding observation에 대해 아래를 **모두** 만족할 때만 canonical institution을 연결한다.

1. source가 `data_go_agri_coop_funding`
2. Data.go key가 실측 real-institution 구조 `0010027 + 6자리 숫자`를 만족
3. suffix 6자리에 대해 active `nh_local` institution link가 정확히 1개 존재
4. 해당 NH link의 institution sector가 `nh_local`
5. Data.go `fncoNm`과 NH source/institution name이 repo normalization 후 exact match

허용 결과:

```text
identity_status = mapped_exact_nh_brc_name
institution_id = matched NH canonical institution id
```

금지:

- 이름 유사도/fuzzy match
- 지역명 prefix를 임의 제거해 매칭
- BRC만 같다는 이유로 27개 mismatch 자동 merge
- 현재 이름을 과거 observation 전체에 소급 적용
- funding source key에 영구 cross-source link를 만들어 이름이 다른 역사까지 자동 흡수

## 7. 기존 observation repair

현재 active history의 unmapped observation은 새 수집만 기다리면 자동 수정되지 않는다. 값/content hash가 unchanged이면 기존 `_upsert_point`가 observation identity metadata를 갱신하지 않기 때문이다.

따라서 별도 idempotent reconciliation pass가 필요하다.

- active funding observation을 observation 단위로 검사
- 위 exact BRC + name gate를 통과한 행만 `institution_id`와 `identity_status`를 갱신
- 불일치 336행은 그대로 unmapped
- 금액, source value, revision, valid_from/valid_to, raw provenance는 변경하지 않음
- `SourceEntityLink`를 funding key 전체에 생성하지 않음

이 방식은 historical amount revision과 identity reconciliation을 분리한다.

## 8. 기대효과와 Runtime Gate

현재 evidence 기준 exact auto-map 기대값:

```text
10,783 / 11,119 = 약 97.0% observations
2025-12 current institutions: 1,082 / 1,109 = 약 97.6%
```

나머지는 review population으로 남긴다.

실제 적용 완료 판정은 authoritative R2 DB에서 다음을 확인한 뒤 한다.

1. aggregate active rows = 0
2. NH real funding active observation count가 source coverage와 일치
3. `mapped_exact_nh_brc_name` 수와 unmapped 수 readback
4. 동일 reconciliation 재실행 시 변경 0건
5. amount/revision/raw provenance row count 및 hash 계약 불변
6. integrity/FK PASS
7. R2 upload 후 restore/readback PASS
