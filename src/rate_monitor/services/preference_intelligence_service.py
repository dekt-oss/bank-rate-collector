"""Stage D1 우대조건 시장분석.

입력은 Strategy 전용 canonical slice다. 따라서 이 함수는 우대조건 때문에
수신이 늘었다고 추정하지 않는다. 현재 수집 데이터에서 다음 사실만 계산한다.

- 우대조건 정보가 실제로 얼마나 제공되는가
- 각 표준 우대조건이 시장에 얼마나 많이 쓰이는가
- 상위 10% 금리 상품에서 그 조건이 얼마나 더/덜 나타나는가
- 고려저축은행 현재 상품의 우대조건 구성이 무엇인가

실제 달성률·증분유입·비용효율은 내부 실적이 필요한 Stage E/D2 범위다.
"""

from __future__ import annotations

import math
from typing import Any

from rate_monitor.domain.preference_taxonomy import OTHER, labels as preference_labels

SECTORS = ("savings_bank", "cu", "kfcc", "nh_local")
TERMS = (6, 12, 24, 36)
OUR_INSTITUTION_NAME = "고려저축은행"
TOP_SHARE = 0.10
LOW_COVERAGE_THRESHOLD = 0.50

_REQUIRED_COLUMNS = {
    "sector",
    "institution",
    "product_id",
    "term_months",
    "max_rate",
    "preference",
    "preference_status",
    "preference_tags",
}


def _decode(table: dict[str, Any], column: str, value: Any) -> Any:
    lookup = (table.get("lookups") or {}).get(column)
    if lookup is None or value is None:
        return value
    try:
        return lookup[value]
    except (IndexError, TypeError):
        return None


def _rate(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _tag_set(value: Any) -> set[str]:
    if value in (None, ""):
        return set()
    return {part for part in str(value).split() if part}


def _representative_key(
    table: dict[str, Any],
    row: list[Any],
    columns: dict[str, int],
) -> tuple[Any, ...]:
    """Strategy rate 비교단위와 같은 product+term+geography 축."""
    def decoded(name: str) -> Any:
        index = columns.get(name)
        if index is None:
            return None
        return _decode(table, name, row[index])

    return (
        decoded("sector"),
        decoded("product_id"),
        row[columns["term_months"]],
        decoded("geo_basis"),
        decoded("region"),
        decoded("district"),
    )


def _representatives(table: dict[str, Any]) -> list[dict[str, Any]]:
    columns = {name: i for i, name in enumerate(table.get("columns") or [])}
    missing = sorted(_REQUIRED_COLUMNS.difference(columns))
    if missing:
        return []

    best: dict[tuple[Any, ...], dict[str, Any]] = {}
    for raw_row in table.get("rows") or []:
        sector = _decode(table, "sector", raw_row[columns["sector"]])
        term = raw_row[columns["term_months"]]
        if sector not in SECTORS or term not in TERMS:
            continue
        rate = _rate(raw_row[columns["max_rate"]])
        if rate is None:
            continue
        record = {
            "sector": sector,
            "institution": _decode(
                table, "institution", raw_row[columns["institution"]]
            ),
            "product_id": _decode(table, "product_id", raw_row[columns["product_id"]]),
            "term_months": int(term),
            "max_rate": rate,
            "preference": _decode(
                table, "preference", raw_row[columns["preference"]]
            ),
            "preference_status": _decode(
                table,
                "preference_status",
                raw_row[columns["preference_status"]],
            ),
            "preference_tags": _tag_set(
                _decode(
                    table,
                    "preference_tags",
                    raw_row[columns["preference_tags"]],
                )
            ),
        }
        key = _representative_key(table, raw_row, columns)
        current = best.get(key)
        if current is None or rate > float(current["max_rate"]):
            best[key] = record
    return list(best.values())


def _top_tier(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], float | None]:
    if not rows:
        return [], None
    ordered = sorted(
        rows,
        key=lambda row: (
            -float(row["max_rate"]),
            str(row.get("institution") or ""),
            str(row.get("product_id") or ""),
        ),
    )
    count = max(1, math.ceil(len(ordered) * TOP_SHARE))
    selected = ordered[:count]
    return selected, float(selected[-1]["max_rate"])


def _status_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"present": 0, "none": 0, "missing": 0}
    for row in rows:
        status = str(row.get("preference_status") or "missing")
        if status not in counts:
            status = "missing"
        counts[status] += 1
    return counts


def _known_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if row.get("preference_status") in {"present", "none"}]


def _category_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        for code in row.get("preference_tags") or ():
            counts[code] = counts.get(code, 0) + 1
    return counts


