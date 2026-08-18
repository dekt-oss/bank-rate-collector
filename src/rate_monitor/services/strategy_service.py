"""전략 대시보드용 read-only 집계.

검색·조회 화면의 데이터 계약은 건드리지 않는다. 전략 화면에서만 필요한
최근 금리 변경 이력과 기간별 시장 추이를 기존 DB에서 읽는다.

현재 시장 표와 이력 집계는 같은 source precedence를 써야 한다. 공개 비교표에서
``config/presentation.yaml``의 ``db_only_sources``가 물러나는 것처럼, 전략 이력도
동일 기관·상품유형·기간에 primary 원천이 유효하면 secondary 원천을 제외한다.

관측 행은 값이 바뀔 때만 새로 생긴다. 같은 상품의 여러 variant가 한 실행에서
같은 금리로 함께 움직이면 **같은 run + 같은 product + 같은 전후 금리**를 상품
변경 1건으로 묶는다. 원본 관측 행은 수정하거나 삭제하지 않는다.
"""

import sqlite3
from pathlib import Path
from typing import Any

from rate_monitor.domain.preference_taxonomy import labels as preference_labels
from rate_monitor.domain.timeutil import kst_iso
from rate_monitor.services.dashboard_service import dedupe_sources
from rate_monitor.services.inflow_prediction_service import public_model_config
from rate_monitor.services.market_intelligence_service import build_market_intelligence

MARKET_CHANGE_WINDOW_DAYS = 30
MARKET_CHANGE_ITEM_LIMIT = 12
MARKET_TREND_WINDOW_DAYS = 63
MARKET_TREND_POINT_LIMIT = 9
OUR_INSTITUTION_NAME = "고려저축은행"


def _rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    cursor = conn.execute(sql, params)
    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1", (table,)
    ).fetchone()
    return row is not None


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    if not _table_exists(conn, table):
        return False
    return any(row[1] == column for row in conn.execute(f"PRAGMA table_info({table})"))


def _coverage_key(row: dict[str, Any]) -> tuple[str, Any, Any]:
    return (
        str(row.get("normalized_institution") or row.get("institution") or ""),
        row.get("product_type"),
        row.get("term_months"),
    )


