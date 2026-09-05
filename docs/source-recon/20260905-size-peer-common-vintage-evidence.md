# Size Peer Common-Vintage Two-Axis Evidence — 2026-09-05

상태: **AUTHENTICATED READ-ONLY EVIDENCE — similarity / persistence 미활성화**

## 1. 목적

Strategy `유사 규모 peer`의 `deposit_liabilities_total + total_assets` 두 축을 서로 다른 최신월끼리 섞지 않고, **동일 공식 기관키 + 동일 기준월**에서 실제 production funding observation과 공식 Data.go 총자산 원천을 결합할 수 있는지 검증한다.

이 문서는 `docs/specs/20260905-strategy-size-peer-total-assets-v1.md`의 Stage C Evidence Gate 결과다.

## 2. 실행 계약

- production DB는 GitHub Actions runner-local copy만 읽는다.
- production R2에 upload/mutate하지 않는다.
- funding은 current production `institution_funding_observations`의 active observation을 읽는다.
- total assets는 공식 Data.go finance endpoint에서 같은 기준월을 read-only로 다시 읽는다.
- join key는 정확히 `(source_id, source_institution_key/fncoCd, source_effective_month)`다.
- 이름 유사도/이름-only identity merge를 사용하지 않는다.
- nearest-month interpolation / latest-to-latest 조합을 사용하지 않는다.
- CRNO가 양쪽에 있고 서로 다르면 fatal conflict다.
- historical observation의 `institution_id`가 미매핑이면 **현재 active SourceEntityLink를 과거에 역적용하지 않는다.** 해당 row는 `institution_identity_unmapped`로 제외한다.

## 3. 검증 실행

- branch head: `1650d4f3d2ecee012476394faf2d637775986cfe`
- full CI run: `33953295539` — **SUCCESS**
- common-vintage Evidence run: `33953295598` — **SUCCESS**
- artifact: `size-peer-common-vintage-evidence`, artifact id `9965584374`

검증 결과:

- Ruff: PASS
- common-vintage contract tests: PASS
- production DB runner-local restore: PASS
- migrations on runner-local copy: PASS
- exact common-vintage Data.go read: PASS
- artifact upload: PASS
- full repository pytest / empty-DB migration: PASS

## 4. exact common vintage

production funding에서 저축은행과 농·축협이 함께 보유한 기준월 후보:

```text
2025-12
2025-06
2024-12
2024-06
2023-12
2023-06
2022-12
2022-06
2021-12
2020-12
```

가장 최신 exact common month인 **`2025-12`**에서 두 업권의 total-assets 원천도 모두 검증되어 이 월을 Stage C evidence vintage로 선택했다.

이는 향후 모든 시점에 `2025-12`를 고정한다는 뜻이 아니다. runtime/persistence 단계에서는 매 실행 시 exact common vintage contract를 다시 적용해야 한다.

## 5. 2025-12 source coverage

### 저축은행

funding production observation:

- source rows: `79`
- exact historical canonical mapping: `66`
- historical unmapped: `13`
- unique source keys: `79`

total assets official source:

- raw finance rows: `52,240`
- `A / 자산총계` rows: `80`
- institution rows: `79`
- aggregate rows: `1`
- institution total = sector total = `117,898,974.000000 million_krw`

### 농·축협

funding production observation:

- source rows: `1,109`
- exact historical canonical mapping: `1,082`
- historical unmapped: `27`
- unique source keys: `1,109`

total assets official source:

- raw finance rows: `177,908`
- `A / 자산총계` rows: `1,126`
- institution rows: `1,109`
- aggregate rows: `17`
- institution total: `563,075,215.088950 million_krw`
- 16 regional totals는 institution total과 별도 exact equality 검증
- sector total도 institution total과 별도 exact equality 검증

## 6. two-axis distribution

동일 source key + 동일월 + exact historical canonical identity를 모두 만족한 institution candidate:

- 전체: **`1,148`**
- 저축은행: `66`
- 농·축협: `1,082`
- fatal identity/CRNO conflicts: `0`

제외:

- `institution_identity_unmapped`: **`40`**
  - 저축은행 `13`
  - 농·축협 `27`

이 40개는 자산값이나 수신값이 0인 것이 아니다. **해당 historical funding observation에 point-in-time exact canonical identity가 잠기지 않았기 때문에 비교 후보에서 제외**된 것이다.

현재 active identity link로 소급 보정하지 않는다. 향후 보완하려면 당시 원천키를 당시 기준 canonical identity에 연결하는 immutable historical identity evidence/replay가 별도 필요하다.

## 7. 고려저축은행 anchor — 2025-12

- canonical institution: `고려저축은행`
- source key: `0010390`
- CRNO: `1801110015304`
- `deposit_liabilities_total`: **`1,804,862.000000 million_krw`**
- `total_assets`: **`2,059,073.000000 million_krw`**
- 두 축 기준월: `2025-12`
- anchor status: **verified**

## 8. similarity 사전 분석 — 정책 미확정

가입가능 universe를 적용하기 전 전체 1,148개 분포에서 설명가능한 후보 거리로 다음을 시험했다.

```text
funding_gap = abs(peer_funding / anchor_funding - 1)
asset_gap  = abs(peer_assets / anchor_assets - 1)
primary_distance = max(funding_gap, asset_gap)
secondary_tie_breaker = funding_gap + asset_gap
```

이 방식은 두 축 중 한 축의 큰 차이를 다른 축의 근접성으로 상쇄하지 않는다는 장점이 있다. 다만 **REMOTE / BRANCH_BUSAN 가입가능 universe를 적용하기 전 결과이므로 아직 policy로 lock하지 않는다.**

unfiltered population에서 고려저축은행 제외 시 참고 분포:

- max gap ≤ 2%: `3`
- ≤ 5%: `9`
- ≤ 10%: `22`
- ≤ 15%: `32`
- ≤ 20%: `43`

상위 예시에는 청주축산농협, 천안농협, NH저축은행 등이 있으나, 이는 **가입가능성 필터 전 참고치**일 뿐 Strategy peer로 노출해서는 안 된다.

## 9. 다음 Evidence Gate

Stage D 전에 반드시:

1. 현재 scenario 가입가능성 기준으로 `REMOTE` / `BRANCH_BUSAN` eligible population을 실제 production evidence에서 산출한다.
2. `BRANCH_BUSAN`은 부산 16개 구·군 전체를 사용하되 official outlet/district evidence만 인정한다.
3. `REMOTE`에서 저축은행은 전국, 농·축협 등 상호금융은 explicit internet/mobile/smartphone source evidence가 있는 기관만 인정한다.
4. eligibility가 **현재 가입가능성**이고 financial size가 `2025-12` historical vintage라면 payload/UI에 두 시점을 명시적으로 분리한다. current eligibility를 2025-12 historical eligibility로 표현하지 않는다.
5. eligibility-filtered population을 측정한 뒤에만 threshold/N/similarity policy를 lock한다.
6. CU/KFCC total-assets source contract가 검증되기 전에는 두 업권을 cross-sector size-peer ready cohort에 자동 포함하지 않는다.

현재 상태에서는 `similarity_selection_enabled=false`, `persistence_enabled=false`, `eligibility_universe_applied=false`를 유지한다.
