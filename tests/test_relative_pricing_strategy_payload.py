from datetime import date
from decimal import Decimal

import pytest

from rate_monitor.services.institution_funding_read_model import InstitutionFundingReadRow
from rate_monitor.services.institution_rate_reduction import InstitutionRateCandidate
from rate_monitor.services.relative_pricing_strategy_payload import (
    RELATIVE_PRICING_CONTRACT_VERSION,
    build_relative_pricing_strategy_payload,
    build_relative_pricing_unavailable_payload,
)


def _rate(
    institution_id: str,
    product_id: str,
    rate: str,
    *,
    match_key: str = "nationwide",
    special_offer: bool = False,
) -> InstitutionRateCandidate:
    return InstitutionRateCandidate(
        institution_id=institution_id,
        product_id=product_id,
        source_id="fsb",
        sector="savings_bank",
        product_type="term_deposit",
        term_months=12,
        join_channel="online",
        availability_scope="전국",
        availability_match_key=match_key,
        special_offer_flag=special_offer,
        rate_pct=Decimal(rate),
        rate_as_of=date(2026, 9, 1),
    )


def _funding(
    institution_id: str,
    balance: str,
    *,
    change_6m_pct: str | None = None,
    analysis_month: str = "2026-03",
) -> InstitutionFundingReadRow:
    change = Decimal(change_6m_pct) if change_6m_pct is not None else None
    return InstitutionFundingReadRow(
        institution_id=institution_id,
        sector="savings_bank",
        analysis_month=analysis_month,
        balance=Decimal(balance),
        balance_6m_ago=None,
        balance_12m_ago=None,
        change_6m_amount=None,
        change_6m_pct=change,
        change_12m_amount=None,
        change_12m_pct=None,
        sector_balance_percentile=Decimal("50"),
        sector_growth_6m_percentile=None,
        sector_growth_12m_percentile=None,
        sector_median_growth_6m=None,
        relative_growth_6m_vs_peer_median=None,
    )


def _matrix(**rates: str) -> dict[str, dict[str, str]]:
    return {
        institution_id: {
            "rate_pct": rate,
            "policy_id": "institution_product_representative_max",
            "rate_as_of": "2026-09-01",
        }
        for institution_id, rate in rates.items()
    }


def _build(**kwargs):
    return build_relative_pricing_strategy_payload(
        [
            _rate("our", "p-our", "3.50"),
            _rate("high", "p-high", "3.60"),
            _rate("low", "p-low", "3.40"),
        ],
        anchor_institution_id="our",
        sector="savings_bank",
        product_type="term_deposit",
        term_months=12,
        availability_match_key="nationwide",
        join_channel="online",
        funding_rows=[
            _funding("our", "80"),
            _funding("high", "60", change_6m_pct="0.02"),
        ],
        institution_names={"high": "상위은행", "low": "하위은행"},
        matrix_representatives=_matrix(our="3.50", high="3.60", low="3.40"),
        as_of="2026-09-01",
        retreating_sources=set(),
        **kwargs,
    )


def test_r1_payload_composes_pricing_peers_funding_and_factual_cost() -> None:
    payload = _build(
        proposal_rate_pct="3.55",
        market_position={"status": "existing_product_market_contract"},
    )

    assert payload["status"] == "ready"
    assert RELATIVE_PRICING_CONTRACT_VERSION == "3"
    assert payload["policies"]["contract_version"] == RELATIVE_PRICING_CONTRACT_VERSION
    assert payload["market_position"] == {
        "status": "existing_product_market_contract"
    }
    assert payload["representative_rate_reconciliation"] == {
        "status": "matched",
        "pricing_policy_id": "relative-pricing-institution-rate",
        "pricing_policy_version": "1",
        "pricing_rate_pct": "3.5000",
        "pricing_rate_as_of": "2026-09-01",
        "matrix_policy_id": "institution_product_representative_max",
        "matrix_rate_pct": "3.5000",
        "matrix_rate_as_of": "2026-09-01",
        "gap_bp": "0.00",
        "difference_reason": None,
    }

    position = payload["pricing_peer_position"]
    assert position["current_rate_pct"] == "3.5000"
    assert position["evaluated_rate_pct"] == "3.5500"
    assert position["evaluation_basis"] == "proposal"
    assert position["pricing_peer_count"] == 2
    assert position["peer_median_rate_pct"] == "3.5000"
    assert position["peer_gap_bp"] == "5.00"
    assert position["peer_rank_best"] == 2
    assert position["peer_rank_worst"] == 2
    assert position["higher_rate_peer_count"] == 1
    assert position["funding_analysis_month"] == "2026-03"
    assert position["funding_join_count"] == 1
    assert position["funding_unjoined_count"] == 1
    assert position["funding_join_ratio"] == "0.5"
    assert position["higher_rate_peer_funding_known_count"] == 1
    assert position["higher_rate_peer_funding_total_krw"] == "60000000"

    peers = {row["institution_id"]: row for row in payload["peers"]}
    assert peers["high"]["institution"] == "상위은행"
    assert peers["high"]["funding_status"] == "known"
    assert peers["high"]["funding_balance_million_krw"] == "60"
    assert peers["high"]["gap_vs_own_bp"] == "5.00"
    assert peers["low"]["funding_status"] == "unavailable"
    assert peers["low"]["funding_balance_million_krw"] is None
    assert peers["low"]["gap_vs_own_bp"] == "-15.00"

    assert payload["scope"]["include_special_offer_in_core"] is False
    assert payload["scope"]["special_offer_radar_included"] is False
    assert payload["special_offer_radar"] == []

    cost = payload["factual_cost"]
    assert cost["standardized_notional_krw"] == "10000000000"
    assert cost["standardized_surface_interest_delta_krw"] == "5000000.0000"


