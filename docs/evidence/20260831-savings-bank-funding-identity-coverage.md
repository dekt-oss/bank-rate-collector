# 저축은행 Funding Identity Coverage — production artifact evidence

```yaml
document_type: runtime_evidence
status: verified_from_github_actions_artifacts
date: 2026-08-31
scope: savings_bank_funding_identity_coverage
source_of_truth: github_actions_artifacts
code_change: none
```

## 1. 결론

2026-08-31 기준 저축은행 기관별 funding source는 **79개 기관을 수집하고 있으며**, canonical exact identity에 연결된 기관은 **66개**, 미연결은 **13개**다.

따라서 현재 Strategy의 저축은행 funding coverage 부족은 `source가 79개를 못 가져오는 문제`가 아니라 **source identity → canonical institution 연결 문제**로 분리해야 한다.

또한 2026-03 기관합계는 ECOS 업권 합계와 사실상 일치하므로, 과거의 약 2배 discrepancy는 현재 aggregate guard 이후 canonical funding 합계의 문제가 아니다.

---

## 2. Funding collection artifact

GitHub Actions run:

- workflow/run: `33329164819`
- artifact file inspected: `publish/funding-report.json`

`coverage`의 `savings_bank / 2026-03`:

```text
institution_count                 79
mapped_count                      66
unmapped_count                    13
institution_sum_million_krw       99,573,991
```

같은 artifact의 ECOS reconciliation:

```text
sector_total_million_krw          99,574,000
difference_million_krw            -9
difference_pct                    ~0.0000090385%
coverage_ratio                    ~0.9999999096
status                            aligned
```

### 검증 경로 구분

이 문서 작성 세션에서는 GitHub Actions artifact ZIP을 내려받아 `publish/funding-report.json`을 직접 검사했기 때문에 `mapped_count=66`, `unmapped_count=13`을 artifact evidence로 기록했다.

2026-08-31 Claude 재리뷰에서는 artifact 파일 자체를 열 수 없었고 run 로그만 확인했기 때문에 다음은 독립 확인됐다.

```text
institution_count                 79
institution_sum_million_krw       99,573,991
sector_total_million_krw          99,574,000
difference_million_krw            -9
status                            aligned
```

또한 실제 발행된 `rate-data/site-public/strategy.html` payload에서 다음은 독립 확인됐다.

```text
funding_growth_6m_institutions             66
current_rate_institutions                  66
historical_rate_institutions               0
current_rate_institutions_not_carried_back 66
```

그러나 `mapped_count` / `unmapped_count`라는 **필드명 자체는 해당 run 로그에 출력되지 않는다.** 따라서 artifact 접근이 없는 제3자 검토자는 로그만으로 `mapped_count=66 / unmapped_count=13`을 재현할 수 없다.

후속 운영 acceptance:

- 다음 funding canonical run/readback에서 `mapped_count`, `unmapped_count`를 의미가 명확한 이름으로 로그에 출력하거나
- artifact evidence를 다운로드 가능한 검증절차로 고정한다.

`funding_growth_6m_institutions=66`과 `mapped_count=66`은 정의가 다를 수 있으므로 단순히 숫자가 같다는 이유로 상호 대체하지 않는다.

해석:

- Data.go institution population: 79
- artifact 기준 exact canonical mapping: 66
- artifact 기준 identity gap: 13
- 79개 기관의 합계 자체는 ECOS 업권 수신잔액과 정합
- 따라서 13개를 0으로 대체하거나 이름만으로 merge하면 안 된다.

---

## 3. Current Strategy artifact

Production-site publish artifact:

- run: `33355308640`
- inspected file: generated `strategy.html`
- embedded payload: `strategy.rate_funding_matrix.sectors.savings_bank`

확인값:

```text
analysis_month                             2026-03
status                                     historical_rate_unavailable
funding_growth_6m_institutions             66
historical_rate_institutions               0
paired_institutions                        0
current_rate_institutions                  66
current_rate_institutions_not_carried_back 66
```

contract에는 다음이 명시된다.

```text
rate_field                  max_rate
rate_representative         institution_product_representative_max
identity                    same canonical institution_id only
temporal_alignment          rate valid at funding analysis month-end
current_rate_carryback      false
missing_rate_as_zero        false
nearest_month_interpolation false
causal_interpretation       false
```

해석:

- funding source 모집단 79 중 현재 Strategy 계산 가능 population은 66이다.
- 현재 66개 금리를 2026-03 과거금리로 carry-back하지 않는다.
- `historical_rate_unavailable`은 현재 계약에 맞는 fail-closed 상태다.
- Strategy의 `66`만으로 artifact의 `mapped_count=66` 정의를 대체해서는 안 된다.

---

## 4. R0에 미치는 영향

기존 문서의 `79 / 66 / 13`은 artifact evidence가 있는 현재 관측값으로 사용한다.

단 다음은 아직 별도 검증이 필요하다.

1. 미연결 13개 각각의 `fncoCd / crno`와 canonical institution의 정확한 대응
2. 이름만으로 자동 merge하지 않는 exact mapping evidence
3. mapping remediation 후 Strategy population이 실제로 79까지 상승하는지
4. remediation 후 source total / ECOS reconciliation이 그대로 유지되는지
5. mapping 변경이 stable institution identity / historical link를 훼손하지 않는지
6. 다음 canonical run에서 mapping coverage가 log/readback으로도 재검증 가능한지

따라서 R0-B의 population 실태 파악은 이 문서로 충족하지만, R0-C identity remediation은 별도 고위험 작업으로 남는다.

---

## 5. 금지 해석

이 evidence로 다음을 주장하면 안 된다.

- 79개 모두 canonical identity가 해결됐다.
- 저축은행 pricing peer N을 지금 확정할 수 있다.
- 2026-03 historical rate가 확보됐다.
- funding 잔액과 금리 사이에 인과관계가 검증됐다.
- 13개 기관을 이름 유사도만으로 자동 연결해도 된다.
- Strategy payload의 66과 artifact `mapped_count=66`이 정의상 반드시 같은 지표다.

이 문서는 **현재 population/identity gap의 크기와 업권 합계 정합성**을 고정하고, 검증경로별 한계를 함께 기록한다.