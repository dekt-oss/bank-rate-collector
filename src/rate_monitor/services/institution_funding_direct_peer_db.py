"""DB adapter and evidence report for institution-funding direct peers."""

from __future__ import annotations

import sqlite3
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from typing import Any

from rate_monitor.services.institution_funding_direct_peer import (
    DirectPeerPoint,
    calibrate_direct_peer_counts,
)
from rate_monitor.services.institution_funding_position_service import (
    build_institution_funding_positions,
)
from rate_monitor.services.institution_funding_read_model_db import (
    build_institution_funding_read_model_from_db,
)

DEFAULT_CANDIDATE_COUNTS = (12, 16, 20)


def _institution_regions(
    db_path: Path, institution_ids: set[str]
) -> dict[str, tuple[str | None, str | None]]:
    if not institution_ids:
        return {}
    conn = sqlite3.connect(db_path)
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


def load_direct_peer_points(
    db_path: Path,
    *,
    sector: str,
    analysis_month: str,
) -> list[DirectPeerPoint]:
    """Load the same exact population used by the institution funding L2 model."""
    rows = build_institution_funding_read_model_from_db(
        db_path,
        sector=sector,
        analysis_month=analysis_month,
    )
    regions = _institution_regions(
        db_path,
        {row.institution_id for row in rows},
    )
    return [
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


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def build_direct_peer_calibration_report(
    db_path: Path,
    *,
    candidate_counts: tuple[int, ...] = DEFAULT_CANDIDATE_COUNTS,
) -> dict[str, Any]:
    """Calibrate candidate peer counts from the latest verified funding months.

    This report deliberately returns evidence rather than choosing a winner.
    The production distribution should decide the configured N.
    """
    if not candidate_counts or any(count < 1 for count in candidate_counts):
        raise ValueError("candidate_counts must contain positive integers")

    positions = build_institution_funding_positions(db_path)
    sectors: dict[str, Any] = {}
    for sector in positions.get("display_order", []):
        position = positions["sectors"][sector]
        analysis_month = str(position["analysis_month"])
        points = load_direct_peer_points(
            db_path,
            sector=sector,
            analysis_month=analysis_month,
        )
        calibrations = calibrate_direct_peer_counts(
            points,
            sector=sector,
            requested_counts=candidate_counts,
        )
        sectors[sector] = {
            "analysis_month": analysis_month,
            "population_count": len(points),
            "growth_6m_available": sum(
                point.growth_6m_pct is not None for point in points
            ),
            "region_sido_known": sum(bool(point.region_sido) for point in points),
            "region_sigungu_known": sum(
                bool(point.region_sigungu) for point in points
            ),
            "candidates": {
                str(count): _json_value(asdict(calibrations[count]))
                for count in candidate_counts
            },
        }

    return {
        "candidate_counts": list(candidate_counts),
        "selection_contract": {
            "sector": "same_sector_only",
            "month": "exact_analysis_month",
            "region_fallback": ["sigungu", "sido", "nationwide"],
            "size_distance": "absolute_log_balance_distance",
            "missing_growth_as_zero": False,
            "quality_score": None,
            "chosen_count": None,
        },
        "sectors": sectors,
    }
