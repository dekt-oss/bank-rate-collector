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

from rate_monitor.services.dashboard_service import dedupe_sources
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
RATE_TERM_SCOPES = (6, 12, 24, 36)
RATE_FIELD = "max_rate"
RATE_REPRESENTATIVE = "institution_product_representative_max"
MIN_PAIRED_ROWS_FOR_QUADRANTS = 2


def _open_readonly(db_path: Path) -> sqlite3.Connection:
    uri = db_path.resolve().as_uri() + "?mode=ro&immutable=1"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _month_end(month: str) -> str:
    year, mon = (int(part) for part in month.split("-"))
    return f"{year:04d}-{mon:02d}-{calendar.monthrange(year, mon)[1]:02d} 23:59:59"


def _representative_rates(rows: list[sqlite3.Row | dict[str, Any]]) -> dict[str, Decimal]:
    """Apply Strategy source precedence, then aggregate product → institution."""
    retreating = set(dedupe_sources())
    covered = {
        str(row["institution_id"])
        for row in rows
        if str(row["source_id"] or "") not in retreating
    }
    product_rates: dict[tuple[str, str], Decimal] = {}
    for row in rows:
        institution_id = str(row["institution_id"])
        source_id = str(row["source_id"] or "")
        if source_id in retreating and institution_id in covered:
            continue
        rate = Decimal(str(row["rate_value"]))
        key = (institution_id, str(row["product_id"]))
        current = product_rates.get(key)
        if current is None or rate > current:
            product_rates[key] = rate

    institution_rates: dict[str, Decimal] = {}
    for (institution_id, _product_id), rate in product_rates.items():
        current = institution_rates.get(institution_id)
        if current is None or rate > current:
            institution_rates[institution_id] = rate
    return institution_rates


def _funding_institution_ids(
    conn: sqlite3.Connection,
    *,
    sector: str,
    analysis_month: str,
) -> set[str]:
    statuses = sorted(VERIFIED_IDENTITY_STATUSES)
    placeholders = ",".join("?" for _ in statuses)
    rows = conn.execute(
        f"""
        SELECT DISTINCT institution_id
        FROM institution_funding_observations
        WHERE sector = ?
          AND source_effective_month = ?
          AND metric_code = ?
          AND valid_to IS NULL
          AND institution_id IS NOT NULL
          AND identity_status IN ({placeholders})
        """,
        (
            sector,
            analysis_month,
            FUNDING_METRIC_CODE,
            *statuses,
        ),
    ).fetchall()
    return {str(row["institution_id"]) for row in rows}


def _candidate_variants_for_terms(
    conn: sqlite3.Connection,
    institution_ids: set[str],
    *,
    terms: tuple[int, ...] = RATE_TERM_SCOPES,
) -> list[tuple[str, str, str, int]]:
    if not institution_ids or not terms:
        return []
    term_placeholders = ",".join("?" for _ in terms)
    rows = conn.execute(
        f"""
        SELECT pv.id AS variant_id,
               p.id AS product_id,
               p.institution_id,
               pv.term_months
        FROM product_variants pv
        JOIN products p ON p.id = pv.product_id
        WHERE p.product_type = ?
          AND pv.term_months IN ({term_placeholders})
        """,
        (RATE_PRODUCT_TYPE, *terms),
    ).fetchall()
    return [
        (
            str(row["variant_id"]),
            str(row["product_id"]),
            str(row["institution_id"]),
            int(row["term_months"]),
        )
        for row in rows
        if str(row["institution_id"]) in institution_ids
    ]


def _candidate_variants(
    conn: sqlite3.Connection,
    institution_ids: set[str],
    *,
    term_months: int = RATE_TERM_MONTHS,
) -> list[tuple[str, str, str]]:
    """Backward-compatible single-term candidate helper."""
    return [
        (variant_id, product_id, institution_id)
        for variant_id, product_id, institution_id, _term in _candidate_variants_for_terms(
            conn,
            institution_ids,
            terms=(term_months,),
        )
    ]


