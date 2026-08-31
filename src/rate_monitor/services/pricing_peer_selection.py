"""Pricing-peer selection independent from institution-funding peers.

Pricing peers are institutions with a valid representative rate in the matched
pricing scope. Funding is optional enrichment and never determines eligibility.
Rate provenance and funding as-of metadata stay attached to each peer so later
presentation cannot make different-time observations look simultaneous.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from rate_monitor.services.public_structural_v2_market_position_service import normalize_rate

PRICING_PEER_POLICY_ID = "relative-pricing-peer"
PRICING_PEER_POLICY_VERSION = "1"
UNKNOWN_SCOPES = frozenset({"", "unknown", "none", "unavailable"})


@dataclass(frozen=True)
class PricingPeerCandidate:
    institution_id: str
    representative_product_id: str
    sector: str
    product_type: str
    term_months: int
    join_channel: str
    availability_scope: str
    rate_pct: Decimal
    rate_as_of: date | datetime | None
    rate_source_id: str
    rate_policy_id: str
    rate_policy_version: str
    source_precedence_policy: str
    precedence_applied: bool
    funding_balance: Decimal | None = None
    funding_change_6m_pct: Decimal | None = None
    funding_as_of: str | None = None


@dataclass(frozen=True)
class PricingPeerSelection:
    status: str
    anchor_institution_id: str
    peer_ids: tuple[str, ...]
    peers: tuple[PricingPeerCandidate, ...]
    pricing_peer_count: int
    funding_join_count: int
    funding_unjoined_count: int
    funding_join_ratio: Decimal | None
    policy_id: str
    policy_version: str
    population_rule: str
    availability_scope: str


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


def _normalized_candidate(candidate: PricingPeerCandidate) -> PricingPeerCandidate:
    funding_balance = (
        Decimal(str(candidate.funding_balance))
        if candidate.funding_balance is not None
        else None
    )
    if funding_balance is not None and (not funding_balance.is_finite() or funding_balance < 0):
        raise ValueError("funding_balance must be finite and non-negative")
    funding_change = (
        Decimal(str(candidate.funding_change_6m_pct))
        if candidate.funding_change_6m_pct is not None
        else None
    )
    if funding_change is not None and not funding_change.is_finite():
        raise ValueError("funding_change_6m_pct must be finite")
    funding_as_of = str(candidate.funding_as_of or "").strip() or None
    if funding_balance is not None and funding_as_of is None:
        raise ValueError("funding_as_of is required when funding_balance is known")
    if funding_change is not None and funding_balance is None:
        raise ValueError("funding_balance is required when funding_change_6m_pct is known")

    return PricingPeerCandidate(
        institution_id=_required_text(candidate.institution_id, field="institution_id"),
        representative_product_id=_required_text(
            candidate.representative_product_id,
            field="representative_product_id",
        ),
        sector=_required_text(candidate.sector, field="sector"),
        product_type=_required_text(candidate.product_type, field="product_type"),
        term_months=int(candidate.term_months),
        join_channel=_required_text(candidate.join_channel, field="join_channel"),
        availability_scope=_required_text(
            candidate.availability_scope,
            field="candidate availability_scope",
        ).lower(),
        rate_pct=normalize_rate(candidate.rate_pct),
        rate_as_of=candidate.rate_as_of,
        rate_source_id=_required_text(candidate.rate_source_id, field="rate_source_id"),
        rate_policy_id=_required_text(candidate.rate_policy_id, field="rate_policy_id"),
        rate_policy_version=_required_text(
            candidate.rate_policy_version,
            field="rate_policy_version",
        ),
        source_precedence_policy=_required_text(
            candidate.source_precedence_policy,
            field="source_precedence_policy",
        ),
        precedence_applied=bool(candidate.precedence_applied),
        funding_balance=funding_balance,
        funding_change_6m_pct=funding_change,
        funding_as_of=funding_as_of,
    )


def select_pricing_peers(
    rows: Iterable[PricingPeerCandidate],
    *,
    anchor_institution_id: str,
    sector: str,
    product_type: str,
    term_months: int,
    availability_scope: str,
    join_channel: str | None = None,
) -> PricingPeerSelection:
    """Select the full eligible institution population for pricing comparison.

    No arbitrary ``N`` is applied. Unknown availability scope fails closed
    instead of silently widening to a nationwide peer universe. Funding remains
    optional, but any known balance must carry its own as-of period.
    """

    anchor_id = _required_text(anchor_institution_id, field="anchor_institution_id")
    target_sector = _required_text(sector, field="sector")
    target_product_type = _required_text(product_type, field="product_type")
    target_scope = _required_scope(availability_scope)
    target_term = int(term_months)
    if target_term <= 0:
        raise ValueError("term_months must be positive")
    target_channel = str(join_channel or "").strip() or None

    normalized = [_normalized_candidate(row) for row in rows]
    matched = [
        row
        for row in normalized
        if row.sector == target_sector
        and row.product_type == target_product_type
        and row.term_months == target_term
        and row.availability_scope == target_scope
        and (target_channel is None or row.join_channel == target_channel)
    ]

    by_id: dict[str, PricingPeerCandidate] = {}
    for row in matched:
        if row.institution_id in by_id:
            raise ValueError(
                "duplicate pricing-peer institution after representative-rate reduction: "
                f"{row.institution_id}"
            )
        by_id[row.institution_id] = row

    if anchor_id not in by_id:
        raise ValueError("anchor institution is not present in the matched pricing population")

    peers = tuple(
        by_id[institution_id]
        for institution_id in sorted(by_id)
        if institution_id != anchor_id
    )
    peer_count = len(peers)
    funding_join_count = sum(peer.funding_balance is not None for peer in peers)
    funding_unjoined_count = peer_count - funding_join_count
    funding_join_ratio = (
        Decimal(funding_join_count) / Decimal(peer_count) if peer_count else None
    )
    status = "ready" if peer_count else "insufficient_peer_coverage"

    return PricingPeerSelection(
        status=status,
        anchor_institution_id=anchor_id,
        peer_ids=tuple(peer.institution_id for peer in peers),
        peers=peers,
        pricing_peer_count=peer_count,
        funding_join_count=funding_join_count,
        funding_unjoined_count=funding_unjoined_count,
        funding_join_ratio=funding_join_ratio,
        policy_id=PRICING_PEER_POLICY_ID,
        policy_version=PRICING_PEER_POLICY_VERSION,
        population_rule="all_eligible_institutions",
        availability_scope=target_scope,
    )
