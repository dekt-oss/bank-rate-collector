# 저축은행 원천 교차검증 v1 — 2026-08-13

## 목적

저축은행 금리를 전략·시뮬레이터에 쓰기 전에 서로 다른 공식 원천이 같은 값을 말하는지 자동 감사한다.

v1은 **감사 전용(read-only)** 이다. FSB, 금융상품한눈에, 개별 저축은행 홈페이지 중 어느 한 값을 자동으로 canonical에 덮어쓰지 않는다.

## 현재 source 역할

- `fsb`: 저축은행중앙회. 현재 공개 비교표의 primary source.
- `finlife_savings_bank`: 금융상품한눈에. DB에 보존하지만 현재 공개 비교에서는 secondary/cross-check 역할.
- 개별 저축은행 공식 홈페이지: 현재 공통 collector가 없으므로 URL·캡처시각을 가진 외부 evidence JSON으로 감사에 주입할 수 있다.

## 현재값 선택

각 source에서 `success / partial / no_change` 중 가장 최근 run을 찾고, `rate_observations.last_run_id`가 해당 run인 valid/current 관측만 읽는다.

`rate_observations`는 값이 바뀔 때만 새 행을 만들기 때문에:

- `run_id`: 현재 값이 처음 관측된 run
- `last_run_id`: 현재 값을 마지막으로 다시 확인한 run
- `raw_artifact_id`: `run_id`에서 현재 값을 처음 본 원본 artifact

이다. 따라서 리포트의 `raw_artifact_path`는 **현재 값을 처음 만든 원본 증거**이며 마지막 확인 run의 artifact라고 오해하면 안 된다.

## 상품 대표값

교차검증은 화면의 시장 대표 기준과 같은 방향으로 variant를 압축한다.

- source
- 금융기관
- 상품 정규명
- 상품유형
- 가입기간

이 같은 variant 가운데 최고 `max_rate` 관측을 대표값으로 쓴다. 동일 최고금리면 `source_effective_at`이 더 최근인 행의 provenance를 사용한다.

## 자동 매칭

자동으로 같은 상품이라고 판정하는 키:

`정규화 기관명 + 정확히 정규화된 상품명 + 상품유형 + 가입기간`

상품명은 공백·특수문자 수준만 정규화한다. 채널명·괄호·상품 수식어를 임의 삭제하지 않는다. false merge가 false negative보다 위험하기 때문이다.

정확 상품명이 안 붙지만 `기관 + 상품유형 + 기간`에는 상대 source 후보가 존재하면 `unmatched_product`로 남긴다. 후보가 전혀 없으면 `source_only`다.

## 금리·기준일 상태 분류

최고금리는 전략 순위에 직접 쓰이므로 top-level 상태로 관리한다.

- `agree`: 최고금리 일치 + 기준일 동일
- `agree_rate_date_diff`: 최고금리 일치 + 기준일 다름
- `agree_rate_date_unknown`: 최고금리 일치 + 한쪽 이상 기준일 미확인
- `rate_mismatch`: 최고금리 불일치 + 기준일 동일
- `rate_mismatch_date_diff`: 최고금리 불일치 + 기준일 다름
- `rate_mismatch_date_unknown`: 최고금리 불일치 + 한쪽 이상 기준일 미확인
- `incomplete_rate`: 매칭됐지만 최고금리가 한쪽 이상 누락
- `unmatched_product`: 상대 source에 같은 기관/상품유형/기간 후보가 있으나 정확 상품명이 안 붙음
- `source_only`: 상대 source 비교 후보가 없음

기준일은 별도로 `same / different / unknown`을 기록한다. 한쪽 기준일이 없다고 `same`으로 간주하지 않는다.

기본금리도 각 exact match에서 독립적으로 `agree / mismatch / incomplete / both_missing`으로 비교한다. 기본금리와 최고금리 차이는 모두 `primary - secondary` Decimal 문자열로 기록한다.

## Provenance

매칭된 양쪽 행에 다음을 보존한다.

- source id
- 기관명 / 상품명 / 상품유형 / 가입기간
- 가입채널 / 이자방식
- 기본금리 / 최고금리
- `source_effective_at`
- `run_id` / `last_run_id`
- observation id
- base / option source locator
- source record hash
- raw artifact relative path / SHA-256

