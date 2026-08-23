from __future__ import annotations

import copy

import pytest

from rate_monitor.services.public_structural_v2_decision_contract import (
    build_public_structural_v2_forecast,
)
from rate_monitor.services.public_structural_v2_forecast_provider import (
    ForecastProviderUnavailable,
    PublicForecastRequest,
    public_structural_forecast_provider,
    resolve_public_forecast,
)


def _request() -> PublicForecastRequest:
    return PublicForecastRequest(
        generated_at="2026-08-23T09:00:00+09:00",
        candidate_rates=(3.50, 3.55),
        baseline_new_money=100.0,
        maturity_amount=200.0,
        current_rollover_rate_pct=60.0,
        current_own_rate=3.50,
        term_months=12,
    )


def _sanitized_payload() -> dict:
    return {
        "version": "inflow-public-forecast-v1",
        "generated_at": "2026-08-23T09:00:01+09:00",
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
                "predicted_total_lower": 210.0,
                "predicted_total_upper": 230.0,
            },
            {
                "rate_pct": 3.55,
                "predicted_new_money": 101.0,
                "predicted_rollover": 121.0,
                "predicted_total": 222.0,
                "incremental_total": 2.0,
                "surface_interest_delta": 0.1,
                "predicted_total_lower": 211.0,
                "predicted_total_upper": 233.0,
            },
        ],
    }


def test_structural_provider_keeps_existing_public_forecast_shape() -> None:
    request = _request()
    actual = resolve_public_forecast(request=request)
    direct = build_public_structural_v2_forecast(
        generated_at=request.generated_at,
        candidate_rates=list(request.candidate_rates),
        baseline_new_money=request.baseline_new_money,
        maturity_amount=request.maturity_amount,
        current_rollover_rate_pct=request.current_rollover_rate_pct,
        current_own_rate=request.current_own_rate,
        term_months=request.term_months,
    )

    assert actual == direct
    assert public_structural_forecast_provider(request) == direct


def test_sanitized_arbitrary_provider_uses_same_public_slot_without_identity() -> None:
    payload = _sanitized_payload()

    actual = resolve_public_forecast(request=_request(), provider=lambda request: payload)

    assert actual == payload
    serialized = repr(actual).lower()
    for forbidden in (
        "provider",
        "private_model",
        "training_metric",
        "feature_importance",
        "source_file",
        "sample_size",
    ):
        assert forbidden not in serialized


def test_provider_unknown_top_level_private_metadata_fails_closed() -> None:
    payload = _sanitized_payload()
    payload["private_model"] = "confidential-v9"

    with pytest.raises(ValueError, match="unknown_fields:private_model"):
        resolve_public_forecast(request=_request(), provider=lambda request: payload)


def test_provider_unknown_scenario_private_metadata_fails_closed() -> None:
    payload = _sanitized_payload()
    payload["scenarios"][0]["training_metric"] = 0.91

    with pytest.raises(ValueError, match="unknown_fields:training_metric"):
        resolve_public_forecast(request=_request(), provider=lambda request: payload)


@pytest.mark.parametrize(
    "mutator",
    [
        lambda payload: payload["scenarios"].pop(),
        lambda payload: payload["scenarios"].append(
            {
                **payload["scenarios"][-1],
                "rate_pct": 3.60,
            }
        ),
        lambda payload: payload["scenarios"].__setitem__(
            1,
            {**payload["scenarios"][1], "rate_pct": 3.50},
        ),
    ],
)
def test_provider_rate_axis_drift_fails_closed(mutator) -> None:
    payload = copy.deepcopy(_sanitized_payload())
    mutator(payload)

    with pytest.raises(ValueError, match="scenario_rate"):
        resolve_public_forecast(request=_request(), provider=lambda request: payload)


def test_explicit_provider_unavailable_returns_strict_public_payload() -> None:
    def unavailable(request: PublicForecastRequest) -> dict:
        raise ForecastProviderUnavailable("maintenance")

    actual = resolve_public_forecast(request=_request(), provider=unavailable)

    assert actual == {
        "version": "inflow-public-forecast-v1",
        "generated_at": "2026-08-23T09:00:00+09:00",
        "status": "unavailable",
        "amount_unit": "KRW_100M",
        "rate_unit": "percent",
        "scenarios": [],
    }


def test_arbitrary_provider_exception_is_not_hidden_as_unavailable() -> None:
    def broken(request: PublicForecastRequest) -> dict:
        raise RuntimeError("provider bug")

    with pytest.raises(RuntimeError, match="provider bug"):
        resolve_public_forecast(request=_request(), provider=broken)
