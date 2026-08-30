"""Temporally aligned Rate × Funding Strategy read model.

The matrix is fail-closed: a current advertised rate is never carried backward
onto an older funding reporting month. Only rate observations whose validity
interval contains the funding month-end may be paired with that funding row.
"""

from __future__ import annotations

import calendar
import sqlite3
from contextlib import closing
from decimal import Decimal
from pathlib import Path
from statistics import median
from typing import Any

from rate_monitor.services.institution_funding_position_service import (
    SECTOR_LABELS,
    build_institution_funding_positions,
)
from rate_monitor.services.institution_funding_read_model_db import (
    FUNDING_METRIC_CODE,
    VERIFIED_IDENTITY_STATUSES,
    build_institution_funding_read_model_from_db,
)

RATE_PRODUCT_TYPE = "term_deposit"
RATE_TERM_MONTHS = 12
RATE_FIELD = "base_rate"
RATE_REPRESENTATIVE = "institution_max_base_rate"
MIN_PAIRED_ROWS_FOR_QUADRANTS = 2


def _open_readonly(db_path: Path) -> sqlite3.Connection:
    uri = db_path.resolve().as_uri() + "?mode=ro&immutable=1"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _month_end(month: str) -> str:
    year, mon = (int(part) for part in month.split("-"))
    return f"{year:04d}-{mon:02d}-{calendar.monthrange(year, mon)[1]:02d} 23:59:59"


def _historical_rates(
    db_path: Path,
    *,
    sector: str,
    analysis_month: str,
) -> dict[str, Decimal]:
    statuses = sorted(VERIFIED_IDENTITY_STATUSES)
    placeholders = ",".join("?" for _ in statuses)
    cutoff = _month_end(analysis_month)
    with closing(_open_readonly(db_path)) as conn:
        rows = conn.execute(
            f"""
            WITH funding_ids AS (
                SELECT DISTINCT institution_id
                FROM institution_funding_observations
                WHERE sector = ?
                  AND source_effective_month = ?
                  AND metric_code = ?
                  AND valid_to IS NULL
                  AND institution_id IS NOT NULL
                  AND identity_status IN ({placeholders})
            )
            SELECT p.institution_id,
                   MAX(CAST(ro.base_rate AS REAL)) AS representative_rate
            FROM funding_ids f
            JOIN products p ON p.institution_id = f.institution_id
            JOIN product_variants pv ON pv.product_id = p.id
            JOIN rate_observations ro ON ro.variant_id = pv.id
            WHERE p.product_type = ?
              AND pv.term_months = ?
              AND ro.validation_status != 'error'
              AND ro.base_rate IS NOT NULL
              AND datetime(ro.valid_from) <= datetime(?)
              AND (ro.valid_to IS NULL OR datetime(ro.valid_to) > datetime(?))
              AND (
                  ro.source_effective_at IS NULL
                  OR date(ro.source_effective_at) <= date(?)
              )
            GROUP BY p.institution_id
            """,
            (
                sector,
                analysis_month,
                FUNDING_METRIC_CODE,
                *statuses,
                RATE_PRODUCT_TYPE,
                RATE_TERM_MONTHS,
                cutoff,
                cutoff,
                cutoff,
            ),
        ).fetchall()
    return {
        str(row["institution_id"]): Decimal(str(row["representative_rate"]))
        for row in rows
        if row["representative_rate"] is not None
    }


def _current_rate_institution_count(
    db_path: Path,
    *,
    sector: str,
    analysis_month: str,
) -> int:
    statuses = sorted(VERIFIED_IDENTITY_STATUSES)
    placeholders = ",".join("?" for _ in statuses)
    with closing(_open_readonly(db_path)) as conn:
        row = conn.execute(
            f"""
            WITH funding_ids AS (
                SELECT DISTINCT institution_id
                FROM institution_funding_observations
                WHERE sector = ?
                  AND source_effective_month = ?
                  AND metric_code = ?
                  AND valid_to IS NULL
                  AND institution_id IS NOT NULL
                  AND identity_status IN ({placeholders})
            )
            SELECT COUNT(DISTINCT p.institution_id) AS institutions
            FROM funding_ids f
            JOIN products p ON p.institution_id = f.institution_id
            JOIN product_variants pv ON pv.product_id = p.id
            JOIN rate_observations ro ON ro.variant_id = pv.id
            WHERE p.product_type = ?
              AND pv.term_months = ?
              AND ro.validation_status != 'error'
              AND ro.base_rate IS NOT NULL
              AND ro.valid_to IS NULL
            """,
            (
                sector,
                analysis_month,
                FUNDING_METRIC_CODE,
                *statuses,
                RATE_PRODUCT_TYPE,
                RATE_TERM_MONTHS,
            ),
        ).fetchone()
    return int(row["institutions"] or 0) if row else 0


