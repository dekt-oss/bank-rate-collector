"""R1 relative-pricing Strategy payload composition.

This module composes the R0 pricing-domain services without changing their
meaning. Pricing-peer eligibility remains independent from funding availability,
and raw availability labels are never promoted into comparison keys here.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from rate_monitor.services.institution_funding_read_model import InstitutionFundingReadRow
from rate_monitor.services.institution_rate_reduction import (
    INSTITUTION_RATE_REDUCTION_POLICY_ID,
    INSTITUTION_RATE_REDUCTION_POLICY_VERSION,
    InstitutionRateCandidate,
    reduce_institution_rates,
)
from rate_monitor.services.pricing_peer_position import (
    PRICING_PEER_POSITION_VERSION,
    pricing_peer_position,
)
from rate_monitor.services.pricing_peer_selection import (
    PRICING_PEER_POLICY_ID,
    PRICING_PEER_POLICY_VERSION,
    PricingPeerCandidate,
    select_pricing_peers,
)
from rate_monitor.services.surface_cost_contract import (
    STANDARD_NOTIONAL_KRW,
    SURFACE_COST_CONTRACT_VERSION,
    standardized_surface_interest_delta,
)

RELATIVE_PRICING_CONTRACT_VERSION = "1"
PRICING_PEER_POSITION_POLICY_ID = "relative-pricing-peer-position"


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _policies() -> dict[str, Any]:
    return {
        "contract_version": RELATIVE_PRICING_CONTRACT_VERSION,
        "institution_rate_reduction": {
            "policy_id": INSTITUTION_RATE_REDUCTION_POLICY_ID,
            "policy_version": INSTITUTION_RATE_REDUCTION_POLICY_VERSION,
        },
        "pricing_peer": {
            "policy_id": PRICING_PEER_POLICY_ID,
            "policy_version": PRICING_PEER_POLICY_VERSION,
        },
        "pricing_peer_position": {
            "policy_id": PRICING_PEER_POSITION_POLICY_ID,
            "policy_version": PRICING_PEER_POSITION_VERSION,
        },
        "surface_cost": {
            "contract_version": SURFACE_COST_CONTRACT_VERSION,
        },
    }


def build_relative_pricing_unavailable_payload(
    *, reason: str, as_of: str | None = None
) -> dict[str, Any]:
    """Return an explicit fail-closed R1 payload when required evidence is absent."""
    normalized_reason = str(reason or "").strip()
    if not normalized_reason:
        raise ValueError("relative-pricing unavailable reason is required")
    return {
        "status": "insufficient_data",
        "reason": normalized_reason,
        "as_of": as_of,
        "policies": _policies(),
        "market_position": None,
        "pricing_peer_position": None,
        "peers": [],
        "factual_cost": None,
    }


def _funding_index(
    rows: Iterable[InstitutionFundingReadRow], *, sector: str
) -> dict[str, InstitutionFundingReadRow]:
    indexed: dict[str, InstitutionFundingReadRow] = {}
    for row in rows:
        if row.sector != sector:
            continue
        if row.institution_id in indexed:
            raise ValueError(
                "duplicate funding row for pricing enrichment: " + row.institution_id
            )
        indexed[row.institution_id] = row
    return indexed


def _pricing_candidate(
    representative: Any,
    *, funding: InstitutionFundingReadRow | None,
) -> PricingPeerCandidate:
    return PricingPeerCandidate(
        institution_id=representative.institution_id,
        representative_product_id=representative.representative_product_id,
        sector=representative.sector,
        product_type=representative.product_type,
        term_months=representative.term_months,
        join_channel=representative.join_channel,
        availability_scope=representative.availability_scope,
        availability_match_key=representative.availability_match_key,
        rate_pct=representative.rate_pct,
        rate_as_of=representative.rate_as_of,
        rate_source_id=representative.source_id,
        rate_policy_id=representative.policy_id,
        rate_policy_version=representative.policy_version,
        source_precedence_policy=representative.source_precedence_policy,
        precedence_applied=representative.precedence_applied,
        funding_balance=funding.balance if funding is not None else None,
        funding_change_6m_pct=(funding.change_6m_pct if funding is not None else None),
        funding_as_of=funding.analysis_month if funding is not None else None,
    )


def _peer_gap_bp(peer_rate: Decimal, own_rate: Decimal) -> Decimal:
    return ((peer_rate - own_rate) * Decimal("100")).quantize(Decimal("0.01"))


def build_relative_pricing_strategy_payload(
    rate_candidates: Iterable[InstitutionRateCandidate],
    *,
    anchor_institution_id: str,
    sector: str,
    product_type: str,
    term_months: int,
    availability_match_key: str,
    funding_rows: Iterable[InstitutionFundingReadRow] = (),
    institution_names: Mapping[str, str] | None = None,
    join_channel: str | None = None,
    proposal_rate_pct: Decimal | float | str | None = None,
    include_special_offer: bool = False,
    retreating_sources: Iterable[str] | None = None,
    market_position: Mapping[str, Any] | None = None,
    as_of: str | None = None,
) -> dict[str, Any]:
    """Compose the factual R1 block from evidence-backed pricing inputs.

    ``availability_match_key`` is mandatory and is passed unchanged to the R0
    reducers/selectors. This function never derives it from display labels or
    geography. Missing funding stays nullable and never changes peer eligibility.
    ``proposal_rate_pct`` is optional; when absent, the current anchor rate is used
    only as a zero-delta baseline, not as a recommendation.
    """
    representatives = reduce_institution_rates(
        rate_candidates,
        sector=sector,
        product_type=product_type,
        term_months=term_months,
        availability_match_key=availability_match_key,
        join_channel=join_channel,
        include_special_offer=include_special_offer,
        retreating_sources=retreating_sources,
    )
    anchor_id = str(anchor_institution_id or "").strip()
    if not anchor_id:
        raise ValueError("anchor_institution_id is required")
    anchor = next(
        (row for row in representatives if row.institution_id == anchor_id),
        None,
    )
    if anchor is None:
        return build_relative_pricing_unavailable_payload(
            reason="anchor_not_in_evidence_backed_pricing_population",
            as_of=as_of,
        )

    funding_by_id = _funding_index(funding_rows, sector=sector)
    candidates = [
        _pricing_candidate(row, funding=funding_by_id.get(row.institution_id))
        for row in representatives
    ]
    selection = select_pricing_peers(
        candidates,
        anchor_institution_id=anchor_id,
        sector=sector,
        product_type=product_type,
        term_months=term_months,
        availability_match_key=availability_match_key,
        join_channel=join_channel,
    )

    current_rate = anchor.rate_pct
    evaluated_rate = (
        current_rate if proposal_rate_pct is None else Decimal(str(proposal_rate_pct))
    )
    position = pricing_peer_position(
        peers=selection.peers,
        current_own_rate_pct=current_rate,
        proposal_rate_pct=evaluated_rate,
    )
    surface_delta = standardized_surface_interest_delta(
        current_rate_pct=current_rate,
        proposal_rate_pct=evaluated_rate,
        term_months=term_months,
    )

    higher_peers = [
        peer
        for peer in selection.peers
        if peer.rate_pct > position.proposal_rate_pct
    ]
    higher_known = [peer for peer in higher_peers if peer.funding_balance is not None]
    higher_funding_total = sum(
        (
            peer.funding_balance
            for peer in higher_known
            if peer.funding_balance is not None
        ),
        Decimal("0"),
    )
    names = institution_names or {}
    peer_rows = [
        {
            "institution_id": peer.institution_id,
            "institution": names.get(peer.institution_id),
            "representative_product_id": peer.representative_product_id,
            "rate_pct": peer.rate_pct,
            "gap_vs_own_bp": _peer_gap_bp(peer.rate_pct, position.proposal_rate_pct),
            "rate_as_of": peer.rate_as_of,
            "rate_source_id": peer.rate_source_id,
            "funding_balance": peer.funding_balance,
            "funding_change_6m_pct": peer.funding_change_6m_pct,
            "funding_as_of": peer.funding_as_of,
            "funding_status": (
                "known" if peer.funding_balance is not None else "unavailable"
            ),
        }
        for peer in selection.peers
    ]

    payload_status = (
        "ready"
        if selection.status == "ready" and position.status == "ready"
        else "insufficient_data"
    )
    payload = {
        "status": payload_status,
        "reason": None if payload_status == "ready" else selection.status,
        "as_of": as_of or _json_value(anchor.rate_as_of),
        "scope": {
            "sector": sector,
            "product_type": product_type,
            "term_months": int(term_months),
            "join_channel": join_channel,
            "availability_match_key": selection.availability_match_key,
            "availability_scope": anchor.availability_scope,
            "include_special_offer": bool(include_special_offer),
        },
        "policies": _policies(),
        "market_position": dict(market_position) if market_position is not None else None,
        "pricing_peer_position": {
            "policy_id": PRICING_PEER_POSITION_POLICY_ID,
            "policy_version": position.version,
            "current_rate_pct": current_rate,
            "evaluated_rate_pct": position.proposal_rate_pct,
            "evaluation_basis": (
                "current_baseline" if proposal_rate_pct is None else "proposal"
            ),
            "pricing_peer_count": selection.pricing_peer_count,
            "peer_median_rate_pct": position.peer_median_rate_pct,
            "peer_gap_bp": position.peer_gap_bp,
            "peer_rank_best": position.rank_best,
            "peer_rank_worst": position.rank_worst,
            "peer_tie_count": position.tie_count,
            "peer_within_5bp_count": position.within_5bp_count,
            "peer_within_10bp_count": position.within_10bp_count,
            "higher_rate_peer_count": position.higher_rate_peer_count,
            "lower_rate_peer_count": position.lower_rate_peer_count,
            "funding_join_count": selection.funding_join_count,
            "funding_unjoined_count": selection.funding_unjoined_count,
            "funding_join_ratio": selection.funding_join_ratio,
            "higher_rate_peer_funding_known_count": len(higher_known),
            "higher_rate_peer_funding_total": higher_funding_total,
            "proposal_transition": {
                "newly_outpriced_count": position.newly_outpriced_count,
                "newly_tied_count": position.newly_tied_count,
                "newly_lost_to_count": position.newly_lost_to_count,
                "newly_tied_down_count": position.newly_tied_down_count,
            },
        },
        "peers": peer_rows,
        "factual_cost": {
            "contract_version": SURFACE_COST_CONTRACT_VERSION,
            "standardized_notional_krw": STANDARD_NOTIONAL_KRW,
            "current_rate_pct": current_rate,
            "evaluated_rate_pct": position.proposal_rate_pct,
            "evaluation_basis": (
                "current_baseline" if proposal_rate_pct is None else "proposal"
            ),
            "standardized_surface_interest_delta_krw": surface_delta,
        },
    }
    return _json_value(payload)
