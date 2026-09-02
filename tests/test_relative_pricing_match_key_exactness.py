from datetime import date
from decimal import Decimal

import pytest

from rate_monitor.services.fsb_availability_service import availability_match_key
from rate_monitor.services.institution_rate_reduction import (
    InstitutionRateCandidate,
    reduce_institution_rates,
)
from rate_monitor.services.pricing_peer_selection import (
    PricingPeerCandidate,
    select_pricing_peers,
)


def _rate_candidate(institution_id: str, key: str) -> InstitutionRateCandidate:
    return InstitutionRateCandidate(
        institution_id=institution_id,
        product_id=f"p-{institution_id}",
        source_id="fsb",
        sector="savings_bank",
        product_type="term_deposit",
        term_months=12,
        join_channel="online",
        availability_scope="FSB 가입가능지역 부산",
        availability_match_key=key,
        special_offer_flag=False,
        rate_pct=Decimal("3.50"),
        rate_as_of=date(2026, 9, 1),
    )


def _peer_candidate(institution_id: str, key: str) -> PricingPeerCandidate:
    return PricingPeerCandidate(
        institution_id=institution_id,
        representative_product_id=f"p-{institution_id}",
        sector="savings_bank",
        product_type="term_deposit",
        term_months=12,
        join_channel="online",
        availability_scope="FSB 가입가능지역 부산",
        availability_match_key=key,
        rate_pct=Decimal("3.50"),
        rate_as_of=date(2026, 9, 1),
        rate_source_id="fsb",
        rate_policy_id="relative-pricing-institution-rate",
        rate_policy_version="1",
        source_precedence_policy="presentation.db_only_sources",
        precedence_applied=True,
    )


def test_rate_reduction_preserves_exact_official_fsb_match_key() -> None:
    key = availability_match_key("YN_Busan")

    rows = reduce_institution_rates(
        [_rate_candidate("anchor", key)],
        sector="savings_bank",
        product_type="term_deposit",
        term_months=12,
        availability_match_key=key,
        join_channel="online",
        retreating_sources=set(),
    )

    assert len(rows) == 1
    assert rows[0].availability_match_key == key
    assert rows[0].availability_match_key.endswith("YN_Busan")


def test_rate_reduction_does_not_case_fold_evidence_key() -> None:
    key = availability_match_key("YN_Busan")

    rows = reduce_institution_rates(
        [_rate_candidate("anchor", key)],
        sector="savings_bank",
        product_type="term_deposit",
        term_months=12,
        availability_match_key=key.lower(),
        join_channel="online",
        retreating_sources=set(),
    )

    assert rows == []


def test_peer_selection_preserves_exact_official_fsb_match_key() -> None:
    key = availability_match_key("YN_Busan")

    result = select_pricing_peers(
        [_peer_candidate("anchor", key), _peer_candidate("peer", key)],
        anchor_institution_id="anchor",
        sector="savings_bank",
        product_type="term_deposit",
        term_months=12,
        availability_match_key=key,
        join_channel="online",
    )

    assert result.availability_match_key == key
    assert result.peer_ids == ("peer",)


def test_peer_selection_rejects_case_mismatched_evidence_population() -> None:
    key = availability_match_key("YN_Busan")

    with pytest.raises(ValueError, match="anchor institution"):
        select_pricing_peers(
            [_peer_candidate("anchor", key), _peer_candidate("peer", key)],
            anchor_institution_id="anchor",
            sector="savings_bank",
            product_type="term_deposit",
            term_months=12,
            availability_match_key=key.lower(),
            join_channel="online",
        )