def _rate_snapshots_by_term(
    db_path: Path,
    *,
    sector: str,
    analysis_month: str,
    terms: tuple[int, ...] = RATE_TERM_SCOPES,
) -> dict[int, tuple[dict[str, Decimal], dict[str, Decimal]]]:
    """Return historical/current representative rates for all requested terms in one scan."""
    normalized_terms = tuple(dict.fromkeys(int(term) for term in terms))
    empty = {term: ({}, {}) for term in normalized_terms}
    if not normalized_terms:
        return empty

    cutoff = _month_end(analysis_month)
    cutoff_date = cutoff[:10]
    with closing(_open_readonly(db_path)) as conn:
        institution_ids = _funding_institution_ids(
            conn,
            sector=sector,
            analysis_month=analysis_month,
        )
        variants = _candidate_variants_for_terms(
            conn,
            institution_ids,
            terms=normalized_terms,
        )
        if not variants:
            return empty

        conn.execute(
            """
            CREATE TEMP TABLE matrix_candidate_variants (
                variant_id TEXT PRIMARY KEY,
                product_id TEXT NOT NULL,
                institution_id TEXT NOT NULL,
                term_months INTEGER NOT NULL
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO matrix_candidate_variants(
                variant_id, product_id, institution_id, term_months
            ) VALUES (?, ?, ?, ?)
            """,
            variants,
        )
        rows = conn.execute(
            """
            SELECT cv.institution_id,
                   cv.product_id,
                   cv.term_months,
                   cr.source_id,
                   CAST(ro.max_rate AS REAL) AS rate_value,
                   ro.valid_from,
                   ro.valid_to,
                   ro.source_effective_at
            FROM rate_observations ro
            JOIN matrix_candidate_variants cv ON cv.variant_id = ro.variant_id
            JOIN collection_runs cr ON cr.id = ro.run_id
            WHERE ro.validation_status != 'error'
              AND ro.max_rate IS NOT NULL
              AND (
                  ro.valid_to IS NULL
                  OR (ro.valid_from <= ? AND ro.valid_to > ?)
              )
            """,
            (cutoff, cutoff),
        ).fetchall()

    result: dict[int, tuple[dict[str, Decimal], dict[str, Decimal]]] = {}
    for term in normalized_terms:
        term_rows = [row for row in rows if int(row["term_months"]) == term]
        current_rows = [row for row in term_rows if row["valid_to"] is None]
        historical_rows = [
            row
            for row in term_rows
            if str(row["valid_from"]) <= cutoff
            and (row["valid_to"] is None or str(row["valid_to"]) > cutoff)
            and (
                row["source_effective_at"] is None
                or str(row["source_effective_at"]) <= cutoff_date
            )
        ]
        result[term] = (
            _representative_rates(historical_rows),
            _representative_rates(current_rows),
        )
    return result


def _rate_snapshots(
    db_path: Path,
    *,
    sector: str,
    analysis_month: str,
    term_months: int = RATE_TERM_MONTHS,
) -> tuple[dict[str, Decimal], dict[str, Decimal]]:
    """Backward-compatible single-term snapshot helper."""
    return _rate_snapshots_by_term(
        db_path,
        sector=sector,
        analysis_month=analysis_month,
        terms=(term_months,),
    )[term_months]


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


def _matrix_status(
    *,
    paired: int,
    historical_rate_count: int,
    current_rate_count: int,
) -> str:
    if paired >= MIN_PAIRED_ROWS_FOR_QUADRANTS:
        return "ready"
    if historical_rate_count == 0 and current_rate_count == 0:
        return "rate_data_unavailable"
    if historical_rate_count == 0:
        return "historical_rate_unavailable"
    return "insufficient_exact_pairs"