def _coverage(counts: dict[str, int]) -> dict[str, Any]:
    total = sum(counts.values())
    known = counts["present"] + counts["none"]
    known_share = known / total if total else 0.0
    return {
        "total_offering_count": total,
        "known_preference_count": known,
        "present_count": counts["present"],
        "none_count": counts["none"],
        "missing_count": counts["missing"],
        "known_preference_share": round(known_share, 4),
        "coverage_status": "adequate" if known_share >= LOW_COVERAGE_THRESHOLD else "low",
    }


def _scope(rows: list[dict[str, Any]], sector: str, term: int) -> dict[str, Any]:
    scope_rows = [
        row
        for row in rows
        if row["sector"] == sector and row["term_months"] == term
    ]
    if not scope_rows:
        return {
            "sector": sector,
            "term_months": term,
            "status": "no_data",
            "coverage": _coverage(_status_counts([])),
            "top_tier": None,
            "categories": [],
            "our_company": None,
        }

    top_rows, cutoff = _top_tier(scope_rows)
    market_counts = _status_counts(scope_rows)
    top_counts = _status_counts(top_rows)
    market_known = _known_rows(scope_rows)
    top_known = _known_rows(top_rows)
    market_category = _category_counts(market_known)
    top_category = _category_counts(top_known)
    labels = preference_labels()
    codes = sorted(set(market_category) | set(top_category))

    categories: list[dict[str, Any]] = []
    for code in codes:
        market_count = market_category.get(code, 0)
        top_count = top_category.get(code, 0)
        market_share = market_count / len(market_known) if market_known else None
        top_share = top_count / len(top_known) if top_known else None
        lift_pp = (
            (top_share - market_share) * 100
            if market_share is not None and top_share is not None
            else None
        )
        categories.append(
            {
                "code": code,
                "label": labels.get(code, code),
                "market_count": market_count,
                "market_share": round(market_share, 4) if market_share is not None else None,
                "top_tier_count": top_count,
                "top_tier_share": round(top_share, 4) if top_share is not None else None,
                "top_tier_lift_pp": round(lift_pp, 2) if lift_pp is not None else None,
                "is_other": code == OTHER,
            }
        )
    categories.sort(
        key=lambda item: (
            -(item["top_tier_lift_pp"] if item["top_tier_lift_pp"] is not None else -9999),
            -(item["top_tier_share"] if item["top_tier_share"] is not None else -1),
            item["label"],
        )
    )

    our_rows = [row for row in scope_rows if row["institution"] == OUR_INSTITUTION_NAME]
    our_company: dict[str, Any] | None = None
    if our_rows:
        tag_union = sorted(
            {
                tag
                for row in our_rows
                for tag in (row.get("preference_tags") or set())
            }
        )
        raw_samples = sorted(
            {
                str(row["preference"])
                for row in our_rows
                if row.get("preference") not in (None, "")
            }
        )[:5]
        our_company = {
            "offering_count": len(our_rows),
            "max_rate": round(max(float(row["max_rate"]) for row in our_rows), 4),
            "preference_status_counts": _status_counts(our_rows),
            "preference_codes": tag_union,
            "preference_labels": [labels.get(code, code) for code in tag_union],
            "raw_samples": raw_samples,
        }

    market_coverage = _coverage(market_counts)
    top_coverage = _coverage(top_counts)
    status = (
        "supported"
        if market_coverage["known_preference_count"] > 0
        else "preference_data_unavailable"
    )
    return {
        "sector": sector,
        "term_months": term,
        "status": status,
        "coverage": market_coverage,
        "top_tier": {
            "definition": "top_ceil_10pct_by_strategy_max_rate",
            "offering_count": len(top_rows),
            "cutoff_rate": round(cutoff, 4) if cutoff is not None else None,
            "coverage": top_coverage,
        },
        "categories": categories,
        "our_company": our_company,
    }


def build_preference_intelligence(strategy_table: dict[str, Any]) -> dict[str, Any]:
    """Strategy table → 시장 우대조건 구조. 유입효과는 계산하지 않는다."""
    columns = set(strategy_table.get("columns") or [])
    missing = sorted(_REQUIRED_COLUMNS.difference(columns))
    if missing:
        return {
            "version": "preference-intelligence-v1",
            "status": "schema_unavailable",
            "missing_columns": missing,
            "effect_calibration": "not_available_without_internal_performance_data",
            "scopes": [],
        }
    rows = _representatives(strategy_table)
    scopes = [_scope(rows, sector, term) for sector in SECTORS for term in TERMS]
    return {
        "version": "preference-intelligence-v1",
        "status": "ready" if any(scope["status"] == "supported" for scope in scopes) else "no_data",
        "unit": "strategy_product_term_geography_representative",
        "top_tier_definition": "top_ceil_10pct_by_strategy_max_rate",
        "category_denominator": "known_preference_products_present_or_none",
        "coverage_warning_threshold": LOW_COVERAGE_THRESHOLD,
        "effect_calibration": "not_available_without_internal_performance_data",
        "scopes": scopes,
    }
