from __future__ import annotations

from datetime import date

from rate_monitor.services.internal_calibration_intake_service import (
    assess_internal_calibration_bundle,
)


def _month_dates(start_year: int, start_month: int, count: int) -> list[str]:
    out: list[str] = []
    year = start_year
    month = start_month
    for _ in range(count):
        out.append(date(year, month, 1).isoformat())
        month += 1
        if month == 13:
            year += 1
            month = 1
    return out


def _bundle(months: int = 37) -> dict[str, list[dict[str, object]]]:
    dates = _month_dates(2023, 1, months)
    pricing_flow = [
        {
            "date": d,
            "product_key": "DEP-12M",
            "term_months": 12,
            "applied_rate_pct": 3.4,
            "new_money_amount": 100.0 + i,
            "new_account_count": 1000 + i,
            "end_balance": 2000.0 + i,
        }
        for i, d in enumerate(dates)
    ]
    maturity_rollover = [
        {
            "date": d,
            "product_key": "DEP-12M",
            "term_months": 12,
            "maturity_amount": 80.0,
            "maturity_account_count": 800,
            "rollover_amount": 50.0,
            "rollover_account_count": 500,
        }
        for d in dates
    ]
    early_withdrawal = [
        {
            "date": d,
            "product_key": "DEP-12M",
            "term_months": 12,
            "early_withdrawal_amount": 5.0,
            "early_withdrawal_account_count": 50,
        }
        for d in dates
    ]
    ftp = [
        {"date": d, "term_months": 12, "ftp_rate_pct": 3.0}
        for d in dates
    ]
    pricing_events = [
        {
            "start_date": dates[0],
            "product_key": "DEP-12M",
            "term_months": 12,
            "rate_before_pct": 3.3,
            "rate_after_pct": 3.4,
            "special_offer_flag": False,
        }
    ]
    return {
        "pricing_flow": pricing_flow,
        "maturity_rollover": maturity_rollover,
        "early_withdrawal": early_withdrawal,
        "pricing_events": pricing_events,
        "ftp": ftp,
    }


def test_recommended_history_bundle_is_ready_without_writing_or_calibrating() -> None:
    report = assess_internal_calibration_bundle(_bundle())

    assert report["status"] == "ready_for_calibration"
    assert report["history_grade"] == "recommended_36m_plus"
    assert report["pricing_observation_dates"] == 37
    assert report["history_months"] == 37
    assert report["history_gate_basis"] == "unique_pricing_observation_months"
    assert report["calibration_allowed"] is True
    assert report["model_coefficients_changed"] is False
    assert report["database_written"] is False


def test_multi_product_rows_on_same_date_are_valid() -> None:
    bundle = _bundle()
    second_product = dict(bundle["pricing_flow"][0])
    second_product["product_key"] = "DEP-12M-B"
    bundle["pricing_flow"].append(second_product)

    report = assess_internal_calibration_bundle(bundle)
    pricing = next(item for item in report["datasets"] if item["dataset"] == "pricing_flow")

    assert report["status"] == "ready_for_calibration"
    assert report["pricing_observation_dates"] == 37
    assert pricing["warnings"] == []


def test_missing_required_dataset_fails_closed() -> None:
    bundle = _bundle()
    bundle.pop("ftp")

    report = assess_internal_calibration_bundle(bundle)

    assert report["status"] == "missing_required_data"
    assert report["missing_required_datasets"] == ["ftp"]
    assert report["calibration_allowed"] is False


def test_short_history_is_not_ready_even_when_fields_are_valid() -> None:
    report = assess_internal_calibration_bundle(_bundle(months=23))

    assert report["status"] == "insufficient_history"
    assert report["history_grade"] == "insufficient"
    assert report["pricing_observation_dates"] == 23
    assert report["history_months"] == 23


def test_exact_24_months_is_minimum_ready() -> None:
    report = assess_internal_calibration_bundle(_bundle(months=24))

    assert report["history_days"] < report["minimum_history_days"]
    assert report["history_months"] == 24
    assert report["status"] == "ready_for_calibration"
    assert report["history_grade"] == "minimum_24m_plus"


def test_exact_36_months_is_recommended() -> None:
    report = assess_internal_calibration_bundle(_bundle(months=36))

    assert report["history_days"] < report["recommended_history_days"]
    assert report["history_months"] == 36
    assert report["status"] == "ready_for_calibration"
    assert report["history_grade"] == "recommended_36m_plus"


def test_sparse_three_year_endpoints_are_not_mistaken_for_three_year_history() -> None:
    bundle = _bundle(months=37)
    bundle["pricing_flow"] = [bundle["pricing_flow"][0], bundle["pricing_flow"][-1]]

    report = assess_internal_calibration_bundle(bundle)

    assert report["history_days"] >= 365 * 3
    assert report["pricing_observation_dates"] == 2
    assert report["history_months"] == 2
    assert report["status"] == "insufficient_history"


def test_direct_pii_fields_are_rejected() -> None:
    bundle = _bundle()
    bundle["pricing_flow"][0]["account_number"] = "123-456"

    report = assess_internal_calibration_bundle(bundle)
    pricing = next(item for item in report["datasets"] if item["dataset"] == "pricing_flow")

    assert report["status"] == "data_quality_failed"
    assert "pii_fields_not_allowed:account_number" in pricing["errors"]


def test_negative_money_amount_is_rejected() -> None:
    bundle = _bundle()
    bundle["pricing_flow"][0]["new_money_amount"] = -1

    report = assess_internal_calibration_bundle(bundle)
    pricing = next(item for item in report["datasets"] if item["dataset"] == "pricing_flow")

    assert report["status"] == "data_quality_failed"
    assert "row_0:negative_amount:new_money_amount" in pricing["errors"]


def test_optional_preference_performance_can_be_added_without_becoming_required() -> None:
    bundle = _bundle()
    bundle["preference_performance"] = [
        {
            "date": "2026-01-01",
            "product_key": "DEP-12M",
            "term_months": 12,
            "preference_code": "MOBILE",
            "eligible_count": 1000,
            "achieved_count": 700,
            "achieved_amount": 50.0,
            "preference_rate_bp": 10,
        }
    ]

    report = assess_internal_calibration_bundle(bundle)

    assert report["status"] == "ready_for_calibration"
    pref = next(
        item for item in report["datasets"] if item["dataset"] == "preference_performance"
    )
    assert pref["status"] == "valid"
