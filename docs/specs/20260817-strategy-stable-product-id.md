# 전략 대시보드 stable product_id 전달 계약

```yaml
document_type: work_order
status: implementation
created_at: 2026-08-17
base_commit: 91557be0d4d651dc2ad435240d9ef52225a71e72
issue: 108
risk: identity/public-contract
```

## 1. 결론

상호금융 Evidence Gate에서 확인된 새마을금고 2,175행·농축협 1,335행의 strategy identity 미매칭은 persisted identity 누락이 아니다.

Production snapshot `state/snapshots/20260817T160518-84b7b10c.sqlite3.gz`에서 현재 strategy display-key 재조인을 후보 전체로 다시 분석한 결과:

| sector | 대상 행 | unique | ambiguous | missing |
|---|---:|---:|---:|---:|
| kfcc | 24,464 | 22,289 | **2,175** | **0** |
| nh_local | 73,020 | 71,685 | **1,335** | **0** |

즉 모든 미매칭은 `institution canonical_name + product name + term + payment/interest/join` 표시키 하나가 2개 이상의 stable `product_id`를 가리켜 안전장치가 매칭을 거부한 경우다.

## 2. Root cause

DB의 실제 product identity는 canonical institution UUID를 포함한 source entity key로 분리돼 있다. 그러나 canonical 공개 table은 사용자 표시용 금융사명을 싣고 stable UUID를 싣지 않는다.

예:

```text
kfcc / 제일 / 꿈드림회전정기예탁금 / 12개월
→ 서로 다른 institution UUID에 속한 product_id 4개

nh_local / 대산농협 / 정기예탁금 / 6개월
→ 서로 다른 institution UUID에 속한 product_id 4개
```

따라서 표시명을 더 정규화하거나 이름 fallback을 추가하는 것은 해결이 아니라 identity merge 오류를 만든다.

## 3. Target state

Strategy Gate가 켜진 build에서만 DB query 시점의 `products.id`를 internal `product_id` column으로 함께 운반한다.

```text
DB row (p.id 포함)
→ canonical packed table + internal product_id
→ strategy slice
→ stable product_id 그대로 사용

동시에
canonical packed table + internal product_id
→ internal column 제거
→ 기존 public data/table.json
```

공개 canonical table의 columns/lookups/rows bytes 계약은 바꾸지 않는다.

## 4. FREEZE

- institutions/products/source_entity_links를 merge·rewrite하지 않는다.
- migration을 만들지 않는다.
- canonical_name 기반 fallback을 추가하지 않는다.
- source precedence/dedupe/rate calculation을 변경하지 않는다.
- Release Gate를 켜지 않는다.
- 기존 `table.json` public schema에 `product_id`를 노출하지 않는다.

## 5. 구현 계약

1. `build_rate_table(..., include_product_id=True)`일 때만 `p.id`를 압축 lookup column으로 추가한다.
2. 기본값은 `False`이며 기존 caller의 canonical table 계약은 그대로다.
3. `build_summary(..., include_product_id=True)`는 strategy build에서만 사용한다.
4. `site_service.build_site()`는 strategy build를 결정한 뒤 internal-id table을 strategy slice에 먼저 전달하고, 공개 table을 쓰기 전 internal column을 제거한다.
5. `augment_strategy_table()`은 이미 `product_id`가 있는 경우 재조인하지 않는다. 단, null product_id가 있으면 build를 실패시킨다.
6. legacy display-key join path는 호환성 때문에 유지하지만 신규 site build path에서는 사용하지 않는다.

## 6. Verification Gate

- Strategy OFF vs ON의 `data/table.json` bytes가 동일해야 한다.
- Strategy ON의 `data/strategy-table.json`에는 `product_id`가 있고 null이 없어야 한다.
- production read-only copy에서 kfcc/nh_local target row는 direct DB `product_id`를 100% 운반해야 한다.
- 기존 저축은행 strategy build/Preview/UI가 회귀하지 않아야 한다.
- ruff / full pytest / migration / Strategy Preview를 통과해야 한다.

## 7. 범위 밖

이 PR은 상호금융을 실제 전략 화면 universe에 추가하지 않는다. 최고금리 semantic 통일도 별도 source evidence 작업이다.
