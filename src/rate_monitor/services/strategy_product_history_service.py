"""상품군·가입기간별 Strategy 실제 금리 변화/추이 집계.

기존 Strategy 12개월 정기예금 요약은 건드리지 않고, 같은 rate_observations와
source precedence를 사용해 예금·정기적금·자유적금의 6/12/24/36개월 이력을
추가 계약으로 제공한다.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from rate_monitor.domain.timeutil import kst_iso
from rate_monitor.services import strategy_service_base as base

TERMS = (6, 12, 24, 36)
ATOMIC_TYPES = ("term_deposit", "installment_savings", "flexible_savings")
SCOPE_TYPES: dict[str, tuple[str, ...]] = {
    "deposit": ("term_deposit",),
    "savings_all": ("installment_savings", "flexible_savings"),
    "savings_installment": ("installment_savings",),
    "savings_flexible": ("flexible_savings",),
}


def _scope(scope_key: str, term: int) -> dict[str, Any]:
    return {
        "sector": "savings_bank",
        "product_types": list(SCOPE_TYPES[scope_key]),
        "term_months": term,
        "rate_field": "max_rate",
        "source_precedence": "presentation.db_only_sources",
    }


def _empty_changes(scope_key: str, term: int) -> dict[str, Any]:
    return {
        "window_days": base.MARKET_CHANGE_WINDOW_DAYS,
        "count": 0,
        "up_count": 0,
        "down_count": 0,
        "affected_variant_count": 0,
        "latest_changed_at": None,
        "items": [],
        "scope": {**_scope(scope_key, term), "event_unit": "run_product_rate_transition"},
    }


def _empty_trend(scope_key: str, term: int) -> dict[str, Any]:
    return {
        "window_days": base.MARKET_TREND_WINDOW_DAYS,
        "points": [],
        "scope": {
            **_scope(scope_key, term),
            "aggregation": "product_representative_mean",
            "our_institution": base.OUR_INSTITUTION_NAME,
            "our_company_aggregation": "institution_product_representative_max",
        },
    }


def _change_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    if not base._table_exists(conn, "rate_observations"):
        return []
    source_metadata = base._table_exists(conn, "collection_runs")
    normalized_name = base._column_exists(conn, "institutions", "normalized_name")
    source_select = "r.source_id" if source_metadata else "NULL AS source_id"
    source_join = "JOIN collection_runs r ON r.id = o.run_id" if source_metadata else ""
    normalized_select = "i.normalized_name" if normalized_name else "i.canonical_name"
    type_placeholders = ",".join("?" for _ in ATOMIC_TYPES)
    term_placeholders = ",".join("?" for _ in TERMS)
    sql = f"""
        WITH history AS (
            SELECT
                o.id, o.variant_id, o.run_id, {source_select}, o.valid_from, o.max_rate,
                LAG(o.max_rate) OVER (
                    PARTITION BY o.variant_id ORDER BY o.valid_from, o.id
                ) AS previous_max_rate
            FROM rate_observations o
            {source_join}
            WHERE o.validation_status != 'error'
        ), changes AS (
            SELECT
                h.run_id, h.source_id, h.valid_from AS changed_at,
                h.previous_max_rate, h.max_rate,
                i.canonical_name AS institution,
                {normalized_select} AS normalized_institution,
                p.id AS product_id, p.name AS product,
                p.product_type, v.term_months
            FROM history h
            JOIN product_variants v ON v.id = h.variant_id
            JOIN products p ON p.id = v.product_id
            JOIN institutions i ON i.id = p.institution_id
            WHERE i.sector = 'savings_bank'
              AND p.product_type IN ({type_placeholders})
              AND v.term_months IN ({term_placeholders})
              AND h.valid_from >= datetime('now', ?)
              AND h.previous_max_rate IS NOT NULL
              AND h.max_rate IS NOT NULL
              AND h.previous_max_rate != h.max_rate
        )
        SELECT
            run_id, source_id, product_id, institution, normalized_institution,
            product, product_type, term_months, previous_max_rate, max_rate,
            MAX(changed_at) AS changed_at, COUNT(*) AS variant_count
        FROM changes
        GROUP BY
            run_id, source_id, product_id, institution, normalized_institution,
            product, product_type, term_months, previous_max_rate, max_rate
    """
    rows = base._rows(
        conn,
        sql,
        (*ATOMIC_TYPES, *TERMS, f"-{base.MARKET_CHANGE_WINDOW_DAYS} days"),
    )
    visible = [item for item in rows if base._source_visible_at(conn, item)]
    for item in visible:
        before = float(item["previous_max_rate"])
        after = float(item["max_rate"])
        item["previous_max_rate"] = before
        item["max_rate"] = after
        item["term_months"] = int(item["term_months"])
        item["variant_count"] = int(item.get("variant_count") or 1)
        item["delta"] = round(after - before, 4)
        item["changed_at"] = kst_iso(item["changed_at"])
    return visible


def _changes_payload(
    all_changes: list[dict[str, Any]], scope_key: str, term: int
) -> dict[str, Any]:
    allowed = set(SCOPE_TYPES[scope_key])
    rows = [
        item
        for item in all_changes
        if item["product_type"] in allowed and item["term_months"] == term
    ]
    payload = _empty_changes(scope_key, term)
    payload.update(
        {
            "count": len(rows),
            "up_count": sum(1 for item in rows if item["delta"] > 0),
            "down_count": sum(1 for item in rows if item["delta"] < 0),
            "affected_variant_count": sum(item["variant_count"] for item in rows),
            "latest_changed_at": max(
                (item["changed_at"] for item in rows), default=None
            ),
            "items": sorted(
                rows,
                key=lambda item: (
                    -abs(float(item["delta"])),
                    str(item["changed_at"]),
                    str(item["institution"]),
                    str(item["product"]),
                ),
            )[: base.MARKET_CHANGE_ITEM_LIMIT],
        }
    )
    return payload


def _snapshot_rows(conn: sqlite3.Connection, at: str) -> list[dict[str, Any]]:
    """한 snapshot의 지원 상품유형·기간을 한 번에 읽어 기간별 재조회 비용을 피한다."""
    normalized = (
        "i.normalized_name"
        if base._column_exists(conn, "institutions", "normalized_name")
        else "i.canonical_name"
    )
    type_placeholders = ",".join("?" for _ in ATOMIC_TYPES)
    term_placeholders = ",".join("?" for _ in TERMS)
    rows = base._rows(
        conn,
        f"""
        SELECT
            p.id AS product_id, i.canonical_name AS institution,
            {normalized} AS normalized_institution,
            p.product_type AS product_type, v.term_months AS term_months,
            r.source_id AS source_id, CAST(o.max_rate AS REAL) AS max_rate
        FROM rate_observations o
        JOIN collection_runs r ON r.id = o.run_id
        JOIN product_variants v ON v.id = o.variant_id
        JOIN products p ON p.id = v.product_id
        JOIN institutions i ON i.id = p.institution_id
        WHERE i.sector = 'savings_bank'
          AND p.product_type IN ({type_placeholders})
          AND v.term_months IN ({term_placeholders})
          AND o.validation_status != 'error'
          AND o.max_rate IS NOT NULL
          AND o.valid_from <= ?
          AND (o.valid_to IS NULL OR o.valid_to > ?)
        """,
        (*ATOMIC_TYPES, *TERMS, at, at),
    )
    return base._apply_source_precedence(rows)


def _representatives(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    chosen: dict[tuple[int, str, str], dict[str, Any]] = {}
    for row in rows:
        key = (
            int(row["term_months"]),
            str(row["product_type"]),
            str(row["product_id"]),
        )
        current = chosen.get(key)
        if current is None or float(row["max_rate"]) > float(current["max_rate"]):
            chosen[key] = row
    return list(chosen.values())


def _point(
    representatives: list[dict[str, Any]], scope_key: str, snapshot: dict[str, Any]
) -> dict[str, Any] | None:
    allowed = set(SCOPE_TYPES[scope_key])
    scoped = [row for row in representatives if row["product_type"] in allowed]
    if not scoped:
        return None
    values = [float(row["max_rate"]) for row in scoped]
    our_values = [
        float(row["max_rate"])
        for row in scoped
        if row["institution"] == base.OUR_INSTITUTION_NAME
    ]
    return {
        "date": snapshot["snapshot_date"],
        "snapshot_at": kst_iso(snapshot["snapshot_at"]),
        "mean_max_rate": round(sum(values) / len(values), 4),
        "market_max_rate": round(max(values), 4),
        "our_company_max_rate": round(max(our_values), 4) if our_values else None,
        "product_count": len(values),
    }


def _trend_payloads(conn: sqlite3.Connection) -> dict[str, dict[str, dict[str, Any]]]:
    payloads = {
        scope_key: {str(term): _empty_trend(scope_key, term) for term in TERMS}
        for scope_key in SCOPE_TYPES
    }
    required = ("collection_runs", "sources", "rate_observations")
    if not all(base._table_exists(conn, table) for table in required):
        return payloads
    snapshots = base._rows(
        conn,
        """
        SELECT
            date(COALESCE(r.finished_at, r.started_at)) AS snapshot_date,
            MAX(COALESCE(r.finished_at, r.started_at)) AS snapshot_at
        FROM collection_runs r
        JOIN sources s ON s.id = r.source_id
        WHERE s.sector = 'savings_bank'
          AND r.status IN ('success', 'partial', 'no_change')
          AND COALESCE(r.finished_at, r.started_at) IS NOT NULL
          AND COALESCE(r.finished_at, r.started_at) >= datetime('now', ?)
        GROUP BY date(COALESCE(r.finished_at, r.started_at))
        ORDER BY snapshot_at DESC
        LIMIT ?
        """,
        (f"-{base.MARKET_TREND_WINDOW_DAYS} days", base.MARKET_TREND_POINT_LIMIT),
    )
    snapshots.reverse()
    for snapshot in snapshots:
        representatives = _representatives(_snapshot_rows(conn, snapshot["snapshot_at"]))
        for term in TERMS:
            term_representatives = [
                row for row in representatives if int(row["term_months"]) == term
            ]
            for scope_key in SCOPE_TYPES:
                point = _point(term_representatives, scope_key, snapshot)
                if point is not None:
                    payloads[scope_key][str(term)]["points"].append(point)
    return payloads


def build_product_history(db_path: Path) -> dict[str, Any]:
    """실제 관측 데이터로 상품군×기간 Strategy 이력 matrix를 만든다."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = None
    try:
        changes = _change_rows(conn)
        trends = _trend_payloads(conn)
    finally:
        conn.close()

    scopes: dict[str, dict[str, dict[str, Any]]] = {}
    for scope_key in SCOPE_TYPES:
        scopes[scope_key] = {}
        for term in TERMS:
            scopes[scope_key][str(term)] = {
                "rate_trend": trends[scope_key][str(term)],
                "market_changes": _changes_payload(changes, scope_key, term),
            }
    return {
        "version": "strategy-product-history-v1",
        "terms": list(TERMS),
        "scopes": scopes,
    }