def _institution_names(db_path: Path, ids: set[str]) -> dict[str, str]:
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    with closing(_open_readonly(db_path)) as conn:
        rows = conn.execute(
            f"SELECT id, canonical_name FROM institutions WHERE id IN ({placeholders})",
            tuple(sorted(ids)),
        ).fetchall()
    return {str(row["id"]): str(row["canonical_name"] or "") for row in rows}


def _sector_matrix(
    db_path: Path,
    *,
    sector: str,
    analysis_month: str,
) -> dict[str, Any]:
    funding_rows = build_institution_funding_read_model_from_db(
        db_path,
        sector=sector,
        analysis_month=analysis_month,
    )
    comparable = [row for row in funding_rows if row.change_6m_pct is not None]
    rates = _historical_rates(
        db_path,
        sector=sector,
        analysis_month=analysis_month,
    )
    names = _institution_names(db_path, {row.institution_id for row in comparable})
    points = [
        {
            "institution_id": row.institution_id,
            "institution": names.get(row.institution_id, ""),
            "rate_pct": str(rates[row.institution_id]),
            "growth_6m_pct": str(row.change_6m_pct),
            "balance_million_krw": str(row.balance),
        }
        for row in comparable
        if row.institution_id in rates
    ]
    rate_median = (
        median(Decimal(point["rate_pct"]) for point in points)
        if len(points) >= MIN_PAIRED_ROWS_FOR_QUADRANTS
        else None
    )
    growth_median = (
        median(Decimal(point["growth_6m_pct"]) for point in points)
        if len(points) >= MIN_PAIRED_ROWS_FOR_QUADRANTS
        else None
    )
    paired = len(points)
    comparable_count = len(comparable)
    status = "ready" if paired >= MIN_PAIRED_ROWS_FOR_QUADRANTS else "historical_rate_unavailable"
    return {
        "sector": sector,
        "label": SECTOR_LABELS.get(sector, sector),
        "analysis_month": analysis_month,
        "rate_cutoff": _month_end(analysis_month)[:10],
        "status": status,
        "available": status == "ready",
        "funding_growth_6m_institutions": comparable_count,
        "historical_rate_institutions": len(rates),
        "paired_institutions": paired,
        "pair_coverage_ratio": (
            str(Decimal(paired) / Decimal(comparable_count)) if comparable_count else None
        ),
        "current_rate_institutions_not_carried_back": _current_rate_institution_count(
            db_path,
            sector=sector,
            analysis_month=analysis_month,
        ),
        "median_rate_pct": str(rate_median) if rate_median is not None else None,
        "median_growth_6m_pct": str(growth_median) if growth_median is not None else None,
        "points": points,
    }


def build_rate_funding_matrix(
    db_path: Path,
    *,
    funding_positions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a future-ready matrix while refusing temporal misalignment."""
    positions = funding_positions or build_institution_funding_positions(db_path)
    sectors: dict[str, Any] = {}
    for sector in positions.get("display_order", []):
        data = positions["sectors"].get(sector)
        if not data:
            continue
        sectors[sector] = _sector_matrix(
            db_path,
            sector=sector,
            analysis_month=str(data["analysis_month"]),
        )
    return {
        "available": any(item["available"] for item in sectors.values()),
        "display_order": [sector for sector in positions.get("display_order", []) if sector in sectors],
        "sectors": sectors,
        "contract": {
            "x_axis": "12M representative advertised base rate",
            "rate_product_type": RATE_PRODUCT_TYPE,
            "rate_term_months": RATE_TERM_MONTHS,
            "rate_representative": RATE_REPRESENTATIVE,
            "y_axis": "exact 6M funding growth",
            "bubble_size": "funding balance",
            "identity": "same canonical institution_id only",
            "temporal_alignment": "rate valid at funding analysis month-end",
            "current_rate_carryback": False,
            "missing_rate_as_zero": False,
            "nearest_month_interpolation": False,
            "quadrant_boundary": "paired same-sector medians",
            "causal_interpretation": False,
            "coverage_quality_threshold": None,
        },
    }