def _apply_source_precedence(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """공개 비교표와 같은 db_only_sources 후퇴 규칙을 snapshot 행에 적용한다."""
    retreating = set(dedupe_sources())
    if not retreating:
        return rows
    covered = {
        _coverage_key(row)
        for row in rows
        if row.get("source_id") not in retreating
    }
    if not covered:
        return rows
    return [
        row
        for row in rows
        if row.get("source_id") not in retreating or _coverage_key(row) not in covered
    ]


def _source_visible_at(conn: sqlite3.Connection, change: dict[str, Any]) -> bool:
    """변경 시점에 공개 비교 universe에서 이 source가 보였는지 판단한다."""
    retreating = tuple(dedupe_sources())
    if (
        not retreating
        or change.get("source_id") not in retreating
        or not _table_exists(conn, "collection_runs")
    ):
        return True
    institution_column = (
        "i.normalized_name"
        if _column_exists(conn, "institutions", "normalized_name")
        else "i.canonical_name"
    )
    placeholders = ",".join("?" for _ in retreating)
    row = conn.execute(
        f"""
        SELECT 1
        FROM rate_observations o
        JOIN collection_runs r ON r.id = o.run_id
        JOIN product_variants v ON v.id = o.variant_id
        JOIN products p ON p.id = v.product_id
        JOIN institutions i ON i.id = p.institution_id
        WHERE r.source_id NOT IN ({placeholders})
          AND i.sector = 'savings_bank'
          AND {institution_column} = ?
          AND p.product_type = ?
          AND v.term_months = ?
          AND o.validation_status != 'error'
          AND o.max_rate IS NOT NULL
          AND o.valid_from <= ?
          AND (o.valid_to IS NULL OR o.valid_to > ?)
        LIMIT 1
        """,
        (
            *retreating,
            change["normalized_institution"],
            change["product_type"],
            change["term_months"],
            change["changed_at"],
            change["changed_at"],
        ),
    ).fetchone()
    return row is None


def _change_cte(*, source_metadata: bool, normalized_name: bool) -> str:
    """저축은행 12개월 정기예금의 상품 단위 최고금리 변경 후보."""
    source_select = "r.source_id" if source_metadata else "NULL AS source_id"
    source_join = "JOIN collection_runs r ON r.id = o.run_id" if source_metadata else ""
    normalized_select = (
        "i.normalized_name" if normalized_name else "i.canonical_name"
    )
    return f"""
        WITH history AS (
            SELECT
                o.id,
                o.variant_id,
                o.run_id,
                {source_select},
                o.valid_from,
                o.max_rate,
                o.validation_status,
                LAG(o.max_rate) OVER (
                    PARTITION BY o.variant_id
                    ORDER BY o.valid_from, o.id
                ) AS previous_max_rate
            FROM rate_observations o
            {source_join}
            WHERE o.validation_status != 'error'
        ), changes AS (
            SELECT
                h.id,
                h.run_id,
                h.source_id,
                h.valid_from AS changed_at,
                h.previous_max_rate,
                h.max_rate,
                i.canonical_name AS institution,
                {normalized_select} AS normalized_institution,
                p.id AS product_id,
                p.name AS product,
                p.product_type AS product_type,
                v.term_months AS term_months
            FROM history h
            JOIN product_variants v ON v.id = h.variant_id
            JOIN products p ON p.id = v.product_id
            JOIN institutions i ON i.id = p.institution_id
            WHERE i.sector = 'savings_bank'
              AND p.product_type = 'term_deposit'
              AND v.term_months = 12
              AND h.valid_from >= datetime('now', ?)
              AND h.previous_max_rate IS NOT NULL
              AND h.max_rate IS NOT NULL
              AND h.previous_max_rate != h.max_rate
        ), product_changes AS (
            SELECT
                run_id,
                source_id,
                product_id,
                institution,
                normalized_institution,
                product,
                product_type,
                term_months,
                previous_max_rate,
                max_rate,
                MAX(changed_at) AS changed_at,
                COUNT(*) AS variant_count
            FROM changes
            GROUP BY
                run_id,
                source_id,
                product_id,
                institution,
                normalized_institution,
                product,
                product_type,
                term_months,
                previous_max_rate,
                max_rate
        )
    """


def _empty_rate_trend() -> dict[str, Any]:
    return {
        "window_days": MARKET_TREND_WINDOW_DAYS,
        "points": [],
        "scope": {
            "sector": "savings_bank",
            "product_type": "term_deposit",
            "term_months": 12,
            "rate_field": "max_rate",
            "aggregation": "product_representative_mean",
            "source_precedence": "presentation.db_only_sources",
            "our_institution": OUR_INSTITUTION_NAME,
            "our_company_aggregation": "institution_product_representative_max",
        },
    }


def _build_rate_trend(conn: sqlite3.Connection) -> dict[str, Any]:
    """정상 수집일 snapshot에서 현재 화면과 같은 source universe를 복원한다."""
    required = ("collection_runs", "sources", "rate_observations")
    if not all(_table_exists(conn, table) for table in required):
        return _empty_rate_trend()

    window = f"-{MARKET_TREND_WINDOW_DAYS} days"
    snapshots = _rows(
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
        (window, MARKET_TREND_POINT_LIMIT),
    )
    snapshots.reverse()

    points: list[dict[str, Any]] = []
    for snapshot in snapshots:
        at = snapshot["snapshot_at"]
        active_rows = _rows(
            conn,
            """
            SELECT
                p.id AS product_id,
                i.canonical_name AS institution,
                i.normalized_name AS normalized_institution,
                p.product_type AS product_type,
                v.term_months AS term_months,
                r.source_id AS source_id,
                CAST(o.max_rate AS REAL) AS max_rate
            FROM rate_observations o
            JOIN collection_runs r ON r.id = o.run_id
            JOIN product_variants v ON v.id = o.variant_id
            JOIN products p ON p.id = v.product_id
            JOIN institutions i ON i.id = p.institution_id
            WHERE i.sector = 'savings_bank'
              AND p.product_type = 'term_deposit'
              AND v.term_months = 12
              AND o.validation_status != 'error'
              AND o.max_rate IS NOT NULL
              AND o.valid_from <= ?
              AND (o.valid_to IS NULL OR o.valid_to > ?)
            """,
            (at, at),
        )
        visible_rows = _apply_source_precedence(active_rows)
        representatives: dict[str, dict[str, Any]] = {}
        for row in visible_rows:
            current = representatives.get(row["product_id"])
            if current is None or float(row["max_rate"]) > float(current["max_rate"]):
                representatives[row["product_id"]] = row
        if not representatives:
            continue
        values = [float(row["max_rate"]) for row in representatives.values()]
        our_values = [
            float(row["max_rate"])
            for row in representatives.values()
            if row["institution"] == OUR_INSTITUTION_NAME
        ]
        points.append(
            {
                "date": snapshot["snapshot_date"],
                "snapshot_at": kst_iso(at),
                "mean_max_rate": round(sum(values) / len(values), 4),
                "market_max_rate": round(max(values), 4),
                "our_company_max_rate": round(max(our_values), 4) if our_values else None,
                "product_count": len(values),
            }
        )

    trend = _empty_rate_trend()
    trend["points"] = points
    return trend


def build_strategy_summary(db_path: Path) -> dict[str, Any]:
    """전략 화면에만 인라인할 가벼운 시장 변화·추이 요약을 만든다."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = None
    window = f"-{MARKET_CHANGE_WINDOW_DAYS} days"
    try:
        cte = _change_cte(
            source_metadata=_table_exists(conn, "collection_runs"),
            normalized_name=_column_exists(conn, "institutions", "normalized_name"),
        )
        raw_changes = _rows(
            conn,
            cte
            + """
                SELECT
                    source_id,
                    institution,
                    normalized_institution,
                    product,
                    product_type,
                    term_months,
                    previous_max_rate,
                    max_rate,
                    changed_at,
                    variant_count
                FROM product_changes
            """,
            (window,),
        )
        visible_changes = [
            item for item in raw_changes if _source_visible_at(conn, item)
        ]
        for item in visible_changes:
            before = float(item["previous_max_rate"])
            after = float(item["max_rate"])
            item["previous_max_rate"] = before
            item["max_rate"] = after
            item["variant_count"] = int(item.get("variant_count") or 1)
            item["delta"] = round(after - before, 4)
            item["changed_at"] = kst_iso(item["changed_at"])

        items = sorted(
            visible_changes,
            key=lambda item: (
                -abs(float(item["delta"])),
                str(item["changed_at"]),
                str(item["institution"]),
                str(item["product"]),
            ),
        )[:MARKET_CHANGE_ITEM_LIMIT]
        rate_trend = _build_rate_trend(conn)
        market_intelligence = build_market_intelligence(conn)
    finally:
        conn.close()

    count = len(visible_changes)
    up_count = sum(1 for item in visible_changes if item["delta"] > 0)
    down_count = sum(1 for item in visible_changes if item["delta"] < 0)
    affected_variant_count = sum(item["variant_count"] for item in visible_changes)
    latest = max((item["changed_at"] for item in visible_changes), default=None)
    return {
        "preference_labels": preference_labels(),
        "inflow_prediction": public_model_config(),
        "rate_trend": rate_trend,
        "market_intelligence": market_intelligence,
        "market_changes": {
            "window_days": MARKET_CHANGE_WINDOW_DAYS,
            "count": count,
            "up_count": up_count,
            "down_count": down_count,
            "affected_variant_count": affected_variant_count,
            "latest_changed_at": latest,
            "items": items,
            "scope": {
                "sector": "savings_bank",
                "product_type": "term_deposit",
                "term_months": 12,
                "rate_field": "max_rate",
                "event_unit": "run_product_rate_transition",
                "source_precedence": "presentation.db_only_sources",
            },
        },
    }
