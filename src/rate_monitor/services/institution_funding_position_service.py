"""Strategy UI overview for institution-level funding relative metrics."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rate_monitor.services.institution_funding_read_model_db import (
    FUNDING_METRIC_CODE,
    VERIFIED_IDENTITY_STATUSES,
)
from rate_monitor.services.institution_funding_strategy_payload import (
    build_institution_funding_strategy_payload,
)

SECTORS = ("savings_bank", "nh_local", "cu")
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
CADENCE_MONTHS = {
    "savings_bank": (3, 6, 9, 12),
    "cu": (6, 12),
    "nh_local": (6, 12),
}
CADENCE_LABELS = {
    "savings_bank": "분기 공시",
    "cu": "반기·정기공시",
    "nh_local": "반기 공시",
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
    statuses = sorted(VERIFIED_IDENTITY_STATUSES)
    placeholders = ",".join("?" for _ in statuses)
    row = conn.execute(
        f"""
        SELECT MAX(source_effective_month)
        FROM institution_funding_observations
        WHERE valid_to IS NULL
          AND sector = ?
          AND institution_id IS NOT NULL
          AND identity_status IN ({placeholders})
          AND metric_code = ?
        """,
        (sector, *statuses, FUNDING_METRIC_CODE),
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


def _month_age(month: str, now: datetime | None = None) -> int:
    current = now or datetime.now(UTC)
    year, mon = (int(part) for part in month.split("-"))
    return max(0, (current.year - year) * 12 + current.month - mon)


def _next_reporting_month(month: str, sector: str) -> str:
    year, mon = (int(part) for part in month.split("-"))
    for candidate in CADENCE_MONTHS[sector]:
        if candidate > mon:
            return f"{year:04d}-{candidate:02d}"
    return f"{year + 1:04d}-{CADENCE_MONTHS[sector][0]:02d}"


def _freshness(sector: str, month: str) -> dict[str, Any]:
    return {
        "months_old": _month_age(month),
        "cadence_label": CADENCE_LABELS[sector],
        "next_reporting_month": _next_reporting_month(month, sector),
    }


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
    """Build latest exact-month position payloads for supported production sectors."""
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
        if not payload["rows"]:
            continue
        conn = sqlite3.connect(db_path)
        try:
            ids = {str(row["institution_id"]) for row in payload["rows"]}
            names = _institution_names(conn, ids)
        finally:
            conn.close()
        positions[sector] = {
            **payload,
            "label": SECTOR_LABELS[sector],
            "freshness": _freshness(sector, month),
            "rows": _compact_rows(payload["rows"], names),
        }

    return {
        "available": bool(positions),
        "sectors": positions,
        "display_order": [sector for sector in SECTORS if sector in positions],
        "sector_labels": SECTOR_LABELS,
        "contract": {
            "metric_code": FUNDING_METRIC_CODE,
            "same_month_peer_population": True,
            "missing_history_is_zero": False,
            "nearest_month_interpolation": False,
            "aggregate_equals_ecos": False,
            "coverage_denominator": "active official rate-directory identity population",
            "coverage_quality_threshold": None,
        },
    }
