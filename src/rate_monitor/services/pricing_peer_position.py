"""Institution-level pricing-peer position metrics."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from statistics import median

from rate_monitor.services.pricing_peer_selection import PricingPeerCandidate
from rate_monitor.services.public_structural_v2_market_position_service import normalize_rate

PRICING_PEER_POSITION_VERSION = "1"
CROWDING_5BP = Decimal("0.05")
CROWDING_10BP = Decimal("0.10")


@dataclass(frozen=True)
class PricingPeerPosition:
    status: str
    proposal_rate_pct: Decimal
    peer_count: int
    peer_median_rate_pct: Decimal | None
    peer_gap_bp: Decimal | None
    rank_best: int | None
    rank_worst: int | None
    tie_count: int
    within_5bp_count: int
    within_10bp_count: int
    higher_rate_peer_count: int
    lower_rate_peer_count: int
    newly_outpriced_count: int
    newly_tied_count: int
    newly_lost_to_count: int
    newly_tied_down_count: int
    version: str


def _relation(candidate: Decimal, competitor: Decimal) -> str:
    if candidate > competitor:
        return "ahead"
    if candidate < competitor:
        return "behind"
    return "tied"


def _gap_bp(left: Decimal, right: Decimal) -> Decimal:
    return ((left - right) * Decimal("100")).quantize(Decimal("0.01"))


def pricing_peer_position(
    *,
    peers: Iterable[PricingPeerCandidate],
    current_own_rate_pct: Decimal | float | str,
    proposal_rate_pct: Decimal | float | str,
) -> PricingPeerPosition:
    """Calculate proposal position over institution-level pricing peers."""

    current = normalize_rate(current_own_rate_pct)
    proposal = normalize_rate(proposal_rate_pct)
    normalized: list[tuple[str, Decimal]] = []
    seen: set[str] = set()
    for peer in peers:
        institution_id = str(peer.institution_id or "").strip()
        if not institution_id:
            raise ValueError("pricing peer institution_id is required")
        if institution_id in seen:
            raise ValueError(f"duplicate pricing peer institution: {institution_id}")
        seen.add(institution_id)
        normalized.append((institution_id, normalize_rate(peer.rate_pct)))

    peer_count = len(normalized)
    if not normalized:
        return PricingPeerPosition(
            status="insufficient_peer_coverage",
            proposal_rate_pct=proposal,
            peer_count=0,
            peer_median_rate_pct=None,
            peer_gap_bp=None,
            rank_best=None,
            rank_worst=None,
            tie_count=0,
            within_5bp_count=0,
            within_10bp_count=0,
            higher_rate_peer_count=0,
            lower_rate_peer_count=0,
            newly_outpriced_count=0,
            newly_tied_count=0,
            newly_lost_to_count=0,
            newly_tied_down_count=0,
            version=PRICING_PEER_POSITION_VERSION,
        )

    rates = [rate for _institution_id, rate in normalized]
    peer_median = median(rates)
    higher = sum(rate > proposal for rate in rates)
    lower = sum(rate < proposal for rate in rates)
    ties = sum(rate == proposal for rate in rates)
    rank_best = higher + 1
    rank_worst = higher + ties + 1

    newly_outpriced = 0
    newly_tied = 0
    newly_lost_to = 0
    newly_tied_down = 0
    for _institution_id, rate in normalized:
        before = _relation(current, rate)
        after = _relation(proposal, rate)
        if before in {"behind", "tied"} and after == "ahead":
            newly_outpriced += 1
        if before == "behind" and after == "tied":
            newly_tied += 1
        if before in {"ahead", "tied"} and after == "behind":
            newly_lost_to += 1
        if before == "ahead" and after == "tied":
            newly_tied_down += 1

    return PricingPeerPosition(
        status="ready",
        proposal_rate_pct=proposal,
        peer_count=peer_count,
        peer_median_rate_pct=peer_median,
        peer_gap_bp=_gap_bp(proposal, peer_median),
        rank_best=rank_best,
        rank_worst=rank_worst,
        tie_count=ties,
        within_5bp_count=sum(abs(rate - proposal) <= CROWDING_5BP for rate in rates),
        within_10bp_count=sum(abs(rate - proposal) <= CROWDING_10BP for rate in rates),
        higher_rate_peer_count=higher,
        lower_rate_peer_count=lower,
        newly_outpriced_count=newly_outpriced,
        newly_tied_count=newly_tied,
        newly_lost_to_count=newly_lost_to,
        newly_tied_down_count=newly_tied_down,
        version=PRICING_PEER_POSITION_VERSION,
    )