def test_missing_funding_never_removes_pricing_peer() -> None:
    payload = _build()

    assert payload["status"] == "ready"
    assert len(payload["peers"]) == 2
    assert payload["pricing_peer_position"]["funding_join_count"] == 1
    assert payload["pricing_peer_position"]["funding_unjoined_count"] == 1
    assert payload["factual_cost"]["evaluation_basis"] == "current_baseline"
    assert payload["factual_cost"]["standardized_surface_interest_delta_krw"] == "0.0000"


def test_higher_peer_without_any_funding_is_unknown_not_zero() -> None:
    payload = build_relative_pricing_strategy_payload(
        [
            _rate("our", "p-our", "3.50"),
            _rate("high", "p-high", "3.60"),
        ],
        anchor_institution_id="our",
        sector="savings_bank",
        product_type="term_deposit",
        term_months=12,
        availability_match_key="nationwide",
        join_channel="online",
        funding_rows=[],
        matrix_representatives=_matrix(our="3.50", high="3.60"),
        retreating_sources=set(),
    )

    position = payload["pricing_peer_position"]
    assert payload["status"] == "ready"
    assert position["higher_rate_peer_count"] == 1
    assert position["higher_rate_peer_funding_known_count"] == 0
    assert position["higher_rate_peer_funding_total_krw"] is None
    assert position["funding_analysis_month"] is None


def test_no_higher_peers_has_measured_zero_higher_peer_funding_total() -> None:
    payload = build_relative_pricing_strategy_payload(
        [
            _rate("our", "p-our", "3.60"),
            _rate("low", "p-low", "3.40"),
        ],
        anchor_institution_id="our",
        sector="savings_bank",
        product_type="term_deposit",
        term_months=12,
        availability_match_key="nationwide",
        funding_rows=[],
        matrix_representatives=_matrix(our="3.60", low="3.40"),
        retreating_sources=set(),
    )

    position = payload["pricing_peer_position"]
    assert position["higher_rate_peer_count"] == 0
    assert position["higher_rate_peer_funding_total_krw"] == "0"


def test_payload_contains_no_r1_forbidden_prediction_or_target_fields() -> None:
    payload = _build(proposal_rate_pct="3.60")

    keys: set[str] = set()

    def walk(value) -> None:
        if isinstance(value, dict):
            keys.update(value)
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(payload)
    assert keys.isdisjoint(
        {
            "predicted_total",
            "predicted_new_money",
            "predicted_rollover",
            "predicted_inflow",
            "target_balance",
            "target_net_inflow",
            "target_horizon",
            "recommended_rate",
            "required_rate",
        }
    )


def test_unknown_match_key_fails_closed_instead_of_inferencing_from_scope() -> None:
    with pytest.raises(ValueError, match="availability_match_key"):
        build_relative_pricing_strategy_payload(
            [_rate("our", "p", "3.50", match_key="미상")],
            anchor_institution_id="our",
            sector="savings_bank",
            product_type="term_deposit",
            term_months=12,
            availability_match_key="미상",
            matrix_representative_rate_pct="3.50",
            matrix_representative_policy_id="institution_product_representative_max",
            retreating_sources=set(),
        )


