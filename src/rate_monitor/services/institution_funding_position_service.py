"""Strategy UI overview for institution-level funding relative metrics."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from rate_monitor.services.institution_funding_strategy_payload import (
    build_institution_funding_strategy_payload,
)

SECTORS = ("savings_bank", "cu", "nh_local")
SECTOR_LABELS = {
    "savings_bank": "저축은행",
    "cu": "신협",
    "nh_local": "농·축협",
}
SOURCE_IDS = {
    "savings_bank": "fsb",
    "cu": "cu",
    "nh_local": "nh_local",
}


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
            (table,),
        ).fetchone()
        is not None
    )


def _latest_verified_month(conn: sqlite3.Connection, sector: str) -> str | None:
    if not _table_exists(conn, "institution_funding_observations"):
        return None
    row = conn.execute(
        """
        SELECT MAX(source_effective_month)
        FROM institution_funding_observations
        WHERE valid_to IS NULL
          AND sector = ?
          AND institution_id IS NOT NULL
          AND identity_status LIKE 'mapped_exact_%'
          AND metric_code = 'deposit_liabilities_total'
        """,
        (sector,),
    ).fetchone()
    return str(row[0]) if row and row[0] else None


def _eligible_institutions(conn: sqlite3.Connection, sector: str) -> int | None:
    """Use active official rate-directory identities as the coverage denominator."""
    if not _table_exists(conn, "source_entity_links"):
        return None
    row = conn.execute(
        """
        SELECT COUNT(DISTINCT entity_id)
        FROM source_entity_links
        WHERE source_id = ?
          AND entity_type = 'institution'
          AND valid_to IS NULL
        """,
        (SOURCE_IDS[sector],),
    ).fetchone()
    value = int(row[0] or 0) if row else 0
    return value or None


def _institution_names(conn: sqlite3.Connection, ids: set[str]) -> dict[str, str]:
    if not ids or not _table_exists(conn, "institutions"):
        return {}
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"SELECT id, canonical_name FROM institutions WHERE id IN ({placeholders})",
        tuple(sorted(ids)),
    ).fetchall()
    return {str(row[0]): str(row[1] or "") for row in rows}


def _compact_rows(
    rows: list[dict[str, Any]], names: dict[str, str]
) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        result.append(
            {
                "institution_id": row["institution_id"],
                "institution": names.get(str(row["institution_id"]), ""),
                "balance_million_krw": row["balance"],
                "balance_percentile": row["sector_balance_percentile"],
                "growth_6m_pct": row["change_6m_pct"],
                "growth_6m_percentile": row["sector_growth_6m_percentile"],
                "growth_12m_pct": row["change_12m_pct"],
                "growth_12m_percentile": row["sector_growth_12m_percentile"],
                "peer_median_growth_6m": row["sector_median_growth_6m"],
                "relative_growth_6m_vs_peer_median": row[
                    "relative_growth_6m_vs_peer_median"
                ],
            }
        )
    return sorted(
        result,
        key=lambda item: (
            -float(item["balance_percentile"]),
            item["institution"],
            item["institution_id"],
        ),
    )


def build_institution_funding_positions(db_path: Path) -> dict[str, Any]:
    """Build latest exact-month position payloads for all supported sectors."""
    conn = sqlite3.connect(db_path)
    try:
        metadata = {
            sector: {
                "month": _latest_verified_month(conn, sector),
                "eligible": _eligible_institutions(conn, sector),
            }
            for sector in SECTORS
        }
    finally:
        conn.close()

    positions: dict[str, Any] = {}
    for sector, meta in metadata.items():
        month = meta["month"]
        if not month:
            continue
        payload = build_institution_funding_strategy_payload(
            db_path,
            sector=sector,
            analysis_month=month,
            eligible_institutions=meta["eligible"],
        )
        conn = sqlite3.connect(db_path)
        try:
            ids = {str(row["institution_id"]) for row in payload["rows"]}
            names = _institution_names(conn, ids)
        finally:
            conn.close()
        positions[sector] = {
            **payload,
            "label": SECTOR_LABELS[sector],
            "rows": _compact_rows(payload["rows"], names),
        }

    return {
        "available": bool(positions),
        "sectors": positions,
        "sector_labels": SECTOR_LABELS,
        "contract": {
            "same_month_peer_population": True,
            "missing_history_is_zero": False,
            "nearest_month_interpolation": False,
            "aggregate_equals_ecos": False,
            "coverage_denominator": "active official rate-directory identity population",
        },
    }
