"""Compose the production-format Relative Pricing R1 read model from DB evidence.

This module is orchestration only. It does not define a new rate, peer, funding,
or cost formula: the versioned R0/R1 domain services remain authoritative.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from rate_monitor.services.institution_funding_read_model import InstitutionFundingReadRow
from rate_monitor.services.institution_funding_read_model_db import (
    build_institution_funding_read_model_from_db,
)
from rate_monitor.services.institution_rate_reduction import reduce_institution_rates
from rate_monitor.services.relative_pricing_availability_resolver import (
    RESOLUTION_RESOLVED,
    RelativePricingAvailabilityResolution,
)
from rate_monitor.services.relative_pricing_matrix_evidence import (
    MatrixRepresentativeEvidence,
    build_current_matrix_representative_evidence,
)
from rate_monitor.services.relative_pricing_rate_candidates import (
    RATE_PRODUCT_TYPE,
    RATE_SECTOR,
    RATE_TERM_MONTHS,
    RelativePricingRateCandidateBuild,
    build_current_relative_pricing_rate_candidates,
)
from rate_monitor.services.relative_pricing_strategy_payload import (
    build_relative_pricing_strategy_payload,
)


@dataclass(frozen=True)
class RelativePricingLiveBuild:
    payload: dict[str, Any]
    rate_candidates: RelativePricingRateCandidateBuild
    matrix_evidence: Mapping[str, MatrixRepresentativeEvidence]
    funding_analysis_month: str | None

    def diagnostics(self) -> dict[str, Any]:
        return {
            "status": self.rate_candidates.status,
            "availability_match_key": self.rate_candidates.availability_match_key,
            "availability_scope": self.rate_candidates.availability_scope,
            "cohort_institution_ids": list(self.rate_candidates.cohort_institution_ids),
            "candidate_institution_ids": list(
                self.rate_candidates.candidate_institution_ids
            ),
            "missing_rate_institution_ids": list(
                self.rate_candidates.missing_rate_institution_ids
            ),
            "candidate_row_count": len(self.rate_candidates.candidates),
            "matrix_evidence_institution_ids": sorted(self.matrix_evidence),
            "matrix_rate_as_of_status": {
                institution_id: evidence.rate_as_of_status
                for institution_id, evidence in sorted(self.matrix_evidence.items())
            },
            "funding_analysis_month": self.funding_analysis_month,
        }


def _funding_month(
    funding_positions: Mapping[str, Any] | None,
    *,
    sector: str,
) -> str | None:
    if not funding_positions:
        return None
    sectors = funding_positions.get("sectors")
    if not isinstance(sectors, Mapping):
        return None
    sector_payload = sectors.get(sector)
    if not isinstance(sector_payload, Mapping):
        return None
    value = str(sector_payload.get("analysis_month") or "").strip()
    return value or None


def _load_funding_rows(
    db_path: Path,
    *,
    sector: str,
    analysis_month: str | None,
) -> list[InstitutionFundingReadRow]:
    if analysis_month is None:
        return []
    return build_institution_funding_read_model_from_db(
        db_path,
        sector=sector,
        analysis_month=analysis_month,
    )


def _institution_names(db_path: Path, institution_ids: set[str]) -> dict[str, str]:
    if not institution_ids:
        return {}
    placeholders = ",".join("?" for _ in institution_ids)
    uri = db_path.resolve().as_uri() + "?mode=ro&immutable=1"
    conn = sqlite3.connect(uri, uri=True)
    try:
        rows = conn.execute(
            f"SELECT id, canonical_name FROM institutions "
            f"WHERE id IN ({placeholders})",
            tuple(sorted(institution_ids)),
        ).fetchall()
    finally:
        conn.close()
    return {str(row[0]): str(row[1] or "") for row in rows}


def _matrix_payloads(
    evidence: Mapping[str, MatrixRepresentativeEvidence],
) -> dict[str, dict[str, object]]:
    return {
        institution_id: item.as_payload()
        for institution_id, item in sorted(evidence.items())
    }


def _difference_reasons(
    evidence: Mapping[str, MatrixRepresentativeEvidence],
    *,
    pricing_rates: Mapping[str, object],
) -> dict[str, str]:
    reasons: dict[str, str] = {}
    for institution_id, item in evidence.items():
        pricing_rate = pricing_rates.get(institution_id)
        if pricing_rate is None or item.pricing_core_difference_reason is None:
            continue
        if pricing_rate != item.rate_pct:
            reasons[institution_id] = item.pricing_core_difference_reason
    return reasons


def build_relative_pricing_live(
    db_path: Path,
    *,
    availability: RelativePricingAvailabilityResolution,
    funding_positions: Mapping[str, Any] | None = None,
    market_position: Mapping[str, Any] | None = None,
    term_months: int = RATE_TERM_MONTHS,
) -> RelativePricingLiveBuild:
    """Build Relative Pricing only after official availability resolves exactly."""
    if availability.status != RESOLUTION_RESOLVED:
        raise ValueError("resolved official availability is required")
    anchor_id = str(availability.anchor_institution_id or "").strip()
    if not anchor_id:
        raise ValueError("resolved availability must include anchor_institution_id")
    match_key = str(availability.availability_match_key or "").strip()
    if not match_key:
        raise ValueError("resolved availability must include availability_match_key")

    candidate_build = build_current_relative_pricing_rate_candidates(
        db_path,
        availability=availability,
        term_months=term_months,
    )
    representatives = reduce_institution_rates(
        candidate_build.candidates,
        sector=RATE_SECTOR,
        product_type=RATE_PRODUCT_TYPE,
        term_months=term_months,
        availability_match_key=match_key,
        include_special_offer=False,
    )
    representative_ids = {row.institution_id for row in representatives}
    matrix_evidence = build_current_matrix_representative_evidence(
        db_path,
        institution_ids=representative_ids,
        product_type=RATE_PRODUCT_TYPE,
        term_months=term_months,
    )
    pricing_rates = {row.institution_id: row.rate_pct for row in representatives}
    difference_reasons = _difference_reasons(
        matrix_evidence,
        pricing_rates=pricing_rates,
    )

    funding_month = _funding_month(funding_positions, sector=RATE_SECTOR)
    funding_rows = _load_funding_rows(
        db_path,
        sector=RATE_SECTOR,
        analysis_month=funding_month,
    )
    institution_names = _institution_names(db_path, representative_ids)
    payload = build_relative_pricing_strategy_payload(
        candidate_build.candidates,
        anchor_institution_id=anchor_id,
        sector=RATE_SECTOR,
        product_type=RATE_PRODUCT_TYPE,
        term_months=term_months,
        availability_match_key=match_key,
        funding_rows=funding_rows,
        institution_names=institution_names,
        include_special_offer=False,
        market_position=market_position,
        matrix_representatives=_matrix_payloads(matrix_evidence),
        representative_rate_difference_reasons=difference_reasons,
    )
    return RelativePricingLiveBuild(
        payload=payload,
        rate_candidates=candidate_build,
        matrix_evidence=matrix_evidence,
        funding_analysis_month=funding_month,
    )
