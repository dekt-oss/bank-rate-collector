from decimal import Decimal

import pytest

from rate_monitor.services.surface_cost_contract import (
    STANDARD_NOTIONAL_KRW,
    standardized_surface_interest_delta,
    surface_interest_delta,
)


def test_standard_100eok_notional_10bp_for_12_months_is_10m_krw() -> None:
    result = standardized_surface_interest_delta(
        current_rate_pct="3.50",
        proposal_rate_pct="3.60",
        term_months=12,
    )

    assert Decimal("10000000000") == STANDARD_NOTIONAL_KRW
    assert result == Decimal("10000000.0000")


def test_term_factor_is_pure_arithmetic() -> None:
    result = surface_interest_delta(
        notional_krw="10000000000",
        current_rate_pct="3.50",
        proposal_rate_pct="3.60",
        term_months=6,
    )

    assert result == Decimal("5000000.0000")


def test_rate_cut_produces_negative_surface_interest_delta() -> None:
    result = surface_interest_delta(
        notional_krw="10000000000",
        current_rate_pct="3.60",
        proposal_rate_pct="3.50",
        term_months=12,
    )

    assert result == Decimal("-10000000.0000")


def test_zero_rate_change_produces_zero_cost_delta() -> None:
    result = surface_interest_delta(
        notional_krw="10000000000",
        current_rate_pct="3.55",
        proposal_rate_pct="3.55",
        term_months=12,
    )

    assert result == Decimal("0.0000")


@pytest.mark.parametrize(
    ("notional", "term_months", "message"),
    [
        ("-1", 12, "non-negative"),
        ("100", 0, "positive"),
    ],
)
def test_invalid_cost_contract_inputs_fail_closed(notional, term_months, message) -> None:
    with pytest.raises(ValueError, match=message):
        surface_interest_delta(
            notional_krw=notional,
            current_rate_pct="3.50",
            proposal_rate_pct="3.60",
            term_months=term_months,
        )


def test_cost_contract_has_no_forecast_or_sensitivity_input() -> None:
    result_a = surface_interest_delta(
        notional_krw="5000000000",
        current_rate_pct="3.40",
        proposal_rate_pct="3.55",
        term_months=12,
    )
    result_b = surface_interest_delta(
        notional_krw="5000000000",
        current_rate_pct="3.40",
        proposal_rate_pct="3.55",
        term_months=12,
    )

    assert result_a == result_b == Decimal("7500000.0000")