def test_anchor_outside_pricing_population_returns_insufficient_data() -> None:
    payload = build_relative_pricing_strategy_payload(
        [_rate("other", "p", "3.50")],
        anchor_institution_id="our",
        sector="savings_bank",
        product_type="term_deposit",
        term_months=12,
        availability_match_key="nationwide",
        matrix_representative_rate_pct="3.50",
        matrix_representative_policy_id="institution_product_representative_max",
        retreating_sources=set(),
    )

    assert payload["status"] == "insufficient_data"
    assert payload["reason"] == "anchor_not_in_evidence_backed_pricing_population"
    assert payload["peers"] == []


def test_duplicate_funding_enrichment_fails_closed() -> None:
    with pytest.raises(ValueError, match="duplicate funding row"):
        build_relative_pricing_strategy_payload(
            [_rate("our", "p-our", "3.50"), _rate("peer", "p-peer", "3.60")],
            anchor_institution_id="our",
            sector="savings_bank",
            product_type="term_deposit",
            term_months=12,
            availability_match_key="nationwide",
            funding_rows=[_funding("peer", "10"), _funding("peer", "20")],
            matrix_representatives=_matrix(our="3.50", peer="3.60"),
            retreating_sources=set(),
        )


def test_mixed_funding_vintages_fail_closed_before_aggregation() -> None:
    with pytest.raises(ValueError, match="mixed funding analysis months"):
        build_relative_pricing_strategy_payload(
            [_rate("our", "p-our", "3.50"), _rate("peer", "p-peer", "3.60")],
            anchor_institution_id="our",
            sector="savings_bank",
            product_type="term_deposit",
            term_months=12,
            availability_match_key="nationwide",
            funding_rows=[
                _funding("our", "10", analysis_month="2026-03"),
                _funding("peer", "20", analysis_month="2025-12"),
            ],
            matrix_representatives=_matrix(our="3.50", peer="3.60"),
            retreating_sources=set(),
        )


def test_matrix_representative_is_required_for_ready_payload() -> None:
    payload = build_relative_pricing_strategy_payload(
        [_rate("our", "p-our", "3.50"), _rate("peer", "p-peer", "3.60")],
        anchor_institution_id="our",
        sector="savings_bank",
        product_type="term_deposit",
        term_months=12,
        availability_match_key="nationwide",
        retreating_sources=set(),
    )

    assert payload["status"] == "insufficient_data"
    assert payload["reason"] == "matrix_representative_rate_unresolved"
    reconciliation = payload["representative_rate_reconciliation"]
    assert reconciliation["status"] == "unresolved"
    assert reconciliation["pricing_rate_pct"] == "3.5000"


def test_unexplained_matrix_pricing_rate_mismatch_fails_closed() -> None:
    payload = build_relative_pricing_strategy_payload(
        [_rate("our", "p-our", "3.50"), _rate("peer", "p-peer", "3.60")],
        anchor_institution_id="our",
        sector="savings_bank",
        product_type="term_deposit",
        term_months=12,
        availability_match_key="nationwide",
        matrix_representatives=_matrix(our="3.45", peer="3.60"),
        retreating_sources=set(),
    )

    assert payload["status"] == "insufficient_data"
    assert payload["reason"] == "representative_rate_policy_mismatch_unexplained"
    reconciliation = payload["representative_rate_reconciliation"]
    assert reconciliation["status"] == "unexplained"
    assert reconciliation["pricing_rate_pct"] == "3.5000"
    assert reconciliation["matrix_rate_pct"] == "3.4500"
    assert reconciliation["gap_bp"] == "5.00"


def test_explained_matrix_pricing_rate_mismatch_preserves_both_policies() -> None:
    payload = build_relative_pricing_strategy_payload(
        [_rate("our", "p-our", "3.50"), _rate("peer", "p-peer", "3.60")],
        anchor_institution_id="our",
        sector="savings_bank",
        product_type="term_deposit",
        term_months=12,
        availability_match_key="nationwide",
        matrix_representatives=_matrix(our="3.45", peer="3.60"),
        representative_rate_difference_reason="pricing scope excludes unmatched channel",
        retreating_sources=set(),
    )

    assert payload["status"] == "ready"
    reconciliation = payload["representative_rate_reconciliation"]
    assert reconciliation["status"] == "explained"
    assert reconciliation["pricing_policy_id"] == "relative-pricing-institution-rate"
    assert reconciliation["matrix_policy_id"] == "institution_product_representative_max"
    assert reconciliation["gap_bp"] == "5.00"
    assert reconciliation["difference_reason"] == (
        "pricing scope excludes unmatched channel"
    )


