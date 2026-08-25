from __future__ import annotations

from rate_monitor.services.inflow_asof_feature_contract import validate_as_of_feature_row


def _values() -> dict[str, float | int]:
    return {
        "own_rate_pct": 3.5,
        "rate_change_bp": 5.0,
        "term_months": 12,
        "market_gap_bp": -10.0,
        "lag_1_new_money_amount": 100.0,
        "maturity_amount": 80.0,
    }


def _as_of() -> dict[str, str]:
    return {key: "2026-07-31" for key in _values()}


def test_all_features_available_at_origin_pass() -> None:
    report = validate_as_of_feature_row(
        forecast_origin="2026-07-31",
        target_date="2026-08-31",
        feature_values=_values(),
        feature_as_of_dates=_as_of(),
    )

    assert report["status"] == "valid"
    assert report["leakage_detected"] is False
    assert report["database_written"] is False


def test_future_value_hidden_behind_lag_name_is_rejected() -> None:
    as_of = _as_of()
    as_of["lag_1_new_money_amount"] = "2026-08-31"

    report = validate_as_of_feature_row(
        forecast_origin="2026-07-31",
        target_date="2026-08-31",
        feature_values=_values(),
        feature_as_of_dates=as_of,
    )

    assert report["status"] == "invalid"
    assert report["leakage_detected"] is True
    assert any(
        error.startswith("feature_not_available_at_forecast_origin:lag_1_new_money_amount:")
        for error in report["errors"]
    )


def test_every_feature_requires_provenance_date() -> None:
    as_of = _as_of()
    as_of.pop("market_gap_bp")

    report = validate_as_of_feature_row(
        forecast_origin="2026-07-31",
        target_date="2026-08-31",
        feature_values=_values(),
        feature_as_of_dates=as_of,
    )

    assert report["status"] == "invalid"
    assert "missing_feature_as_of_dates:market_gap_bp" in report["errors"]


def test_orphan_as_of_metadata_is_rejected() -> None:
    as_of = _as_of()
    as_of["mystery_feature"] = "2026-07-31"

    report = validate_as_of_feature_row(
        forecast_origin="2026-07-31",
        target_date="2026-08-31",
        feature_values=_values(),
        feature_as_of_dates=as_of,
    )

    assert report["status"] == "invalid"
    assert "orphan_feature_as_of_dates:mystery_feature" in report["errors"]


def test_target_must_be_strictly_after_forecast_origin() -> None:
    report = validate_as_of_feature_row(
        forecast_origin="2026-08-01",
        target_date="2026-08-01",
        feature_values=_values(),
        feature_as_of_dates=_as_of(),
    )

    assert report["status"] == "invalid"
    assert "target_date_must_be_after_forecast_origin" in report["errors"]


def test_month_strings_are_normalized_to_first_day() -> None:
    values = _values()
    as_of = {key: "2026-07" for key in values}

    report = validate_as_of_feature_row(
        forecast_origin="2026-07",
        target_date="2026-08",
        feature_values=values,
        feature_as_of_dates=as_of,
    )

    assert report["status"] == "valid"
    assert report["forecast_origin"] == "2026-07-01"
    assert report["target_date"] == "2026-08-01"
