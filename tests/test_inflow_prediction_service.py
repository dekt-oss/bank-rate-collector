"""수신금액 구조 예측엔진의 단위·경계·방향성 계약."""

import math

import pytest

from rate_monitor.services.inflow_prediction_service import (
    MAX_ABS_NEW_MONEY_LOG_EFFECT,
    SCENARIOS,
    predict_range,
    predict_scenario,
    public_model_config,
)

BASE = next(scenario for scenario in SCENARIOS if scenario.key == "base")
HIGH = next(scenario for scenario in SCENARIOS if scenario.key == "high")


def _predict(**overrides):
    inputs = {
        "baseline_new_money": 100.0,
        "maturity_amount": 200.0,
        "current_rollover_rate_pct": 60.0,
        "current_own_rate": 3.50,
        "proposed_rate": 3.50,
        "market_top10_rate": 3.60,
        "term_months": 12,
        "scenario": BASE,
    }
    inputs.update(overrides)
    return predict_scenario(**inputs)


def test_public_config_marks_coefficients_as_uncalibrated_stress_assumptions() -> None:
    config = public_model_config()

    assert config["version"] == "inflow-structural-v1"
    assert config["calibration_status"] == "uncalibrated"
    assert config["coefficient_provenance"] == "uncalibrated_stress_assumptions"
    assert config["rate_step_percentage_point"] == 0.10
    assert config["amount_unit"] == "KRW_100M"
    assert [scenario["key"] for scenario in config["scenarios"]] == [
        "low",
        "base",
        "high",
    ]


def test_zero_rate_change_preserves_baseline_new_money_and_rollover() -> None:
    result = _predict()

    assert result["relative_change_pp"] == 0
    assert result["rate_steps_10bp"] == 0
    assert result["predicted_new_money"] == 100.0
    assert result["predicted_rollover_rate_pct"] == 60.0
    assert result["predicted_rollover"] == 120.0
    assert result["baseline_total"] == 220.0
    assert result["predicted_total"] == 220.0
    assert result["incremental_total"] == 0
    assert result["surface_interest_delta"] == 0


def test_plus_10bp_raises_new_money_and_rollover_in_base_scenario() -> None:
    result = _predict(proposed_rate=3.60)

    assert result["rate_steps_10bp"] == pytest.approx(1.0)
    assert result["new_money_multiplier"] == pytest.approx(math.exp(0.05), abs=1e-6)
    assert result["predicted_new_money"] > 100.0
    assert result["predicted_rollover_rate_pct"] > 60.0
    assert result["predicted_total"] > result["baseline_total"]
    assert result["surface_interest_delta"] > 0


def test_rate_cut_moves_new_money_and_rollover_in_opposite_direction() -> None:
    result = _predict(proposed_rate=3.30)

    assert result["rate_steps_10bp"] == pytest.approx(-2.0)
    assert result["predicted_new_money"] < 100.0
    assert result["predicted_rollover_rate_pct"] < 60.0
    assert result["predicted_total"] < result["baseline_total"]
    assert result["surface_interest_delta"] < 0


def test_top10_gap_is_audited_without_double_counting_static_market_reference() -> None:
    result = _predict(proposed_rate=3.70, market_top10_rate=3.60)

    assert result["current_top10_gap_pp"] == pytest.approx(-0.10)
    assert result["proposed_top10_gap_pp"] == pytest.approx(0.10)
    assert result["relative_change_pp"] == pytest.approx(0.20)
    assert result["rate_steps_10bp"] == pytest.approx(2.0)


def test_three_scenarios_form_a_range_and_base_result_is_preserved() -> None:
    result = predict_range(
        baseline_new_money=100.0,
        maturity_amount=200.0,
        current_rollover_rate_pct=60.0,
        current_own_rate=3.50,
        proposed_rate=3.70,
        market_top10_rate=3.60,
        term_months=12,
    )

    totals = [item["predicted_total"] for item in result["scenarios"].values()]
    assert result["predicted_total_range"]["min"] == min(totals)
    assert result["predicted_total_range"]["max"] == max(totals)
    assert result["base"] == result["scenarios"]["base"]
    assert totals[0] < totals[1] < totals[2]


def test_new_money_log_effect_has_an_explicit_guardrail() -> None:
    result = _predict(proposed_rate=10.0, scenario=HIGH)

    assert result["raw_new_money_log_effect"] > MAX_ABS_NEW_MONEY_LOG_EFFECT
    assert result["applied_new_money_log_effect"] == MAX_ABS_NEW_MONEY_LOG_EFFECT
    assert result["new_money_multiplier"] == pytest.approx(
        math.exp(MAX_ABS_NEW_MONEY_LOG_EFFECT), abs=1e-6
    )
    assert 0 <= result["predicted_rollover_rate_pct"] <= 100


def test_surface_interest_delta_respects_term_month_unit() -> None:
    twelve = _predict(maturity_amount=0, proposed_rate=3.60, term_months=12)
    six = _predict(maturity_amount=0, proposed_rate=3.60, term_months=6)

    assert six["surface_interest_delta"] == pytest.approx(
        twelve["surface_interest_delta"] / 2,
        abs=1e-4,
    )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"baseline_new_money": -1}, "baseline_new_money"),
        ({"maturity_amount": -1}, "maturity_amount"),
        ({"current_rollover_rate_pct": 101}, "current_rollover_rate_pct"),
        ({"current_rollover_rate_pct": -0.1}, "current_rollover_rate_pct"),
        ({"term_months": 0}, "term_months"),
        ({"proposed_rate": float("nan")}, "proposed_rate"),
    ],
)
def test_invalid_financial_inputs_fail_closed(overrides, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        _predict(**overrides)