def test_unapproved_special_offer_policy_fails_closed() -> None:
    with pytest.raises(ValueError, match="special-offer core/radar policy is not approved"):
        build_relative_pricing_strategy_payload(
            [
                _rate("our", "p-our", "3.50"),
                _rate("peer", "p-peer-core", "3.60"),
                _rate("peer", "p-peer-special", "4.50", special_offer=True),
            ],
            anchor_institution_id="our",
            sector="savings_bank",
            product_type="term_deposit",
            term_months=12,
            availability_match_key="nationwide",
            include_special_offer=True,
            retreating_sources=set(),
        )


def test_matrix_policy_must_be_canonical_for_every_displayed_institution() -> None:
    matrix = _matrix(our="3.50", peer="3.60")
    matrix["peer"]["policy_id"] = "typo-policy"
    payload = build_relative_pricing_strategy_payload(
        [_rate("our", "p-our", "3.50"), _rate("peer", "p-peer", "3.60")],
        anchor_institution_id="our",
        sector="savings_bank",
        product_type="term_deposit",
        term_months=12,
        availability_match_key="nationwide",
        matrix_representatives=matrix,
        retreating_sources=set(),
    )
    assert payload["status"] == "insufficient_data"
    assert payload["reason"] == "matrix_representative_policy_noncanonical"
    assert payload["representative_rate_reconciliations"]["peer"]["status"] == "policy_mismatch"


def test_matrix_dates_must_match_pricing_observation_dates() -> None:
    matrix = _matrix(our="3.50", peer="3.60")
    matrix["peer"]["rate_as_of"] = "2026-08-31"
    payload = build_relative_pricing_strategy_payload(
        [_rate("our", "p-our", "3.50"), _rate("peer", "p-peer", "3.60")],
        anchor_institution_id="our",
        sector="savings_bank",
        product_type="term_deposit",
        term_months=12,
        availability_match_key="nationwide",
        matrix_representatives=matrix,
        retreating_sources=set(),
    )
    assert payload["status"] == "insufficient_data"
    assert payload["reason"] == "matrix_representative_rate_temporal_mismatch"


def test_missing_peer_matrix_evidence_fails_closed() -> None:
    payload = build_relative_pricing_strategy_payload(
        [_rate("our", "p-our", "3.50"), _rate("peer", "p-peer", "3.60")],
        anchor_institution_id="our",
        sector="savings_bank",
        product_type="term_deposit",
        term_months=12,
        availability_match_key="nationwide",
        matrix_representatives=_matrix(our="3.50"),
        retreating_sources=set(),
    )
    assert payload["status"] == "insufficient_data"
    assert payload["reason"] == "matrix_representative_rate_unresolved"
    assert payload["representative_rate_reconciliations"]["peer"]["status"] == "unresolved"


def test_invalid_matrix_rate_fails_closed_before_gap_calculation() -> None:
    matrix = _matrix(our="3.50", peer="3.60")
    matrix["peer"]["rate_pct"] = "-1"
    payload = build_relative_pricing_strategy_payload(
        [_rate("our", "p-our", "3.50"), _rate("peer", "p-peer", "3.60")],
        anchor_institution_id="our",
        sector="savings_bank",
        product_type="term_deposit",
        term_months=12,
        availability_match_key="nationwide",
        matrix_representatives=matrix,
        retreating_sources=set(),
    )
    assert payload["status"] == "insufficient_data"
    assert payload["reason"] == "matrix_representative_rate_invalid"


def test_unavailable_payload_keeps_policy_versions_visible() -> None:
    payload = build_relative_pricing_unavailable_payload(
        reason="availability_match_key_unresolved",
        as_of="2026-09-01",
    )

    assert payload["status"] == "insufficient_data"
    assert payload["pricing_peer_position"] is None
    assert payload["representative_rate_reconciliation"] is None
    assert payload["representative_rate_reconciliations"] == {}
    assert payload["special_offer_radar"] == []
    assert payload["factual_cost"] is None
    assert payload["policies"]["contract_version"] == "3"
    assert payload["policies"]["pricing_peer"]["policy_version"] == "1"
    assert payload["policies"]["surface_cost"]["contract_version"] == "1"