def _sector_matrix_from_inputs(
    db_path: Path,
    *,
    sector: str,
    analysis_month: str,
    term_months: int,
    funding_rows: list[Any],
    rates: dict[str, Decimal],
    current_rates: dict[str, Decimal],
) -> dict[str, Any]:
    comparable = [row for row in funding_rows if row.change_6m_pct is not None]
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
    status = _matrix_status(
        paired=paired,
        historical_rate_count=len(rates),
        current_rate_count=len(current_rates),
    )
    return {
        "sector": sector,
        "label": SECTOR_LABELS.get(sector, sector),
        "analysis_month": analysis_month,
        "rate_cutoff": _month_end(analysis_month)[:10],
        "rate_term_months": term_months,
        "status": status,
        "available": status == "ready",
        "funding_growth_6m_institutions": comparable_count,
        "historical_rate_institutions": len(rates),
        "paired_institutions": paired,
        "pair_coverage_ratio": (
            str(Decimal(paired) / Decimal(comparable_count)) if comparable_count else None
        ),
        "current_rate_institutions": len(current_rates),
        "current_rate_institutions_not_carried_back": len(current_rates),
        "median_rate_pct": str(rate_median) if rate_median is not None else None,
        "median_growth_6m_pct": str(growth_median) if growth_median is not None else None,
        "points": points,
    }


def _sector_matrix(
    db_path: Path,
    *,
    sector: str,
    analysis_month: str,
    term_months: int = RATE_TERM_MONTHS,
) -> dict[str, Any]:
    funding_rows = build_institution_funding_read_model_from_db(
        db_path,
        sector=sector,
        analysis_month=analysis_month,
    )
    rates, current_rates = _rate_snapshots(
        db_path,
        sector=sector,
        analysis_month=analysis_month,
        term_months=term_months,
    )
    return _sector_matrix_from_inputs(
        db_path,
        sector=sector,
        analysis_month=analysis_month,
        term_months=term_months,
        funding_rows=funding_rows,
        rates=rates,
        current_rates=current_rates,
    )


def _sector_term_scopes(
    db_path: Path,
    *,
    sector: str,
    analysis_month: str,
) -> dict[str, dict[str, Any]]:
    """Build all deposit-term matrices while scanning rate history once per sector."""
    funding_rows = build_institution_funding_read_model_from_db(
        db_path,
        sector=sector,
        analysis_month=analysis_month,
    )
    snapshots = _rate_snapshots_by_term(
        db_path,
        sector=sector,
        analysis_month=analysis_month,
        terms=RATE_TERM_SCOPES,
    )
    return {
        str(term): _sector_matrix_from_inputs(
            db_path,
            sector=sector,
            analysis_month=analysis_month,
            term_months=term,
            funding_rows=funding_rows,
            rates=snapshots[term][0],
            current_rates=snapshots[term][1],
        )
        for term in RATE_TERM_SCOPES
    }


def build_rate_funding_matrix(
    db_path: Path,
    *,
    funding_positions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build future-ready deposit-term matrices while refusing temporal misalignment."""
    positions = funding_positions or build_institution_funding_positions(db_path)
    scopes: dict[str, dict[str, Any]] = {
        str(term): {"available": False, "display_order": [], "sectors": {}}
        for term in RATE_TERM_SCOPES
    }
    for sector in positions.get("display_order", []):
        data = positions["sectors"].get(sector)
        if not data:
            continue
        sector_scopes = _sector_term_scopes(
            db_path,
            sector=sector,
            analysis_month=str(data["analysis_month"]),
        )
        for term in RATE_TERM_SCOPES:
            key = str(term)
            item = sector_scopes[key]
            scopes[key]["sectors"][sector] = item
            scopes[key]["display_order"].append(sector)
            scopes[key]["available"] = scopes[key]["available"] or item["available"]

    default_scope = scopes[str(RATE_TERM_MONTHS)]
    return {
        # Backward-compatible 12M surface for existing consumers.
        "available": default_scope["available"],
        "display_order": default_scope["display_order"],
        "sectors": default_scope["sectors"],
        "default_term_months": RATE_TERM_MONTHS,
        "supported_term_months": list(RATE_TERM_SCOPES),
        "scopes": scopes,
        "contract": {
            "x_axis": "selected-term representative advertised maximum rate",
            "rate_product_type": RATE_PRODUCT_TYPE,
            "rate_term_months": RATE_TERM_MONTHS,
            "rate_term_scopes": list(RATE_TERM_SCOPES),
            "rate_field": RATE_FIELD,
            "rate_representative": RATE_REPRESENTATIVE,
            "source_precedence": "presentation.db_only_sources",
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
            "product_scope": "term_deposit_only",
            "savings_matrix_supported": False,
        },
    }
