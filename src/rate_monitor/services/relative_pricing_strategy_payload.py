"""R1 relative-pricing Strategy payload composition.

This module composes the R0 pricing-domain services without changing their
meaning. Pricing-peer eligibility remains independent from funding availability,
and raw availability labels are never promoted into comparison keys here.

The payload is deliberately fail-closed around three evidence boundaries:

* funding balances are canonical ``million_krw`` values and are never exposed
  under an unqualified/ambiguous amount name;
* Rate x Funding Matrix and pricing representatives must be reconciled before a
  factual block can become ready;
* special offers are radar evidence only and never replace the core pricing-peer
  representative.
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
    InstitutionRepresentativeRate,
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
from rate_monitor.services.public_structural_v2_market_position_service import normalize_rate
from rate_monitor.services.rate_funding_matrix_service import RATE_REPRESENTATIVE
from rate_monitor.services.surface_cost_contract import (
    STANDARD_NOTIONAL_KRW,
    SURFACE_COST_CONTRACT_VERSION,
    standardized_surface_interest_delta,
)

RELATIVE_PRICING_CONTRACT_VERSION = "3"
PRICING_PEER_POSITION_POLICY_ID = "relative-pricing-peer-position"
MILLION_KRW_TO_KRW = Decimal("1000000")


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
        "representative_rate_reconciliation": None,
        "representative_rate_reconciliations": {},
        "pricing_peer_position": None,
        "peers": [],
        "special_offer_radar": [],
        "factual_cost": None,
    }


def _funding_index(
    rows: Iterable[InstitutionFundingReadRow], *, sector: str
) -> tuple[dict[str, InstitutionFundingReadRow], str | None]:
    """Index one coherent funding vintage for optional pricing enrichment.

    The canonical funding ``balance`` is normalized to ``million_krw``. Mixed
    analysis months are not aggregated: point-in-time factual totals must come
    from one reporting vintage.
    """
    sector_rows = [row for row in rows if row.sector == sector]
    analysis_months = {row.analysis_month for row in sector_rows}
    if len(analysis_months) > 1:
        raise ValueError(
            "mixed funding analysis months for pricing enrichment: "
            + ", ".join(sorted(analysis_months))
        )

    indexed: dict[str, InstitutionFundingReadRow] = {}
    for row in sector_rows:
        if row.institution_id in indexed:
            raise ValueError(
                "duplicate funding row for pricing enrichment: " + row.institution_id
            )
        indexed[row.institution_id] = row
    analysis_month = next(iter(analysis_months), None)
    return indexed, analysis_month


def _pricing_candidate(
    representative: InstitutionRepresentativeRate,
    *,
    funding: InstitutionFundingReadRow | None,
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


def _special_offer_representatives(
    rows: list[InstitutionRateCandidate],
    *,
    sector: str,
    product_type: str,
    term_months: int,
    availability_match_key: str,
    join_channel: str | None,
    retreating_sources: Iterable[str] | None,
    enabled: bool,
) -> list[InstitutionRepresentativeRate]:
    if not enabled:
        return []
    special_rows = [row for row in rows if row.special_offer_flag]
    if not special_rows:
        return []
    return reduce_institution_rates(
        special_rows,
        sector=sector,
        product_type=product_type,
        term_months=term_months,
        availability_match_key=availability_match_key,
        join_channel=join_channel,
        include_special_offer=True,
        retreating_sources=retreating_sources,
    )


def _observation_date(value: date | datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        return None


def _representative_rate_reconciliation(
    *,
    pricing_representative: InstitutionRepresentativeRate,
    matrix_representative_rate_pct: Decimal | float | str | None,
    matrix_representative_policy_id: str | None,
    matrix_representative_rate_as_of: date | datetime | str | None,
    difference_reason: str | None,
) -> dict[str, Any]:
    matrix_policy = str(matrix_representative_policy_id or "").strip()
    pricing_date = _observation_date(pricing_representative.rate_as_of)
    matrix_date = _observation_date(matrix_representative_rate_as_of)
    base = {
        "pricing_policy_id": pricing_representative.policy_id,
        "pricing_policy_version": pricing_representative.policy_version,
        "pricing_rate_pct": pricing_representative.rate_pct,
        "pricing_rate_as_of": pricing_date,
        "matrix_policy_id": matrix_policy or None,
        "matrix_rate_pct": None,
        "matrix_rate_as_of": matrix_date,
        "gap_bp": None,
        "difference_reason": None,
    }
    if matrix_representative_rate_pct is None or not matrix_policy:
        return {"status": "unresolved", **base}
    if matrix_policy != RATE_REPRESENTATIVE:
        return {"status": "policy_mismatch", **base}
    try:
        matrix_rate = normalize_rate(matrix_representative_rate_pct)
    except (ValueError, ArithmeticError):
        return {"status": "invalid", **base}
    base["matrix_rate_pct"] = matrix_rate
    if pricing_date is None or matrix_date is None:
        return {"status": "temporal_unresolved", **base}
    if pricing_date != matrix_date:
        return {"status": "temporal_mismatch", **base}

    gap_bp = _peer_gap_bp(pricing_representative.rate_pct, matrix_rate)
    normalized_reason = str(difference_reason or "").strip() or None
    if gap_bp == 0:
        status = "matched"
        normalized_reason = None
    elif normalized_reason:
        status = "explained"
    else:
        status = "unexplained"
    return {
        "status": status,
        **base,
        "gap_bp": gap_bp,
        "difference_reason": normalized_reason,
    }

def _radar_rows(
    representatives: Iterable[InstitutionRepresentativeRate],
    *,
    names: Mapping[str, str],
) -> list[dict[str, Any]]:
    return [
        {
            "institution_id": row.institution_id,
            "institution": names.get(row.institution_id),
            "representative_product_id": row.representative_product_id,
            "rate_pct": row.rate_pct,
            "rate_as_of": row.rate_as_of,
            "rate_source_id": row.source_id,
            "special_offer_flag": True,
        }
        for row in representatives
    ]


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
    matrix_representatives: Mapping[str, Mapping[str, Any]] | None = None,
    representative_rate_difference_reasons: Mapping[str, str] | None = None,
    matrix_representative_rate_pct: Decimal | float | str | None = None,
    matrix_representative_policy_id: str | None = None,
    matrix_representative_rate_as_of: date | datetime | str | None = None,
    representative_rate_difference_reason: str | None = None,
    as_of: str | None = None,
) -> dict[str, Any]:
    """Compose the factual R1 block from evidence-backed pricing inputs.

    ``availability_match_key`` is mandatory and is passed unchanged to the R0
    reducers/selectors. This function never derives it from display labels or
    geography. Missing funding stays nullable and never changes peer eligibility.

    Special-offer core/radar behavior is not silently inferred. Until the
    repository contract is explicitly promoted, ``include_special_offer=True``
    fails closed. Matrix evidence must be supplied for every displayed canonical
    institution, with the canonical Matrix policy and the same observation date.
    """
    rate_rows = list(rate_candidates)
    names = institution_names or {}
    if include_special_offer:
        raise ValueError(
            "special-offer core/radar policy is not approved; "
            "include_special_offer must remain False"
        )
    radar: list[dict[str, Any]] = []

    # Core pricing ranking remains the existing non-promotional population.
    representatives = reduce_institution_rates(
        rate_rows,
        sector=sector,
        product_type=product_type,
        term_months=term_months,
        availability_match_key=availability_match_key,
        join_channel=join_channel,
        include_special_offer=False,
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
        payload = build_relative_pricing_unavailable_payload(
            reason="anchor_not_in_evidence_backed_pricing_population",
            as_of=as_of,
        )
        payload["special_offer_radar"] = _json_value(radar)
        return payload

    matrix_by_id: dict[str, Mapping[str, Any]] = dict(matrix_representatives or {})
    if anchor_id not in matrix_by_id and (
        matrix_representative_rate_pct is not None
        or matrix_representative_policy_id is not None
        or matrix_representative_rate_as_of is not None
    ):
        matrix_by_id[anchor_id] = {
            "rate_pct": matrix_representative_rate_pct,
            "policy_id": matrix_representative_policy_id,
            "rate_as_of": matrix_representative_rate_as_of,
        }
    reasons = dict(representative_rate_difference_reasons or {})
    if representative_rate_difference_reason and anchor_id not in reasons:
        reasons[anchor_id] = representative_rate_difference_reason

    reconciliations: dict[str, dict[str, Any]] = {}
    for representative in representatives:
        evidence = matrix_by_id.get(representative.institution_id, {})
        if not isinstance(evidence, Mapping):
            raise ValueError(
                "matrix representative evidence must be a mapping for institution "
                + representative.institution_id
            )
        reconciliations[representative.institution_id] = (
            _representative_rate_reconciliation(
                pricing_representative=representative,
                matrix_representative_rate_pct=evidence.get("rate_pct"),
                matrix_representative_policy_id=evidence.get("policy_id"),
                matrix_representative_rate_as_of=evidence.get("rate_as_of"),
                difference_reason=reasons.get(representative.institution_id),
            )
        )

    blocked_statuses = {
        item["status"] for item in reconciliations.values()
        if item["status"] not in {"matched", "explained"}
    }
    reconciliation = reconciliations[anchor_id]
    if blocked_statuses:
        if "temporal_mismatch" in blocked_statuses:
            reason = "matrix_representative_rate_temporal_mismatch"
        elif "temporal_unresolved" in blocked_statuses:
            reason = "matrix_representative_rate_temporal_unresolved"
        elif "invalid" in blocked_statuses:
            reason = "matrix_representative_rate_invalid"
        elif "policy_mismatch" in blocked_statuses:
            reason = "matrix_representative_policy_noncanonical"
        elif "unresolved" in blocked_statuses:
            reason = "matrix_representative_rate_unresolved"
        else:
            reason = "representative_rate_policy_mismatch_unexplained"
        payload = build_relative_pricing_unavailable_payload(reason=reason, as_of=as_of)
        payload["representative_rate_reconciliation"] = _json_value(reconciliation)
        payload["representative_rate_reconciliations"] = _json_value(reconciliations)
        payload["special_offer_radar"] = _json_value(radar)
        return payload

    funding_by_id, funding_analysis_month = _funding_index(funding_rows, sector=sector)
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
        peer for peer in selection.peers if peer.rate_pct > position.proposal_rate_pct
    ]
    higher_known = [peer for peer in higher_peers if peer.funding_balance is not None]
    if not higher_peers:
        higher_funding_total_krw: Decimal | None = Decimal("0")
    elif not higher_known:
        # Higher-rate peers exist, but none has a funding observation. Missing is
        # not a measured zero.
        higher_funding_total_krw = None
    else:
        higher_funding_total_million_krw = sum(
            (
                peer.funding_balance
                for peer in higher_known
                if peer.funding_balance is not None
            ),
            Decimal("0"),
        )
        higher_funding_total_krw = (
            higher_funding_total_million_krw * MILLION_KRW_TO_KRW
        )

    peer_rows = [
        {
            "institution_id": peer.institution_id,
            "institution": names.get(peer.institution_id),
            "representative_product_id": peer.representative_product_id,
            "rate_pct": peer.rate_pct,
            "gap_vs_own_bp": _peer_gap_bp(peer.rate_pct, position.proposal_rate_pct),
            "rate_as_of": peer.rate_as_of,
            "rate_source_id": peer.rate_source_id,
            "funding_balance_million_krw": peer.funding_balance,
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
            "include_special_offer_in_core": False,
            "special_offer_radar_included": False,
        },
        "policies": _policies(),
        "market_position": dict(market_position) if market_position is not None else None,
        "representative_rate_reconciliation": reconciliation,
        "representative_rate_reconciliations": reconciliations,
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
            "funding_analysis_month": funding_analysis_month,
            "funding_join_count": selection.funding_join_count,
            "funding_unjoined_count": selection.funding_unjoined_count,
            "funding_join_ratio": selection.funding_join_ratio,
            "higher_rate_peer_funding_known_count": len(higher_known),
            "higher_rate_peer_funding_total_krw": higher_funding_total_krw,
            "proposal_transition": {
                "newly_outpriced_count": position.newly_outpriced_count,
                "newly_tied_count": position.newly_tied_count,
                "newly_lost_to_count": position.newly_lost_to_count,
                "newly_tied_down_count": position.newly_tied_down_count,
            },
        },
        "peers": peer_rows,
        "special_offer_radar": radar,
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
