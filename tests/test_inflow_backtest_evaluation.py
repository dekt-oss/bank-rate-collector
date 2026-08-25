from __future__ import annotations

import pytest

from rate_monitor.services.inflow_backtest_evaluation import (
    score_backtest_records,
    validate_backtest_record,
)


def _rows() -> list[dict[str, float | bool]]:
    return [
        {
            "actual_new_money": 100.0,
            "predicted_new_money": 105.0,
            "actual_rollover": 60.0,
            "predicted_rollover": 62.0,
            "maturity_amount": 100.0,
            "pricing_event": True,
            "baseline_total": 150.0,
        },
        {
            "actual_new_money": 120.0,
            "predicted_new_money": 114.0,
            "actual_rollover": 80.0,
            "predicted_rollover": 76.0,
            "maturity_amount": 120.0,
            "pricing_event": True,
            "baseline_total": 210.0,
        },
    ]


def test_scoring_uses_one_deterministic_metric_definition() -> None:
    report = score_backtest_records(_rows())

    assert report["status"] == "valid"
    assert report["row_count"] == 2
    assert report["pricing_event_count"] == 2
    metrics = report["metrics"]
    assert metrics["total_wape"] == pytest.approx(17 / 360)
    assert metrics["new_money_wape"] == pytest.approx(11 / 220)
    assert metrics["rollover_rate_mae_pp"] == pytest.approx(6 / 220 * 100)
    assert metrics["bias_ratio"] == pytest.approx(-3 / 360)
    assert metrics["event_direction_accuracy"] == pytest.approx(1.0)


def test_pricing_event_requires_pre_event_baseline() -> None:
    row = _rows()[0]
    row.pop("baseline_total")

    with pytest.raises(ValueError, match="required_for_pricing_event"):
        validate_backtest_record(row)


def test_rollover_cannot_exceed_maturity() -> None:
    row = _rows()[0]
    row["predicted_rollover"] = 101.0

    with pytest.raises(ValueError, match="exceeds_maturity"):
        validate_backtest_record(row)


def test_negative_amounts_fail_closed() -> None:
    row = _rows()[0]
    row["actual_new_money"] = -1.0

    report = score_backtest_records([row])

    assert report["status"] == "invalid"
    assert any("must_be_non_negative" in error for error in report["errors"])


def test_unknown_fields_fail_closed_instead_of_being_silently_ignored() -> None:
    row = _rows()[0]
    row["private_feature_importance"] = 0.7

    report = score_backtest_records([row])

    assert report["status"] == "invalid"
    assert any("unknown_fields:private_feature_importance" in error for error in report["errors"])


def test_direction_metric_detects_wrong_sign_even_if_amount_error_is_small() -> None:
    rows = _rows()
    rows[0]["predicted_new_money"] = 88.0
    rows[0]["predicted_rollover"] = 61.0

    report = score_backtest_records(rows)

    assert report["status"] == "valid"
    assert report["metrics"]["event_direction_accuracy"] == pytest.approx(0.5)


def test_no_pricing_event_rows_cannot_claim_direction_accuracy() -> None:
    rows = _rows()
    for row in rows:
        row["pricing_event"] = False
        row.pop("baseline_total")

    report = score_backtest_records(rows)

    assert report["status"] == "invalid"
    assert "pricing_event_rows_required_for_direction_metric" in report["errors"]


def test_zero_denominators_fail_closed_instead_of_returning_fake_zero_error() -> None:
    rows = [
        {
            "actual_new_money": 0.0,
            "predicted_new_money": 0.0,
            "actual_rollover": 0.0,
            "predicted_rollover": 0.0,
            "maturity_amount": 0.0,
            "pricing_event": True,
            "baseline_total": 0.0,
        }
    ]

    report = score_backtest_records(rows)

    assert report["status"] == "invalid"
    assert "actual_total_sum_must_be_positive" in report["errors"]
    assert "actual_new_money_sum_must_be_positive" in report["errors"]
    assert "maturity_sum_must_be_positive" in report["errors"]
