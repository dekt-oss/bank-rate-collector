"""Institution-level representative pricing-rate reduction.

This module is deliberately separate from Rate × Funding's existing representative
rate semantics. It builds one deterministic pricing representative per institution
for a matched product/term/availability scope and applies the same presentation
source-retreat rule before choosing the rate.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from rate_monitor.services.dashboard_service import dedupe_sources
from rate_monitor.services.public_structural_v2_market_position_service import normalize_rate

INSTITUTION_RATE_REDUCTION_POLICY_ID = "relative-pricing-institution-rate"
INSTITUTION_RATE_REDUCTION_POLICY_VERSION = "1"
SOURCE_PRECEDENCE_POLICY = "presentation.db_only_sources"
UNKNOWN_SCOPES = frozenset({"", "unknown", "none", "unavailable"})


@dataclass(frozen=True)
class InstitutionRateCandidate:
    institution_id: str
    product_id: str
    source_id: str
    sector: str
    product_type: str
    term_months: int
    join_channel: str
    availability_scope: str
    special_offer_flag: bool
    rate_pct: Decimal
    rate_as_of: date | datetime | None = None


@dataclass(frozen=True)
class InstitutionRepresentativeRate:
    institution_id: str
    representative_product_id: str
    source_id: str
    sector: str
    product_type: str
    term_months: int
    join_channel: str
    availability_scope: str
    special_offer_flag: bool
    rate_pct: Decimal
    rate_as_of: date | datetime | None
    selection_reason: str
    policy_id: str
    policy_version: str
    source_precedence_policy: str
    precedence_applied: bool


def _required_text(value: object, *, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    return text


def _required_scope(value: object) -> str:
    scope = _required_text(value, field="availability_scope").lower()
    if scope in UNKNOWN_SCOPES:
        raise ValueError("availability_scope must be evidence-backed, not unknown")
    return scope


def _normalized_candidate(candidate: InstitutionRateCandidate) -> InstitutionRateCandidate:
    return InstitutionRateCandidate(
        institution_id=_required_text(candidate.institution_id, field="institution_id"),
        product_id=_required_text(candidate.product_id, field="product_id"),
        source_id=_required_text(candidate.source_id, field="source_id"),
        sector=_required_text(candidate.sector, field="sector"),
        product_type=_required_text(candidate.product_type, field="product_type"),
        term_months=int(candidate.term_months),
        join_channel=_required_text(candidate.join_channel, field="join_channel"),
        availability_scope=_required_text(
            candidate.availability_scope,
            field="candidate availability_scope",
        ).lower(),
        special_offer_flag=bool(candidate.special_offer_flag),
        rate_pct=normalize_rate(candidate.rate_pct),
        rate_as_of=candidate.rate_as_of,
    )


def reduce_institution_rates(
    rows: Iterable[InstitutionRateCandidate],
    *,
    sector: str,
    product_type: str,
    term_months: int,
    availability_scope: str,
    join_channel: str | None = None,
    include_special_offer: bool = False,
    retreating_sources: Iterable[str] | None = None,
) -> list[InstitutionRepresentativeRate]:
    """Return one deterministic representative rate per institution.

    ``availability_scope`` is required and must not be unknown. The function
    does not silently widen an unknown scope to nationwide.

    Source precedence mirrors the existing Strategy presentation rule: a source
    listed in ``db_only_sources`` retreats when the same institution has at
    least one eligible non-retreating source row.
    """

    target_sector = _required_text(sector, field="sector")
    target_product_type = _required_text(product_type, field="product_type")
    target_scope = _required_scope(availability_scope)
    target_term = int(term_months)
    if target_term <= 0:
        raise ValueError("term_months must be positive")
    target_channel = str(join_channel or "").strip() or None

    normalized = [_normalized_candidate(row) for row in rows]
    eligible = [
        row
        for row in normalized
        if row.sector == target_sector
        and row.product_type == target_product_type
        and row.term_months == target_term
        and row.availability_scope == target_scope
        and (target_channel is None or row.join_channel == target_channel)
        and (include_special_offer or not row.special_offer_flag)
    ]

    retreating = set(retreating_sources if retreating_sources is not None else dedupe_sources())
    covered_by_primary = {
        row.institution_id for row in eligible if row.source_id not in retreating
    }
    precedence_filtered = [
        row
        for row in eligible
        if not (row.source_id in retreating and row.institution_id in covered_by_primary)
    ]

    by_institution: dict[str, list[InstitutionRateCandidate]] = {}
    for row in precedence_filtered:
        by_institution.setdefault(row.institution_id, []).append(row)

    result: list[InstitutionRepresentativeRate] = []
    for institution_id in sorted(by_institution):
        candidates = sorted(
            by_institution[institution_id],
            key=lambda row: (-row.rate_pct, row.product_id, row.source_id),
        )
        selected = candidates[0]
        result.append(
            InstitutionRepresentativeRate(
                institution_id=institution_id,
                representative_product_id=selected.product_id,
                source_id=selected.source_id,
                sector=selected.sector,
                product_type=selected.product_type,
                term_months=selected.term_months,
                join_channel=selected.join_channel,
                availability_scope=selected.availability_scope,
                special_offer_flag=selected.special_offer_flag,
                rate_pct=selected.rate_pct,
                rate_as_of=selected.rate_as_of,
                selection_reason="max_rate_within_matched_scope",
                policy_id=INSTITUTION_RATE_REDUCTION_POLICY_ID,
                policy_version=INSTITUTION_RATE_REDUCTION_POLICY_VERSION,
                source_precedence_policy=SOURCE_PRECEDENCE_POLICY,
                precedence_applied=True,
            )
        )
    return result
