#!/usr/bin/env python3
"""payment_method strict 7D 도입 시 source 비교 표본 변화를 read-only로 계산한다.

이 스크립트는 7D를 구현하지 않는다. 현재 production snapshot과 현행 6D audit
report를 입력으로 받아, strict exact payment_method를 추가했을 때 비교 가능 표본,
source-only key, same-7D 내부 모호성이 어떻게 변하는지만 계산한다.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from rate_monitor.domain.normalization import normalize_product_name
from rate_monitor.services.institution_matching import normalize_institution

WILDCARD_PAYMENT = {"", "any", "unknown", "none", "null"}


def _facet(value: object) -> str:
    text = str(value or "").strip().lower()
    return text or "unknown"


def _decimal(value: object) -> Decimal | None:
    if value in {None, ""}:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _rate_pair(row: dict[str, Any]) -> tuple[str | None, str | None]:
    base = _decimal(row.get("base_rate"))
    maximum = _decimal(row.get("max_rate"))
    return (
        format(base, "f") if base is not None else None,
        format(maximum, "f") if maximum is not None else None,
    )


def _key6(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        normalize_institution(row.get("institution")),
        normalize_product_name(str(row.get("product") or "")),
        str(row.get("product_type") or ""),
        row.get("term_months"),
        _facet(row.get("join_channel")),
        _facet(row.get("interest_method")),
    )


def _key7(row: dict[str, Any]) -> tuple[Any, ...]:
    return (*_key6(row), _facet(row.get("payment_method")))


def _current_rows(db_path: Path, report: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
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


def _payment_coverage(rows: list[dict[str, Any]]) -> dict[str, Any]:
    product_types: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        product_type = str(row.get("product_type") or "unknown")
        payment = _facet(row.get("payment_method"))
        bucket = "unknown" if payment in WILDCARD_PAYMENT else "known"
        product_types[product_type][bucket] += 1

    output: dict[str, Any] = {}
    for product_type, counts in sorted(product_types.items()):
        total = counts["known"] + counts["unknown"]
        output[product_type] = {
            "rows": total,
            "known_payment_method": counts["known"],
            "unknown_payment_method": counts["unknown"],
            "known_ratio": counts["known"] / total if total else None,
        }
    return output


def _group7(rows: list[dict[str, Any]]) -> dict[tuple[Any, ...], list[dict[str, Any]]]:
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[_key7(row)].append(row)
    return dict(grouped)


def _group_state(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    rate_pairs = sorted({_rate_pair(row) for row in candidates})
    payment_methods = sorted({_facet(row.get("payment_method")) for row in candidates})
    return {
        "candidate_count": len(candidates),
        "rate_pairs": [
            {"base_rate": base_rate, "max_rate": max_rate}
            for base_rate, max_rate in rate_pairs
        ],
        "payment_methods": payment_methods,
        "ambiguous": len(rate_pairs) > 1,
        "representative_rate_pair": rate_pairs[0] if len(rate_pairs) == 1 else None,
    }


def _current_6d_comparable(report: dict[str, Any]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for match in report.get("matches", []):
        if not isinstance(match, dict):
            continue
        identity = match.get("match") if isinstance(match.get("match"), dict) else {}
        product_type = str(identity.get("product_type") or "unknown")
        counts[product_type] += 1
    return dict(sorted(counts.items()))


def _strict7d_simulation(
    primary_rows: list[dict[str, Any]],
    secondary_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    primary = _group7(primary_rows)
    secondary = _group7(secondary_rows)
    all_keys = sorted(set(primary) | set(secondary), key=lambda item: tuple(map(str, item)))

    comparable: Counter[str] = Counter()
    agree: Counter[str] = Counter()
    mismatch: Counter[str] = Counter()
    source_only: Counter[str] = Counter()
    ambiguous_primary: Counter[str] = Counter()
    ambiguous_secondary: Counter[str] = Counter()
    ambiguous_examples: list[dict[str, Any]] = []

    for key in all_keys:
        product_type = str(key[2] or "unknown")
        left = primary.get(key)
        right = secondary.get(key)
        if left is None or right is None:
            source_only[product_type] += 1
            continue

        left_state = _group_state(left)
        right_state = _group_state(right)
        if left_state["ambiguous"]:
            ambiguous_primary[product_type] += 1
        if right_state["ambiguous"]:
            ambiguous_secondary[product_type] += 1
        if left_state["ambiguous"] or right_state["ambiguous"]:
            if len(ambiguous_examples) < 30:
                ambiguous_examples.append(
                    {
                        "key7": list(key),
                        "primary": left_state,
                        "secondary": right_state,
                    }
                )
            continue

        comparable[product_type] += 1
        left_pair = left_state["representative_rate_pair"]
        right_pair = right_state["representative_rate_pair"]
        left_max = left_pair[1] if left_pair else None
        right_max = right_pair[1] if right_pair else None
        if left_max == right_max:
            agree[product_type] += 1
        else:
            mismatch[product_type] += 1

    return {
        "comparable_by_product_type": dict(sorted(comparable.items())),
        "agree_by_product_type": dict(sorted(agree.items())),
        "mismatch_by_product_type": dict(sorted(mismatch.items())),
        "source_only_key_count_by_product_type": dict(sorted(source_only.items())),
        "ambiguous_primary_by_product_type": dict(sorted(ambiguous_primary.items())),
        "ambiguous_secondary_by_product_type": dict(sorted(ambiguous_secondary.items())),
        "ambiguous_same_7d_examples": ambiguous_examples,
        "total_comparable": sum(comparable.values()),
        "total_source_only_keys": sum(source_only.values()),
        "total_ambiguous_primary": sum(ambiguous_primary.values()),
        "total_ambiguous_secondary": sum(ambiguous_secondary.values()),
    }


def _ambiguity_transition(report: dict[str, Any]) -> dict[str, Any]:
    items = [
        item
        for item in report.get("dimension_ambiguities", [])
        if isinstance(item, dict) and item.get("dimension") == "payment_method"
    ]
    transition = Counter()
    examples: list[dict[str, Any]] = []
    for item in items:
        counterpart = item.get("counterpart")
        counterpart_payment = (
            _facet(counterpart.get("payment_method"))
            if isinstance(counterpart, dict)
            else None
        )
        candidate_methods = sorted(
            {
                _facet(candidate.get("payment_method"))
                for candidate in item.get("candidate_variants", [])
                if isinstance(candidate, dict)
            }
        )
        if counterpart_payment is None:
            category = "already_no_counterpart"
        elif counterpart_payment in candidate_methods:
            category = "strict7d_has_exact_payment_candidate"
        else:
            category = "strict7d_turns_into_payment_source_only"
        transition[category] += 1
        if len(examples) < 20:
            examples.append(
                {
                    "institution": item.get("institution"),
                    "product": item.get("product"),
                    "term_months": item.get("term_months"),
                    "join_channel": item.get("join_channel"),
                    "interest_method": item.get("interest_method"),
                    "counterpart_payment_method": counterpart_payment,
                    "candidate_payment_methods": candidate_methods,
                    "transition": category,
                }
            )
    return {
        "counts": dict(sorted(transition.items())),
        "examples": examples,
    }


def build_impact(db_path: Path, report_path: Path) -> dict[str, Any]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    scope = report.get("scope") if isinstance(report.get("scope"), dict) else {}
    primary_source = str(scope.get("primary_source") or "fsb")
    secondary_source = str(scope.get("secondary_source") or "finlife_savings_bank")
    rows = _current_rows(db_path, report)
    primary_rows = rows.get(primary_source, [])
    secondary_rows = rows.get(secondary_source, [])

    current_comparable = _current_6d_comparable(report)
    strict7d = _strict7d_simulation(primary_rows, secondary_rows)
    current_total = sum(current_comparable.values())
    strict_total = int(strict7d["total_comparable"])

    product_type_impact: dict[str, Any] = {}
    all_product_types = set(current_comparable) | set(
        strict7d["comparable_by_product_type"]
    )
    for product_type in sorted(all_product_types):
        before = int(current_comparable.get(product_type, 0))
        after = int(strict7d["comparable_by_product_type"].get(product_type, 0))
        product_type_impact[product_type] = {
            "current_6d_comparable": before,
            "strict_7d_comparable": after,
            "delta": after - before,
            "retention_ratio": after / before if before else None,
        }

    return {
        "scope": {
            "mode": "read_only_impact_simulation",
            "production_state_mutated": False,
            "canonical_mutated": False,
            "source_precedence_changed": False,
            "identity_changed": False,
            "strict_7d_implemented": False,
            "primary_source": primary_source,
            "secondary_source": secondary_source,
        },
        "payment_method_coverage": {
            primary_source: _payment_coverage(primary_rows),
            secondary_source: _payment_coverage(secondary_rows),
        },
        "current_6d": {
            "comparable_by_product_type": current_comparable,
            "total_comparable": current_total,
            "payment_method_ambiguities": sum(
                1
                for item in report.get("dimension_ambiguities", [])
                if isinstance(item, dict) and item.get("dimension") == "payment_method"
            ),
        },
        "strict_7d_simulation": strict7d,
        "product_type_impact": product_type_impact,
        "ambiguity_transition": _ambiguity_transition(report),
        "summary": {
            "current_6d_comparable": current_total,
            "strict_7d_comparable": strict_total,
            "comparable_delta": strict_total - current_total,
            "overall_retention_ratio": strict_total / current_total if current_total else None,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    impact = build_impact(args.db, args.report)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(impact, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(impact["summary"], ensure_ascii=False, sort_keys=True))
    print("coverage:", json.dumps(impact["payment_method_coverage"], ensure_ascii=False))
    print("product impact:", json.dumps(impact["product_type_impact"], ensure_ascii=False))
    print("ambiguity transition:", json.dumps(impact["ambiguity_transition"]["counts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
