from datetime import date
from decimal import Decimal

import pytest

from rate_monitor.services.pricing_peer_selection import (
    PRICING_PEER_POLICY_ID,
    PricingPeerCandidate,
    select_pricing_peers,
)


def _peer(
    institution_id: str,
    rate: str,
    *,
    funding: str | None = None,
    funding_as_of: str | None = None,
    scope: str = "전국",
    match_key: str = "nationwide",
    channel: str = "online",
) -> PricingPeerCandidate:
    return PricingPeerCandidate(
        institution_id=institution_id,
        representative_product_id=f"p-{institution_id}",
        sector="savings_bank",
        product_type="term_deposit",
        term_months=12,
        join_channel=channel,
        availability_scope=scope,
        availability_match_key=match_key,
        rate_pct=Decimal(rate),
        rate_as_of=date(2026, 8, 31),
        rate_source_id="fsb",
        rate_policy_id="relative-pricing-institution-rate",
        rate_policy_version="1",
        source_precedence_policy="presentation.db_only_sources",
        precedence_applied=True,
        funding_balance=Decimal(funding) if funding is not None else None,
        funding_change_6m_pct=None,
        funding_as_of=(funding_as_of or "2026-03") if funding is not None else None,
    )


def _select(rows, *, match_key: str = "nationwide"):
    return select_pricing_peers(
        rows,
        anchor_institution_id="anchor",
        sector="savings_bank",
        product_type="term_deposit",
        term_months=12,
        availability_match_key=match_key,
        join_channel="online",
    )


def test_pricing_peer_uses_full_eligible_population_without_arbitrary_n() -> None:
    rows = [_peer("anchor", "3.50")]
    rows.extend(_peer(f"peer-{index:02d}", "3.40") for index in range(25))

    result = _select(rows)

    assert result.status == "ready"
    assert result.pricing_peer_count == 25
    assert len(result.peer_ids) == 25
    assert result.policy_id == PRICING_PEER_POLICY_ID
    assert result.population_rule == "all_eligible_institutions"
    assert result.availability_match_key == "nationwide"


def test_missing_funding_does_not_remove_pricing_peer() -> None:
    result = _select(
        [
            _peer("anchor", "3.50", funding="1000"),
            _peer("known", "3.60", funding="900"),
            _peer("unknown", "3.55", funding=None),
        ]
    )

    assert result.peer_ids == ("known", "unknown")
    assert result.pricing_peer_count == 2
    assert result.funding_join_count == 1
    assert result.funding_unjoined_count == 1
    assert result.funding_join_ratio == Decimal("0.5")
    assert result.peers[1].funding_balance is None


def test_rate_provenance_and_different_funding_as_of_are_preserved() -> None:
    result = _select(
        [
            _peer("anchor", "3.50"),
            _peer("peer", "3.60", funding="900", funding_as_of="2026-03"),
        ]
    )

    peer = result.peers[0]
    assert peer.rate_as_of == date(2026, 8, 31)
    assert peer.rate_source_id == "fsb"
    assert peer.rate_policy_id == "relative-pricing-institution-rate"
    assert peer.rate_policy_version == "1"
    assert peer.source_precedence_policy == "presentation.db_only_sources"
    assert peer.precedence_applied is True
    assert peer.funding_as_of == "2026-03"


def test_duplicate_institution_after_reduction_fails_closed() -> None:
    with pytest.raises(ValueError, match="duplicate pricing-peer institution"):
        _select(
            [
                _peer("anchor", "3.50"),
                _peer("dup", "3.60"),
                _peer("dup", "3.70"),
            ]
        )


def test_anchor_must_exist_in_matched_population() -> None:
    with pytest.raises(ValueError, match="anchor institution"):
        _select([_peer("other", "3.60")])


def test_unknown_match_key_fails_closed_instead_of_widening_to_nationwide() -> None:
    with pytest.raises(ValueError, match="availability_match_key"):
        select_pricing_peers(
            [_peer("anchor", "3.50")],
            anchor_institution_id="anchor",
            sector="savings_bank",
            product_type="term_deposit",
            term_months=12,
            availability_match_key="미상",
        )


def test_same_raw_local_label_is_not_enough_to_make_peers() -> None:
    result = _select(
        [
            _peer("anchor", "3.50", scope="지역금고", match_key="local:busan"),
            _peer("same", "3.55", scope="지역금고", match_key="local:busan"),
            _peer("seoul", "3.70", scope="지역금고", match_key="local:seoul"),
        ],
        match_key="local:busan",
    )

    assert result.peer_ids == ("same",)


def test_mismatched_channel_is_not_a_peer() -> None:
    result = _select(
        [
            _peer("anchor", "3.50"),
            _peer("same", "3.55"),
            _peer("branch", "3.80", channel="branch"),
        ]
    )

    assert result.peer_ids == ("same",)


def test_zero_peer_population_is_explicitly_insufficient() -> None:
    result = _select([_peer("anchor", "3.50")])

    assert result.status == "insufficient_peer_coverage"
    assert result.pricing_peer_count == 0
    assert result.funding_join_ratio is None


def test_known_funding_without_as_of_fails_closed() -> None:
    row = _peer("anchor", "3.50", funding=None)
    bad = PricingPeerCandidate(
        **{
            **row.__dict__,
            "funding_balance": Decimal("1000"),
            "funding_as_of": None,
        }
    )

    with pytest.raises(ValueError, match="funding_as_of"):
        _select([bad])


def test_funding_change_without_balance_fails_closed() -> None:
    row = _peer("anchor", "3.50", funding=None)
    bad = PricingPeerCandidate(
        **{
            **row.__dict__,
            "funding_change_6m_pct": Decimal("0.05"),
        }
    )

    with pytest.raises(ValueError, match="funding_balance"):
        _select([bad])
