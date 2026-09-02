"""Build Relative Pricing rate candidates from canonical current observations.

The adapter consumes only the persisted canonical product/variant/rate path. It
never calls FSB/FinLife directly and never derives availability from geography.
Official FSB availability has already been resolved before this module is called.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from rate_monitor.services.fsb_availability_service import AREA_LABELS
from rate_monitor.services.institution_rate_reduction import InstitutionRateCandidate
from rate_monitor.services.relative_pricing_availability_resolver import (
    RESOLUTION_RESOLVED,
    RelativePricingAvailabilityResolution,
)

RATE_PRODUCT_TYPE = "term_deposit"
RATE_SECTOR = "savings_bank"
RATE_TERM_MONTHS = 12


@dataclass(frozen=True)
class RelativePricingRateCandidateBuild:
    status: str
    availability_match_key: str
    availability_scope: str
    cohort_institution_ids: tuple[str, ...]
    candidate_institution_ids: tuple[str, ...]
    missing_rate_institution_ids: tuple[str, ...]
    candidates: tuple[InstitutionRateCandidate, ...]


def _official_scope(match_key: str) -> str:
    prefix = "fsb:term_deposit:area:"
    if not match_key.startswith(prefix):
        raise ValueError(f"unsupported FSB availability_match_key: {match_key}")
    area_code = match_key[len(prefix) :]
    label = AREA_LABELS.get(area_code)
    if label is None:
        raise ValueError(f"unsupported FSB availability AREA: {area_code}")
    return f"FSB 가입가능지역 {label}"


def _rate_as_of(row: sqlite3.Row) -> date | None:
    raw = row["source_effective_at"] or row["as_of"]
    if raw is None:
        return None
    return date.fromisoformat(str(raw)[:10])


def build_current_relative_pricing_rate_candidates(
    db_path: Path,
    *,
    availability: RelativePricingAvailabilityResolution,
    term_months: int = RATE_TERM_MONTHS,
) -> RelativePricingRateCandidateBuild:
    """Read all current canonical rate rows in one resolved FSB availability cohort."""

    if availability.status != RESOLUTION_RESOLVED or not availability.availability_match_key:
        raise ValueError("resolved official availability is required before rate candidates")
    if not availability.cohort_institution_ids:
        raise ValueError("resolved availability cohort must not be empty")
    target_term = int(term_months)
    if target_term <= 0:
        raise ValueError("term_months must be positive")

    match_key = availability.availability_match_key
    availability_scope = _official_scope(match_key)
    cohort_ids = tuple(sorted(set(availability.cohort_institution_ids)))
    placeholders = ",".join("?" for _ in cohort_ids)
    uri = db_path.resolve().as_uri() + "?mode=ro&immutable=1"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            f"""
            SELECT i.id AS institution_id,
                   p.id AS product_id,
                   cr.source_id,
                   i.sector,
                   p.product_type,
                   pv.term_months,
                   pv.join_channel,
                   p.is_special_sale,
                   ro.max_rate,
                   ro.source_effective_at,
                   ro.as_of
            FROM institutions i
            JOIN products p ON p.institution_id = i.id
            JOIN product_variants pv ON pv.product_id = p.id
            JOIN rate_observations ro ON ro.variant_id = pv.id
            JOIN collection_runs cr ON cr.id = ro.run_id
            WHERE i.id IN ({placeholders})
              AND i.sector = ?
              AND i.active = 1
              AND p.product_type = ?
              AND p.active = 1
              AND pv.term_months = ?
              AND ro.valid_to IS NULL
              AND ro.validation_status != 'error'
              AND ro.max_rate IS NOT NULL
            ORDER BY i.id, p.id, pv.id, cr.source_id
            """,
            (*cohort_ids, RATE_SECTOR, RATE_PRODUCT_TYPE, target_term),
        ).fetchall()
    finally:
        conn.close()

    candidates = tuple(
        InstitutionRateCandidate(
            institution_id=str(row["institution_id"]),
            product_id=str(row["product_id"]),
            source_id=str(row["source_id"]),
            sector=str(row["sector"]),
            product_type=str(row["product_type"]),
            term_months=int(row["term_months"]),
            join_channel=str(row["join_channel"]),
            availability_scope=availability_scope,
            availability_match_key=match_key,
            special_offer_flag=bool(row["is_special_sale"]),
            rate_pct=Decimal(str(row["max_rate"])),
            rate_as_of=_rate_as_of(row),
        )
        for row in rows
    )
    candidate_ids = tuple(sorted({row.institution_id for row in candidates}))
    missing_ids = tuple(sorted(set(cohort_ids) - set(candidate_ids)))
    return RelativePricingRateCandidateBuild(
        status="ready" if candidates else "rate_data_unavailable",
        availability_match_key=match_key,
        availability_scope=availability_scope,
        cohort_institution_ids=cohort_ids,
        candidate_institution_ids=candidate_ids,
        missing_rate_institution_ids=missing_ids,
        candidates=candidates,
    )
