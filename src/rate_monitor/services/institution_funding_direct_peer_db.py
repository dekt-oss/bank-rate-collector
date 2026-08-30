"""DB adapter for calibrated institution-funding direct peers."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from rate_monitor.services.institution_funding_direct_peer import (
    DirectPeerPoint,
    DirectPeerSelection,
    select_direct_peers,
)
from rate_monitor.services.institution_funding_read_model_db import (
    build_institution_funding_read_model_from_db,
)

NH_LOCAL_DIRECT_PEER_COUNT = 16
DIRECT_PEER_ENABLED_SECTORS = frozenset({"nh_local"})


def _load_regions(
    db_path: Path,
    institution_ids: set[str],
) -> dict[str, tuple[str | None, str | None]]:
    if not institution_ids:
        return {}
    uri = db_path.resolve().as_uri() + "?mode=ro&immutable=1"
    conn = sqlite3.connect(uri, uri=True)
    try:
        placeholders = ",".join("?" for _ in institution_ids)
        rows = conn.execute(
            f"""
            SELECT id, region_sido, region_sigungu
            FROM institutions
            WHERE id IN ({placeholders})
            """,
            tuple(sorted(institution_ids)),
        ).fetchall()
    finally:
        conn.close()
    return {
        str(row[0]): (
            str(row[1]).strip() if row[1] else None,
            str(row[2]).strip() if row[2] else None,
        )
        for row in rows
    }


def build_direct_peer_selections(
    db_path: Path,
    *,
    sector: str,
    analysis_month: str,
    requested_count: int | None = None,
) -> dict[str, DirectPeerSelection]:
    """Return calibrated direct-peer selections for one exact sector/month.

    Production enablement is intentionally narrow. NH local-coop uses N=16 from
    production calibration. Other sectors remain disabled until their own
    population-specific calibration has passed.
    """
    if sector not in DIRECT_PEER_ENABLED_SECTORS:
        return {}
    count = requested_count or NH_LOCAL_DIRECT_PEER_COUNT
    rows = build_institution_funding_read_model_from_db(
        db_path,
        sector=sector,
        analysis_month=analysis_month,
    )
    regions = _load_regions(db_path, {row.institution_id for row in rows})
    points = [
        DirectPeerPoint(
            institution_id=row.institution_id,
            sector=row.sector,
            balance=row.balance,
            growth_6m_pct=row.change_6m_pct,
            region_sido=regions.get(row.institution_id, (None, None))[0],
            region_sigungu=regions.get(row.institution_id, (None, None))[1],
        )
        for row in rows
    ]
    return {
        point.institution_id: select_direct_peers(
            points,
            sector=sector,
            institution_id=point.institution_id,
            requested_count=count,
        )
        for point in points
    }
