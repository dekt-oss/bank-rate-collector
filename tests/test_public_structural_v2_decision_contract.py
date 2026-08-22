from __future__ import annotations

import pytest

from rate_monitor.services.inflow_public_forecast_contract import (
    public_forecast_allowlist,
    validate_public_forecast_payload,
)
from rate_monitor.services.public_structural_v2_decision_contract import (
    build_candidate_rate_sets,
    build_public_structural_v2_forecast,
)


def test_candidate_set_keeps_market_markers_out_of_fixed_5bp_grid() -> None:
    result = build_candidate_rate_sets(
        current_rate=3.50,
        proposal_rate=3.63,
        top25_cutoff=3.57,
        top10_cutoff=3.68,
        market_max_rate=3.77,
        economics_min_rate=3.40,
        economics_max_rate=3.70,
    )

    assert result["fixed_step_bp"] == 5
    assert result["economics_grid"] == [3.4, 3.45, 3.5, 3.55, 3.6, 3.65, 3.7]
    assert result["proposal_on_economics_grid"] is False
    assert 3.57 not in result["economics_grid"]
    assert 3.68 not in result["economics_grid"]
    assert 3.77 not in result["economics_grid"]
    markers = {row["rate_pct"]: row["labels"] for row in result["factual_markers"]}
    assert markers[3.57] == ["top25"]
    assert markers[3.68] == ["top10"]
    assert markers[3.77] == ["market_max"]


def test_candidate_markers_group_same_rate_without_duplicate_visual_points() -> None:
    result = build_candidate_rate_sets(
        current_rate=3.50,
        proposal_rate=3.60,
        top25_cutoff=3.55,
        top10_cutoff=3.60,
        market_max_rate=3.70,
        economics_min_rate=3.45,
        economics_max_rate=3.65,
    )

    marker = next(row for row in result["factual_markers"] if row["rate_pct"] == 3.60)
    assert marker["labels"] == ["proposal", "top10"]


def test_public_forecast_contains_only_allowlisted_fields() -> None:
    payload = build_public_structural_v2_forecast(
        generated_at="2026-08-22T17:00:00+09:00",
        candidate_rates=[3.50, 3.55, 3.60],
        baseline_new_money=100.0,
        maturity_amount=200.0,
        current_rollover_rate_pct=60.0,
        current_own_rate=3.50,
        term_months=12,
    )
    allowlist = public_forecast_allowlist()

    assert set(payload) == set(allowlist["top_level"])
    assert len(payload["scenarios"]) == 3
    for row in payload["scenarios"]:
        assert set(row) <= set(allowlist["scenario"])
    assert validate_public_forecast_payload(payload) is payload


def test_public_forecast_never_exposes_structural_coefficients_or_diagnostics() -> None:
    payload = build_public_structural_v2_forecast(
        generated_at="2026-08-22T17:00:00+09:00",
        candidate_rates=[3.60],
        baseline_new_money=100.0,
        maturity_amount=200.0,
        current_rollover_rate_pct=60.0,
        current_own_rate=3.50,
        term_months=12,
    )
    serialized = repr(payload)

    for forbidden in (
        "beta",
        "gamma",
        "log_effect",
        "coefficient",
        "feature",
        "training",
        "model_id",
        "sample_size",
    ):
        assert forbidden not in serialized.lower()


def test_stress_bounds_are_actual_min_max_around_base_on_rate_cut() -> None:
    payload = build_public_structural_v2_forecast(
        generated_at="2026-08-22T17:00:00+09:00",
        candidate_rates=[3.40],
        baseline_new_money=100.0,
        maturity_amount=200.0,
        current_rollover_rate_pct=60.0,
        current_own_rate=3.50,
        term_months=12,
    )
    row = payload["scenarios"][0]

    assert row["predicted_total_lower"] <= row["predicted_total"]
    assert row["predicted_total"] <= row["predicted_total_upper"]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"economics_min_rate": 3.55, "economics_max_rate": 3.70},
        {"economics_min_rate": 3.30, "economics_max_rate": 3.45},
    ],
)
def test_candidate_range_must_contain_current_rate(kwargs) -> None:
    with pytest.raises(ValueError, match="current_rate"):
        build_candidate_rate_sets(
            current_rate=3.50,
            proposal_rate=3.60,
            top25_cutoff=3.55,
            top10_cutoff=3.60,
            market_max_rate=3.70,
            **kwargs,
        )


def test_forecast_rejects_duplicate_candidate_rate_after_normalization() -> None:
    with pytest.raises(ValueError, match="중복"):
        build_public_structural_v2_forecast(
            generated_at="2026-08-22T17:00:00+09:00",
            candidate_rates=[3.50001, 3.50002],
            baseline_new_money=100.0,
            maturity_amount=200.0,
            current_rollover_rate_pct=60.0,
            current_own_rate=3.50,
            term_months=12,
        )
