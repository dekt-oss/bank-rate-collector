from __future__ import annotations

from copy import deepcopy

import pytest

from rate_monitor.services.public_structural_v2_marginal_service import (
    build_fixed_5bp_marginals,
)
from rate_monitor.services.public_structural_v2_surface_service import (
    build_public_structural_v2_surface,
)


def _surface():
    return build_public_structural_v2_surface(
        generated_at="2026-08-22T17:00:00+09:00",
        market_rows=[
            {"product_id": "top", "rate": 3.70},
            {"product_id": "peer", "rate": 3.60},
            {"product_id": "anchor", "rate": 3.50},
            {"product_id": "low", "rate": 3.40},
        ],
        anchor_product_id="anchor",
        current_own_rate=3.50,
        proposal_rate=3.63,
        economics_min_rate=3.40,
        economics_max_rate=3.70,
        baseline_new_money=100.0,
        maturity_amount=200.0,
        current_rollover_rate_pct=60.0,
        term_months=12,
    )


def test_marginal_uses_only_fixed_5bp_economics_grid() -> None:
    surface = _surface()
    result = build_fixed_5bp_marginals(surface)

    assert result["step_bp"] == 5
    assert result["ratio_metric_status"] == "not_exposed_uncalibrated_denominator"
    assert result["annualized_marginal_rate_status"] == "not_exposed"
    assert len(result["marginals"]) == len(surface["candidate_set"]["economics_grid"]) - 1
    assert all(row["step_bp"] == 5 for row in result["marginals"])
    assert all(
        round(row["to_rate_pct"] - row["from_rate_pct"], 4) == 0.05
        for row in result["marginals"]
    )
    assert all(row["from_rate_pct"] != 3.63 for row in result["marginals"])
    assert all(row["to_rate_pct"] != 3.63 for row in result["marginals"])


def test_marginal_delta_is_difference_between_public_forecast_rows() -> None:
    surface = _surface()
    result = build_fixed_5bp_marginals(surface)
    forecast = {row["rate_pct"]: row for row in surface["forecast"]["scenarios"]}

    for row in result["marginals"]:
        before = forecast[row["from_rate_pct"]]
        after = forecast[row["to_rate_pct"]]
        assert row["structural_total_delta"] == round(
            after["predicted_total"] - before["predicted_total"],
            4,
        )
        assert row["surface_interest_delta"] == round(
            after["surface_interest_delta"] - before["surface_interest_delta"],
            4,
        )


def test_unavailable_forecast_propagates_as_empty_marginal_set() -> None:
    surface = deepcopy(_surface())
    surface["forecast"] = {
        "version": "inflow-public-forecast-v1",
        "generated_at": "2026-08-23T09:00:00+09:00",
        "status": "unavailable",
        "amount_unit": "KRW_100M",
        "rate_unit": "percent",
        "scenarios": [],
    }

    result = build_fixed_5bp_marginals(surface)

    assert result["version"] == "public-structural-v2-marginal-v1"
    assert result["marginals"] == []
    assert result["ratio_metric_status"] == "not_exposed_uncalibrated_denominator"


def test_non_5bp_grid_fails_closed_instead_of_annualizing() -> None:
    surface = deepcopy(_surface())
    surface["candidate_set"]["economics_grid"] = [3.50, 3.53, 3.58]

    with pytest.raises(ValueError, match="5bp"):
        build_fixed_5bp_marginals(surface)


def test_marginal_output_has_no_ratio_or_ftp_metric() -> None:
    result = build_fixed_5bp_marginals(_surface())
    serialized = repr(result).lower()

    assert "cost_per" not in serialized
    assert "ftp" not in serialized
    assert "funding_rate" not in serialized