## 개별 금융사 공식 홈페이지 evidence

`scripts/source_discrepancy_audit.py --official-evidence <json>`으로 제3의 공식 증거를 추가할 수 있다.

```json
{
  "records": [
    {
      "institution": "금융기관명",
      "product": "공식 상품명",
      "product_type": "term_deposit",
      "term_months": 12,
      "base_rate": "3.80",
      "max_rate": "3.80",
      "effective_at": "2026-08-13",
      "captured_at": "2026-08-13T14:00:00+09:00",
      "url": "https://official.example/product"
    }
  ]
}
```

이 evidence는 DB에 저장하거나 canonical을 수정하지 않는다. 정확 상품 키가 붙는 FSB/finlife 행과만 나란히 비교하며 기본금리·최고금리를 각각 비교한다.

## Production R2 최신 실측

Source discrepancy audit #8 / run `31674837679`, snapshot `state/snapshots/20260813T123319-61fe7160.sqlite3.gz`:

- FSB 대표상품: 2,166
- 금융상품한눈에 대표상품: 1,030
- exact matches: 924
- 최고금리 `agree`: 229
- 최고금리 `agree_rate_date_diff`: 679
- 최고금리 `agree_rate_date_unknown`: 0
- 최고금리 `rate_mismatch`: 2
- 최고금리 `rate_mismatch_date_diff`: 14
- 최고금리 `rate_mismatch_date_unknown`: 0
- 최고금리 `incomplete_rate`: 0
- 기본금리 `agree`: 908
- 기본금리 `mismatch`: 16
- 기본금리 `incomplete`: 0
- 기본금리 `both_missing`: 0
- `unmatched_product`: 165
- `source_only`: 1,183

즉 확실히 같은 상품으로 자동 매칭된 924건 중 **16건에서 기본금리와 최고금리가 모두 불일치**했고, 이번 snapshot의 exact match에는 기준일 미확인 행이 없었다.

### 동일 기준일인데 금리가 다른 사례

청주저축은행 정기적금:

- 12개월: FSB 3.80 / finlife 4.00 / 양쪽 `source_effective_at=2026-08-10`
- 6개월: FSB 2.10 / finlife 3.05 / 양쪽 `source_effective_at=2026-08-10`

### 금리와 기준일이 함께 다른 사례

금화·대신·대원·아산·진주·하나저축은행 등에서 검출됐다. 예:

- 아산저축은행 `SB톡톡-정기예금` 12개월: FSB 2.50 (2025-12-03), finlife 4.10 (2026-07-20)
- 진주저축은행 `정기예금(진주,통영)` 12개월: FSB 3.63 (2026-07-24), finlife 2.30 (2026-07-20)

이 유형은 어느 값이 잘못됐다고 자동 판정하지 않고 source freshness/시행일 확인 대상으로 남긴다.

## 현재 한계

1. 정확 상품명 자동매칭이 보수적이라 165건은 사람이 identity 규칙을 추가 검토해야 한다.
2. FSB가 제공하는 `source_effective_at`과 실제 금리 시행일의 의미가 상품별로 같은지 별도 검증이 필요하다.
3. 개별 저축은행 홈페이지는 아직 공통 자동 collector가 아니다. v1은 evidence 입력 계약만 제공한다.
4. raw artifact는 현재 값을 처음 관측한 artifact다. 마지막 확인 run의 raw row를 직접 연결하려면 별도 provenance 확장이 필요하다.
5. 이 리포트는 warning/evidence이지 canonical source authority 결정기가 아니다.
6. 같은 상품·기간의 source별 대표 최고금리를 비교하므로 가입채널/이자방식 coverage 차이가 불일치 원인일 수 있다. provenance의 variant context를 함께 확인해야 한다.

## 다음 단계

- 대백 애플정기예금처럼 사용자 영향이 큰 사례를 official evidence JSON으로 재현한다.
- `unmatched_product` 165건의 상품명 패턴을 감사해 안전한 alias만 수동 규칙으로 추가한다.
- source별 freshness/authority 정책을 ADR 또는 별도 spec으로 확정한다.
- 확정 후 전략 대시보드에 `원천 일치 / 기준일 차이 / 금리 불일치` 신호만 표출한다.
- 자동 canonical 보정은 별도 승인 전 구현하지 않는다.
