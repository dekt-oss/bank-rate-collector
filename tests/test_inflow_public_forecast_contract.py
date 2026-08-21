from __future__ import annotations

from copy import deepcopy

import pytest

from rate_monitor.services.inflow_public_forecast_contract import (
    PUBLIC_FORECAST_CONTRACT_VERSION,
    public_forecast_allowlist,
    validate_public_forecast_payload,
)


def _ready_payload() -> dict[str, object]:
    return {
        "version": PUBLIC_FORECAST_CONTRACT_VERSION,
        "generated_at": "2026-08-21T23:50:00+09:00",
        "status": "ready",
        "amount_unit": "KRW_100M",
        "rate_unit": "percent",
        "scenarios": [
            {
                "rate_pct": 3.50,
                "predicted_new_money": 100.0,
                "predicted_rollover": 120.0,
                "predicted_total": 220.0,
                "incremental_total": 0.0,
                "surface_interest_delta": 0.0,
                "predicted_total_lower": 205.0,
                "predicted_total_upper": 235.0,
            },
            {
                "rate_pct": 3.60,
                "predicted_new_money": 106.0,
                "predicted_rollover": 124.0,
                "predicted_total": 230.0,
                "incremental_total": 10.0,
                "surface_interest_delta": 1.2,
                "predicted_total_lower": 214.0,
                "predicted_total_upper": 247.0,
            },
        ],
    }


def test_ready_payload_accepts_only_sanitized_prediction_results() -> None:
    payload = _ready_payload()

    assert validate_public_forecast_payload(payload) is payload
    allowlist = public_forecast_allowlist()
    assert "calibration_status" not in allowlist["top_level"]
    assert "coefficient_provenance" not in allowlist["top_level"]
    assert "beta" not in allowlist["scenario"]
    assert "gamma" not in allowlist["scenario"]


@pytest.mark.parametrize(
    "private_field",
    [
        "calibration_status",
        "coefficient_provenance",
        "source_file",
        "feature_importance",
        "training_metrics",
        "model_id",
        "data_fingerprint",
    ],
)
def test_private_or_training_metadata_is_rejected_at_top_level(private_field: str) -> None:
    payload = _ready_payload()
    payload[private_field] = "must-not-leave-private-runtime"

    with pytest.raises(ValueError, match="public_forecast:unknown_fields"):
        validate_public_forecast_payload(payload)


@pytest.mark.parametrize("private_field", ["beta", "gamma", "provenance", "raw_features"])
def test_private_model_detail_is_rejected_inside_scenario(private_field: str) -> None:
    payload = _ready_payload()
    scenario = payload["scenarios"][0]
    assert isinstance(scenario, dict)
    scenario[private_field] = 0.05

    with pytest.raises(ValueError, match="scenario_0:unknown_fields"):
        validate_public_forecast_payload(payload)


def test_unknown_field_is_not_silently_sanitized() -> None:
    payload = _ready_payload()
    payload["harmless_but_unreviewed_field"] = "value"

    with pytest.raises(ValueError, match="harmless_but_unreviewed_field"):
        validate_public_forecast_payload(payload)

    assert "harmless_but_unreviewed_field" in payload


def test_unavailable_payload_must_not_carry_stale_predictions() -> None:
    payload = _ready_payload()
    payload["status"] = "unavailable"

    with pytest.raises(ValueError, match="unavailable_must_not_include_scenarios"):
        validate_public_forecast_payload(payload)

    payload["scenarios"] = []
    assert validate_public_forecast_payload(payload) is payload


def test_ready_payload_requires_at_least_one_scenario() -> None:
    payload = _ready_payload()
    payload["scenarios"] = []

    with pytest.raises(ValueError, match="ready_requires_scenarios"):
        validate_public_forecast_payload(payload)


def test_predicted_total_must_equal_public_components() -> None:
    payload = _ready_payload()
    scenario = payload["scenarios"][0]
    assert isinstance(scenario, dict)
    scenario["predicted_total"] = 221.0

    with pytest.raises(ValueError, match="predicted_total_component_mismatch"):
        validate_public_forecast_payload(payload)


def test_prediction_interval_requires_both_bounds_and_must_cover_total() -> None:
    payload = _ready_payload()
    scenario = payload["scenarios"][0]
    assert isinstance(scenario, dict)
    scenario.pop("predicted_total_upper")

    with pytest.raises(ValueError, match="prediction_interval_requires_both_bounds"):
        validate_public_forecast_payload(payload)

    payload = _ready_payload()
    scenario = payload["scenarios"][0]
    assert isinstance(scenario, dict)
    scenario["predicted_total_lower"] = 225.0

    with pytest.raises(ValueError, match="prediction_interval_does_not_cover_total"):
        validate_public_forecast_payload(payload)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("rate_pct", -0.1, "rate_pct:out_of_range"),
        ("rate_pct", 100.1, "rate_pct:out_of_range"),
        ("predicted_new_money", -1.0, "predicted_new_money:must_be_non_negative"),
        ("predicted_rollover", float("nan"), "predicted_rollover:must_be_finite_number"),
        ("surface_interest_delta", float("inf"), "surface_interest_delta:must_be_finite_number"),
    ],
)
def test_invalid_public_financial_values_fail_closed(field: str, value: float, message: str) -> None:
    payload = _ready_payload()
    scenario = payload["scenarios"][0]
    assert isinstance(scenario, dict)
    scenario[field] = value

    with pytest.raises(ValueError, match=message):
        validate_public_forecast_payload(payload)


def test_missing_required_field_is_rejected() -> None:
    payload = _ready_payload()
    payload.pop("amount_unit")

    with pytest.raises(ValueError, match="public_forecast:missing_fields:amount_unit"):
        validate_public_forecast_payload(payload)


def test_input_payload_is_not_copied_or_mutated_on_success() -> None:
    payload = _ready_payload()
    before = deepcopy(payload)

    result = validate_public_forecast_payload(payload)

    assert result is payload
    assert payload == before
