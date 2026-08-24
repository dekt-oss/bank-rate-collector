"""Payment-method ambiguity를 조사 가능한 census로 변환한다.

Source discrepancy의 6D 비교는 payment_method가 여러 값으로 갈리고 rate pair도
다르면 fail-closed한다. 이 모듈은 그 차단 항목을 계량할 뿐 canonical/source
authority를 선택하거나 DB를 수정하지 않는다.
"""

from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from rate_monitor.domain.normalization import normalize_product_name
from rate_monitor.services.institution_matching import normalize_institution

CENSUS_POLICY_VERSION = "payment-method-ambiguity-census-v1"


def _decimal(value: object) -> Decimal | None:
    if value in {None, ""}:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _decimal_json(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None


def _risk_band(delta: Decimal | None) -> str:
    """Triage의 max-rate gap band와 동일한 경계를 census에 재사용한다."""
    if delta is None:
        return "unknown"
    if delta >= Decimal("1.0"):
        return "ge_1.00pp"
    if delta >= Decimal("0.5"):
        return "ge_0.50pp"
    if delta >= Decimal("0.2"):
        return "ge_0.20pp"
    if delta >= Decimal("0.1"):
        return "ge_0.10pp"
    if delta > 0:
        return "lt_0.10pp"
    return "zero"


def _current_rows_by_source(
    db_path: Path | None,
    report: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    if db_path is None:
        return {}
    source_runs = report.get("source_runs")
    if not isinstance(source_runs, dict):
        return {}
    run_ids = [
        str(item.get("id"))
        for item in source_runs.values()
        if isinstance(item, dict) and item.get("id")
    ]
    if not run_ids:
        return {}

    placeholders = ",".join("?" for _ in run_ids)
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute(
            "SELECT lr.source_id, i.canonical_name AS institution, p.name AS product, "
            "       p.product_type, pv.term_months, pv.join_channel, pv.interest_method, "
            "       pv.payment_method, o.base_rate, o.max_rate, o.source_effective_at "
            "FROM rate_observations o "
            "JOIN collection_runs lr ON lr.id = o.last_run_id "
            "JOIN product_variants pv ON pv.id = o.variant_id "
            "JOIN products p ON p.id = pv.product_id "
            "JOIN institutions i ON i.id = p.institution_id "
            f"WHERE o.last_run_id IN ({placeholders}) "
            "  AND o.validation_status = 'valid' "
            "  AND o.valid_to IS NULL "
            "  AND i.sector = 'savings_bank'",
            run_ids,
        )
        columns = [item[0] for item in cursor.description]
        rows = [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
    finally:
        conn.close()

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("source_id") or "")].append(row)
    return dict(grouped)


def _same_identity_value(left: object, right: object, *, kind: str) -> bool:
    if kind == "institution":
        return normalize_institution(left) == normalize_institution(right)
    if kind == "product":
        return normalize_product_name(str(left or "")) == normalize_product_name(
            str(right or "")
        )
    return left == right


def _counterpart_absence_analysis(
    ambiguity: dict[str, Any],
    report: dict[str, Any],
    rows_by_source: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    scope = report.get("scope") if isinstance(report.get("scope"), dict) else {}
    counterpart_side = str(ambiguity.get("counterpart_side") or "")
    source_id = (
        scope.get("primary_source")
        if counterpart_side == "primary"
        else scope.get("secondary_source")
    )
    source_id = str(source_id or "")
    rows = rows_by_source.get(source_id, [])

    same_institution_type = [
        row
        for row in rows
        if _same_identity_value(
            row.get("institution"), ambiguity.get("institution"), kind="institution"
        )
        and row.get("product_type") == ambiguity.get("product_type")
    ]
    same_product = [
        row
        for row in same_institution_type
        if _same_identity_value(row.get("product"), ambiguity.get("product"), kind="product")
    ]
    same_product_term = [
        row
        for row in same_product
        if row.get("term_months") == ambiguity.get("term_months")
    ]
    exact_6d = [
        row
        for row in same_product_term
        if str(row.get("join_channel") or "").lower()
        == str(ambiguity.get("join_channel") or "").lower()
        and str(row.get("interest_method") or "").lower()
        == str(ambiguity.get("interest_method") or "").lower()
    ]

    if exact_6d:
        category = "counterpart_6d_rows_exist_but_were_not_selected"
        candidates = exact_6d
    elif same_product_term:
        category = "same_product_term_variant_mismatch"
        candidates = same_product_term
    elif same_product:
        category = "same_product_other_terms_only"
        candidates = same_product
    elif same_institution_type:
        category = "same_institution_type_other_product_only"
        candidates = same_institution_type
    elif rows_by_source:
        category = "counterpart_product_absent_from_latest_source_rows"
        candidates = []
    else:
        category = "counterpart_runtime_rows_unavailable"
        candidates = []

    return {
        "category": category,
        "counterpart_source_id": source_id or None,
        "same_institution_type_count": len(same_institution_type),
        "same_product_count": len(same_product),
        "same_product_term_count": len(same_product_term),
        "exact_6d_row_count": len(exact_6d),
        "candidate_variants": [
            {
                "product": row.get("product"),
                "term_months": row.get("term_months"),
                "join_channel": row.get("join_channel"),
                "interest_method": row.get("interest_method"),
                "payment_method": row.get("payment_method"),
                "base_rate": _decimal_json(_decimal(row.get("base_rate"))),
                "max_rate": _decimal_json(_decimal(row.get("max_rate"))),
                "source_effective_at": row.get("source_effective_at"),
            }
            for row in candidates[:20]
        ],
    }


def _blocked_delta(ambiguity: dict[str, Any]) -> dict[str, Any]:
    counterpart = ambiguity.get("counterpart")
    if not isinstance(counterpart, dict):
        return {
            "counterpart_present": False,
            "counterpart_max_rate": None,
            "candidate_deltas": [],
            "max_absolute_delta": None,
            "min_absolute_delta": None,
            "blocked_risk_band": "unknown",
        }

    counterpart_rate = _decimal(counterpart.get("max_rate"))
    candidate_deltas: list[dict[str, Any]] = []
    absolute_values: list[Decimal] = []
    for candidate in ambiguity.get("candidate_variants", []):
        if not isinstance(candidate, dict):
            continue
        candidate_rate = _decimal(candidate.get("max_rate"))
        delta = (
            abs(candidate_rate - counterpart_rate)
            if candidate_rate is not None and counterpart_rate is not None
            else None
        )
        if delta is not None:
            absolute_values.append(delta)
        candidate_deltas.append(
            {
                "payment_method": candidate.get("payment_method"),
                "candidate_max_rate": _decimal_json(candidate_rate),
                "absolute_delta_to_counterpart": _decimal_json(delta),
            }
        )

    max_delta = max(absolute_values) if absolute_values else None
    min_delta = min(absolute_values) if absolute_values else None
    return {
        "counterpart_present": True,
        "counterpart_max_rate": _decimal_json(counterpart_rate),
        "candidate_deltas": candidate_deltas,
        "max_absolute_delta": _decimal_json(max_delta),
        "min_absolute_delta": _decimal_json(min_delta),
        "blocked_risk_band": _risk_band(max_delta),
    }


def annotate_payment_method_ambiguity_census(
    report: dict[str, Any],
    *,
    db_path: Path | None = None,
) -> dict[str, Any]:
    """현재 ambiguity를 계량하고 queue masking을 명시한다."""
    ambiguities = [
        item
        for item in report.get("dimension_ambiguities", [])
        if isinstance(item, dict) and item.get("dimension") == "payment_method"
    ]
    rows_by_source = _current_rows_by_source(db_path, report)

    candidate_counts: Counter[int] = Counter()
    product_types: Counter[str] = Counter()
    method_combinations: Counter[str] = Counter()
    institutions: Counter[str] = Counter()
    counterpart_coverage: Counter[str] = Counter()
    risk_bands: Counter[str] = Counter()
    no_counterpart_categories: Counter[str] = Counter()
    items: list[dict[str, Any]] = []

    for ambiguity in ambiguities:
        candidates = [
            item
            for item in ambiguity.get("candidate_variants", [])
            if isinstance(item, dict)
        ]
        methods = sorted(
            {
                str(item.get("payment_method") or "unknown").strip().lower()
                for item in candidates
            }
        )
        candidate_counts[len(candidates)] += 1
        product_types[str(ambiguity.get("product_type") or "unknown")] += 1
        method_combinations["+".join(methods) or "unknown"] += 1
        institutions[str(ambiguity.get("institution") or "unknown")] += 1

        delta = _blocked_delta(ambiguity)
        counterpart_key = "present" if delta["counterpart_present"] else "missing"
        counterpart_coverage[counterpart_key] += 1
        risk_bands[str(delta["blocked_risk_band"])] += 1

        absence = None
        if not delta["counterpart_present"]:
            absence = _counterpart_absence_analysis(
                ambiguity,
                report,
                rows_by_source,
            )
            no_counterpart_categories[str(absence["category"])] += 1

        rate_pairs = sorted(
            {
                (
                    _decimal_json(_decimal(candidate.get("base_rate"))),
                    _decimal_json(_decimal(candidate.get("max_rate"))),
                )
                for candidate in candidates
            }
        )
        items.append(
            {
                "institution": ambiguity.get("institution"),
                "product": ambiguity.get("product"),
                "product_type": ambiguity.get("product_type"),
                "term_months": ambiguity.get("term_months"),
                "join_channel": ambiguity.get("join_channel"),
                "interest_method": ambiguity.get("interest_method"),
                "blocked_side": ambiguity.get("side"),
                "counterpart_side": ambiguity.get("counterpart_side"),
                "candidate_count": len(candidates),
                "candidate_payment_methods": methods,
                "candidate_rate_pairs": [
                    {"base_rate": base_rate, "max_rate": max_rate}
                    for base_rate, max_rate in rate_pairs
                ],
                "blocked_delta": delta,
                "counterpart_absence_analysis": absence,
            }
        )

    items.sort(
        key=lambda item: (
            str(item.get("institution") or ""),
            str(item.get("product") or ""),
            int(item.get("term_months") or 0),
            str(item.get("join_channel") or ""),
            str(item.get("interest_method") or ""),
        )
    )

    triage = report.get("triage") if isinstance(report.get("triage"), dict) else {}
    triage_summary = (
        triage.get("summary") if isinstance(triage.get("summary"), dict) else {}
    )
    comparable_mismatch_count = int(triage_summary.get("queue_size") or 0)
    blocked_count = len(ambiguities)
    blocked_with_counterpart = counterpart_coverage["present"]
    high_gap_blocked = sum(
        risk_bands[key] for key in ("ge_1.00pp", "ge_0.50pp", "ge_0.20pp")
    )

    census = {
        "policy_version": CENSUS_POLICY_VERSION,
        "scope": "payment_method_dimension_ambiguity_only",
        "authority_semantics": "risk_visibility_only; does_not_select_canonical_source",
        "identity_semantics": "does_not_promote_payment_method_to_strict_7d_identity",
        "blocked_delta_semantics": (
            "max candidate max-rate absolute gap versus the available 6D counterpart; "
            "used for investigation visibility only"
        ),
        "summary": {
            "ambiguity_blocked_count": blocked_count,
            "product_types": dict(sorted(product_types.items())),
            "candidate_count_distribution": {
                str(key): value for key, value in sorted(candidate_counts.items())
            },
            "payment_method_combinations": dict(sorted(method_combinations.items())),
            "institutions": len(institutions),
            "institution_counts": dict(sorted(institutions.items())),
            "counterpart_coverage": dict(sorted(counterpart_coverage.items())),
            "blocked_risk_bands": dict(sorted(risk_bands.items())),
            "no_counterpart_categories": dict(sorted(no_counterpart_categories.items())),
        },
        "queue_masking_indicator": {
            "comparable_mismatch_count": comparable_mismatch_count,
            "ambiguity_blocked_count": blocked_count,
            "ambiguity_blocked_with_counterpart": blocked_with_counterpart,
            "blocked_ge_0_20pp_count": high_gap_blocked,
            "p0_count": int(triage_summary.get("P0") or 0),
            "warning": (
                "P0 count must not be interpreted alone; payment-method ambiguities are "
                "excluded from comparable mismatch triage by fail-closed policy"
            ),
        },
        "items": items,
    }
    report["ambiguity_census"] = census
    report.setdefault("summary", {})["ambiguity_blocked_count"] = blocked_count
    report["scope"]["ambiguity_census_mutates_canonical"] = False
    report["scope"]["ambiguity_census_selects_authority"] = False
    report["scope"]["ambiguity_census_promotes_7d_identity"] = False
    return report
