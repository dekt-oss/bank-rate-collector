from datetime import date
from decimal import Decimal

import pytest

from rate_monitor.services.pricing_peer_position import pricing_peer_position
from rate_monitor.services.pricing_peer_selection import PricingPeerCandidate


def _peer(institution_id: str, rate: str) -> PricingPeerCandidate:
    return PricingPeerCandidate(
        institution_id=institution_id,
        representative_product_id=f"p-{institution_id}",
        sector="savings_bank",
        product_type="term_deposit",
        term_months=12,
        join_channel="online",
        availability_scope="nationwide",
        rate_pct=Decimal(rate),
        rate_as_of=date(2026, 8, 31),
        rate_source_id="fsb",
        rate_policy_id="relative-pricing-institution-rate",
        rate_policy_version="1",
        source_precedence_policy="presentation.db_only_sources",
        precedence_applied=True,
    )


def test_pricing_peer_position_uses_institution_population_and_peer_median() -> None:
    result = pricing_peer_position(
        peers=[
            _peer("a", "3.40"),
            _peer("b", "3.50"),
            _peer("c", "3.60"),
            _peer("d", "3.70"),
        ],
        current_own_rate_pct="3.45",
        proposal_rate_pct="3.55",
    )

    assert result.status == "ready"
    assert result.peer_count == 4
    assert result.peer_median_rate_pct == Decimal("3.5500")
    assert result.peer_gap_bp == Decimal("0.00")
    assert result.rank_best == 3
    assert result.rank_worst == 3
    assert result.higher_rate_peer_count == 2
    assert result.lower_rate_peer_count == 2


def test_ties_crowding_and_transitions_are_explicit() -> None:
    result = pricing_peer_position(
        peers=[
            _peer("tie", "3.55"),
            _peer("near", "3.60"),
            _peer("far", "3.70"),
            _peer("low", "3.40"),
        ],
        current_own_rate_pct="3.50",
        proposal_rate_pct="3.55",
    )

    assert result.tie_count == 1
    assert result.within_5bp_count == 2
    assert result.within_10bp_count == 2
    assert result.rank_best == 3
    assert result.rank_worst == 4
    assert result.newly_tied_count == 1
    assert result.newly_outpriced_count == 0


def test_rate_cut_that_loses_peers_is_counted() -> None:
    result = pricing_peer_position(
        peers=[
            _peer("a", "3.45"),
            _peer("b", "3.50"),
            _peer("c", "3.55"),
        ],
        current_own_rate_pct="3.60",
        proposal_rate_pct="3.50",
    )

    assert result.newly_lost_to_count == 1
    assert result.newly_tied_down_count == 1


def test_empty_peer_population_returns_fail_closed_status() -> None:
    result = pricing_peer_position(
        peers=[],
        current_own_rate_pct="3.50",
        proposal_rate_pct="3.55",
    )

    assert result.status == "insufficient_peer_coverage"
    assert result.peer_count == 0
    assert result.peer_median_rate_pct is None
    assert result.rank_best is None


def test_duplicate_peer_institution_fails_closed() -> None:
    with pytest.raises(ValueError, match="duplicate pricing peer institution"):
        pricing_peer_position(
            peers=[_peer("dup", "3.50"), _peer("dup", "3.60")],
            current_own_rate_pct="3.50",
            proposal_rate_pct="3.55",
        )
