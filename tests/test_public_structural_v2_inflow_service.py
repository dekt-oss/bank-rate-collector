from __future__ import annotations

import inspect

import pytest

from rate_monitor.services.inflow_prediction_service import predict_range
from rate_monitor.services.public_structural_v2_inflow_service import (
    predict_structural_v2_range,
    public_structural_v2_config,
)


def _predict(**overrides):
    inputs = {
        "baseline_new_money": 100.0,
        "maturity_amount": 200.0,
        "current_rollover_rate_pct": 60.0,
        "current_own_rate": 3.50,
        "proposed_rate": 3.50,
        "term_months": 12,
    }
    inputs.update(overrides)
    return predict_structural_v2_range(**inputs)


def test_public_v2_config_keeps_uncalibrated_and_market_invariance_explicit() -> None:
    config = public_structural_v2_config()

    assert config["version"] == "inflow-structural-v2-public"
    assert config["calibration_status"] == "uncalibrated"
    assert config["coefficient_provenance"] == "uncalibrated_stress_assumptions"
    assert config["rollover_transform"] == "logit_interior_exact_boundaries"
    assert config["market_position_effect"] == "not_applied_to_amount_formula"


def test_amount_engine_has_no_market_position_input_by_contract() -> None:
    parameters = inspect.signature(predict_structural_v2_range).parameters

    assert "market_top10_rate" not in parameters
    assert "market_rank" not in parameters
    assert "market_crowding" not in parameters


@pytest.mark.parametrize("rollover_rate", [0.0, 100.0])
@pytest.mark.parametrize("proposed_rate", [3.4999, 3.50, 3.5001, 3.60])
def test_exact_rollover_boundaries_are_continuous_absorbing_limits(
    rollover_rate: float,
    proposed_rate: float,
) -> None:
    result = _predict(
        current_rollover_rate_pct=rollover_rate,
        proposed_rate=proposed_rate,
    )

    for scenario in result["scenarios"].values():
        assert scenario["predicted_rollover_rate_pct"] == rollover_rate
        assert scenario["predicted_rollover"] == pytest.approx(
            200.0 * rollover_rate / 100.0,
            abs=1e-4,
        )


def test_tiny_raise_at_100pct_no_longer_creates_negative_boundary_jump() -> None:
    result = _predict(current_rollover_rate_pct=100.0, proposed_rate=3.5001)["base"]

    assert result["predicted_rollover_rate_pct"] == 100.0
    assert result["predicted_total"] > result["baseline_total"]
    assert result["incremental_total"] > 0


def test_interior_probability_keeps_v1_math_when_guardrail_does_not_bind() -> None:
    v1 = predict_range(
        baseline_new_money=100.0,
        maturity_amount=200.0,
        current_rollover_rate_pct=60.0,
        current_own_rate=3.50,
        proposed_rate=3.60,
        market_top10_rate=3.60,
        term_months=12,
    )
    v2 = _predict(proposed_rate=3.60)

    for key in ("low", "base", "high"):
        assert v2["scenarios"][key]["predicted_new_money"] == v1["scenarios"][key][
            "predicted_new_money"
        ]
        assert v2["scenarios"][key]["predicted_rollover_rate_pct"] == v1[
            "scenarios"
        ][key]["predicted_rollover_rate_pct"]
        assert v2["scenarios"][key]["predicted_total"] == v1["scenarios"][key][
            "predicted_total"
        ]


def test_rate_cut_uses_actual_min_max_instead_of_scenario_label_order() -> None:
    result = _predict(proposed_rate=3.40)
    totals = {
        key: row["predicted_total"] for key, row in result["scenarios"].items()
    }

    assert totals["low"] > totals["base"] > totals["high"]
    assert result["predicted_total_range"]["min"] == totals["high"]
    assert result["predicted_total_range"]["max"] == totals["low"]


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"baseline_new_money": -1}, "baseline_new_money"),
        ({"maturity_amount": -1}, "maturity_amount"),
        ({"current_rollover_rate_pct": 100.1}, "current_rollover_rate_pct"),
        ({"term_months": 0}, "term_months"),
        ({"proposed_rate": float("nan")}, "proposed_rate"),
    ],
)
def test_invalid_inputs_fail_closed(overrides, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        _predict(**overrides)
