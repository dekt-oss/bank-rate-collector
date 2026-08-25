from __future__ import annotations

from copy import deepcopy
from datetime import date
from typing import Any

import pytest

from rate_monitor.services.inflow_asof_feature_contract import validate_as_of_feature_row
from rate_monitor.services.inflow_backtest_evaluation import score_backtest_records
from rate_monitor.services.inflow_calibration_protocol import (
    PROTOCOL_VERSION,
    assess_challenger_promotion,
    build_expanding_window_splits,
)
from rate_monitor.services.inflow_private_model_registry_contract import (
    LIFECYCLE_CHAMPION,
    REGISTRY_CONTRACT_VERSION,
    assess_champion_activation,
    promotion_report_digest,
    validate_private_registry_snapshot,
)
from rate_monitor.services.inflow_public_forecast_contract import (
    PUBLIC_FORECAST_CONTRACT_VERSION,
    validate_public_forecast_payload,
)
from rate_monitor.services.internal_calibration_intake_service import (
    assess_internal_calibration_bundle,
)

_EXPERIMENT_ID = "synthetic-experiment-001"
_MODEL_ARTIFACT_SHA256 = "a" * 64
_TRAINING_DATA_FINGERPRINT_SHA256 = "b" * 64
_FEATURE_SCHEMA_SHA256 = "c" * 64


def _month_dates(count: int) -> list[str]:
    values: list[str] = []
    year = 2023
    month = 1
    for _ in range(count):
        values.append(date(year, month, 1).isoformat())
        month += 1
        if month == 13:
            year += 1
            month = 1
    return values


def _synthetic_bundle() -> dict[str, list[dict[str, object]]]:
    dates = _month_dates(37)
    return {
        "pricing_flow": [
            {
                "date": observed_at,
                "product_key": "SYNTHETIC-DEP-12M",
                "term_months": 12,
                "applied_rate_pct": 3.4,
                "new_money_amount": 100.0 + index,
                "new_account_count": 1000 + index,
                "end_balance": 2000.0 + index,
            }
            for index, observed_at in enumerate(dates)
        ],
        "maturity_rollover": [
            {
                "date": observed_at,
                "product_key": "SYNTHETIC-DEP-12M",
                "term_months": 12,
                "maturity_amount": 100.0,
                "maturity_account_count": 1000,
                "rollover_amount": 50.0,
                "rollover_account_count": 500,
            }
            for observed_at in dates
        ],
        "early_withdrawal": [
            {
                "date": observed_at,
                "product_key": "SYNTHETIC-DEP-12M",
                "term_months": 12,
                "early_withdrawal_amount": 5.0,
                "early_withdrawal_account_count": 50,
            }
            for observed_at in dates
        ],
        "pricing_events": [
            {
                "start_date": dates[index],
                "product_key": "SYNTHETIC-DEP-12M",
                "term_months": 12,
                "rate_before_pct": 3.3,
                "rate_after_pct": 3.4,
                "special_offer_flag": False,
            }
            for index in range(0, 32, 4)
        ],
        "ftp": [
            {"date": observed_at, "term_months": 12, "ftp_rate_pct": 3.0}
            for observed_at in dates
        ],
    }


def _feature_values() -> dict[str, object]:
    return {
        "own_rate_pct": 3.4,
        "rate_change_bp": 10,
        "market_gap_bp": 5,
        "term_months": 12,
        "special_offer_flag": False,
        "lag_1_new_money_amount": 100.0,
        "maturity_amount": 100.0,
        "prior_rollover_rate_pct": 50.0,
        "bok_base_rate_pct": 2.5,
        "sector_deposit_rate_pct": 3.35,
        "month_sin": 0.5,
        "month_cos": 0.8660254,
    }


def _feature_as_of_dates() -> dict[str, str]:
    return dict.fromkeys(_feature_values(), "2025-12-31")


def _backtest_rows(
    *,
    predicted_new_money: float,
    predicted_rollover: float,
) -> list[dict[str, float | bool]]:
    return [
        {
            "actual_new_money": 100.0,
            "predicted_new_money": predicted_new_money,
            "actual_rollover": 50.0,
            "predicted_rollover": predicted_rollover,
            "maturity_amount": 100.0,
            "pricing_event": True,
            "baseline_total": 140.0,
        }
        for _ in range(8)
    ]


def _evaluation_contracts() -> dict[str, Any]:
    incumbent = score_backtest_records(
        _backtest_rows(predicted_new_money=90.0, predicted_rollover=45.0)
    )
    challenger = score_backtest_records(
        _backtest_rows(predicted_new_money=96.0, predicted_rollover=49.0)
    )
    folds = build_expanding_window_splits(_month_dates(36))
    assert incumbent["metrics"] is not None
    assert challenger["metrics"] is not None
    fold_metrics = [
        {
            "role": fold["role"],
            "challenger_total_wape": challenger["metrics"]["total_wape"],
            "incumbent_total_wape": incumbent["metrics"]["total_wape"],
        }
        for fold in folds
    ]
    return {
        "incumbent": incumbent,
        "challenger": challenger,
        "folds": folds,
        "fold_metrics": fold_metrics,
    }


def _promotion_report(
    *,
    challenger_metrics: dict[str, float] | None = None,
    fold_metrics: list[dict[str, float | str]] | None = None,
) -> dict[str, Any]:
    evaluations = _evaluation_contracts()
    incumbent_score = evaluations["incumbent"]
    challenger_score = evaluations["challenger"]
    assert incumbent_score["metrics"] is not None
    assert challenger_score["metrics"] is not None
    return assess_challenger_promotion(
        experiment_id=_EXPERIMENT_ID,
        model_artifact_sha256=_MODEL_ARTIFACT_SHA256,
        training_data_fingerprint_sha256=_TRAINING_DATA_FINGERPRINT_SHA256,
        feature_schema_sha256=_FEATURE_SCHEMA_SHA256,
        candidate_key="regularized_elasticity_v1",
        observation_date_count=37,
        pricing_event_oos_count=challenger_score["pricing_event_count"],
        feature_columns=list(_feature_values()),
        challenger_metrics=challenger_metrics or challenger_score["metrics"],
        incumbent_metrics=incumbent_score["metrics"],
        fold_metrics=fold_metrics or evaluations["fold_metrics"],
    )


def _champion_entry(report: dict[str, Any]) -> dict[str, object]:
    return {
        "registry_version": REGISTRY_CONTRACT_VERSION,
        "registry_id": "synthetic-registry-001",
        "model_id": "synthetic-model-001",
        "candidate_key": "regularized_elasticity_v1",
        "scope_key": "portfolio:synthetic",
        "lifecycle_status": LIFECYCLE_CHAMPION,
        "protocol_version": PROTOCOL_VERSION,
        "experiment_id": _EXPERIMENT_ID,
        "model_artifact_sha256": _MODEL_ARTIFACT_SHA256,
        "training_data_fingerprint_sha256": _TRAINING_DATA_FINGERPRINT_SHA256,
        "feature_schema_sha256": _FEATURE_SCHEMA_SHA256,
        "promotion_report_sha256": promotion_report_digest(report),
        "promotion_status": "eligible_for_human_review",
        "training_cutoff_date": "2025-09-30",
        "evaluation_cutoff_date": "2025-12-31",
        "effective_from_date": "2026-01-03",
        "human_approved": True,
        "human_approver": "synthetic-human-reviewer",
        "human_approval_at": "2026-01-02T09:00:00+09:00",
        "human_approval_ref": "synthetic-approval:001",
        "supersedes_model_id": None,
    }


def _public_forecast() -> dict[str, object]:
    return {
        "version": PUBLIC_FORECAST_CONTRACT_VERSION,
        "generated_at": "2026-01-02T10:00:00+09:00",
        "status": "ready",
        "amount_unit": "KRW_100M",
        "rate_unit": "percent",
        "scenarios": [
            {
                "rate_pct": 3.4,
                "predicted_new_money": 96.0,
                "predicted_rollover": 49.0,
                "predicted_total": 145.0,
                "incremental_total": 5.0,
                "surface_interest_delta": 0.2,
                "predicted_total_lower": 140.0,
                "predicted_total_upper": 150.0,
            }
        ],
    }


def _run_positive_rehearsal() -> dict[str, Any]:
    intake = assess_internal_calibration_bundle(_synthetic_bundle())
    as_of = validate_as_of_feature_row(
        forecast_origin="2025-12-31",
        target_date="2026-01-31",
        feature_values=_feature_values(),
        feature_as_of_dates=_feature_as_of_dates(),
    )
    evaluations = _evaluation_contracts()
    promotion = _promotion_report()
    entry = _champion_entry(promotion)
    activation = assess_champion_activation(entry=entry, promotion_report=promotion)
    snapshot = validate_private_registry_snapshot([entry])
    public_forecast = validate_public_forecast_payload(_public_forecast())
    return {
        "intake": intake,
        "as_of": as_of,
        "evaluations": evaluations,
        "promotion": promotion,
        "entry": entry,
        "activation": activation,
        "snapshot": snapshot,
        "public_forecast": public_forecast,
    }


def test_synthetic_private_research_rehearsal_reaches_human_approved_champion() -> None:
    result = _run_positive_rehearsal()

    assert result["intake"]["status"] == "ready_for_calibration"
    assert result["as_of"]["status"] == "valid"
    assert result["promotion"]["status"] == "eligible_for_human_review"
    assert result["activation"]["status"] == "activation_allowed"
    assert result["activation"]["auto_activate"] is False
    assert result["snapshot"]["status"] == "valid"
    assert result["public_forecast"]["status"] == "ready"
    assert len(result["evaluations"]["folds"]) == 4
    assert result["evaluations"]["folds"][-1]["role"] == "final_holdout"
    for report_name in ("intake", "as_of", "promotion", "activation", "snapshot"):
        assert result[report_name]["database_written"] is False


def test_future_value_disguised_as_lag_feature_is_blocked() -> None:
    as_of_dates = _feature_as_of_dates()
    as_of_dates["lag_1_new_money_amount"] = "2026-01-01"

    report = validate_as_of_feature_row(
        forecast_origin="2025-12-31",
        target_date="2026-01-31",
        feature_values=_feature_values(),
        feature_as_of_dates=as_of_dates,
    )

    assert report["status"] == "invalid"
    assert report["leakage_detected"] is True


def test_tampered_promotion_report_cannot_activate_champion() -> None:
    report = _promotion_report()
    entry = _champion_entry(report)
    report["primary_relative_improvement"] = 0.99

    activation = assess_champion_activation(entry=entry, promotion_report=report)

    assert activation["status"] == "blocked"
    assert "promotion_report:digest_mismatch" in activation["reasons"]


def test_blocked_promotion_cannot_be_forged_into_registry_champion() -> None:
    evaluations = _evaluation_contracts()
    fold_metrics = deepcopy(evaluations["fold_metrics"])
    fold_metrics[-1]["challenger_total_wape"] = 0.11
    report = _promotion_report(fold_metrics=fold_metrics)
    assert report["status"] == "blocked"
    report["status"] = "eligible_for_human_review"
    entry = _champion_entry(report)

    activation = assess_champion_activation(entry=entry, promotion_report=report)

    assert activation["status"] == "blocked"
    assert "promotion_report:eligible_report_has_reasons" in activation["reasons"]


def test_champion_activation_requires_human_approval() -> None:
    report = _promotion_report()
    entry = _champion_entry(report)
    entry["human_approved"] = False
    entry.pop("human_approver")
    entry.pop("human_approval_at")
    entry.pop("human_approval_ref")

    activation = assess_champion_activation(entry=entry, promotion_report=report)

    assert activation["status"] == "blocked"
    assert "champion_history:human_approval_required" in activation["reasons"]


@pytest.mark.parametrize(
    ("approval_at", "expected_reason"),
    [
        (
            "2025-12-30T09:00:00+09:00",
            "human_approval_at:cannot_precede_evaluation_cutoff_date",
        ),
        ("2026-01-02T09:00:00", "human_approval_at:timezone_required"),
    ],
)
def test_invalid_approval_chronology_or_timezone_blocks_activation(
    approval_at: str,
    expected_reason: str,
) -> None:
    report = _promotion_report()
    entry = _champion_entry(report)
    entry["human_approval_at"] = approval_at

    activation = assess_champion_activation(entry=entry, promotion_report=report)

    assert activation["status"] == "blocked"
    assert expected_reason in activation["reasons"]


def test_duplicate_champion_in_same_scope_is_blocked() -> None:
    report = _promotion_report()
    first = _champion_entry(report)
    second = deepcopy(first)
    second["registry_id"] = "synthetic-registry-002"
    second["model_id"] = "synthetic-model-002"
    second["experiment_id"] = "synthetic-experiment-002"

    snapshot = validate_private_registry_snapshot([first, second])

    assert snapshot["status"] == "invalid"
    assert "multiple_active_champions:portfolio:synthetic:2" in snapshot["errors"]


def test_replacement_without_predecessor_retirement_is_blocked() -> None:
    report = _promotion_report()
    previous = _champion_entry(report)
    replacement = deepcopy(previous)
    replacement["registry_id"] = "synthetic-registry-002"
    replacement["model_id"] = "synthetic-model-002"
    replacement["experiment_id"] = "synthetic-experiment-002"
    replacement["supersedes_model_id"] = "synthetic-model-001"

    snapshot = validate_private_registry_snapshot([previous, replacement])

    assert snapshot["status"] == "invalid"
    assert (
        "supersedes_model_id:previous_model_not_retired:synthetic-model-001"
        in snapshot["errors"]
    )


def test_private_coefficients_cannot_cross_public_forecast_boundary() -> None:
    payload = _public_forecast()
    payload["coefficients"] = {"synthetic_beta": 0.05}

    with pytest.raises(ValueError, match="public_forecast:unknown_fields:coefficients"):
        validate_public_forecast_payload(payload)


@pytest.mark.parametrize(
    ("failure", "expected_reason"),
    [
        ("final_holdout", "final_holdout_not_better_than_incumbent"),
        ("component_regression", "component_regression:rollover_rate_mae_pp"),
    ],
)
def test_holdout_or_component_regression_blocks_promotion(
    failure: str,
    expected_reason: str,
) -> None:
    evaluations = _evaluation_contracts()
    challenger_score = evaluations["challenger"]
    assert challenger_score["metrics"] is not None
    challenger_metrics = dict(challenger_score["metrics"])
    fold_metrics = deepcopy(evaluations["fold_metrics"])
    if failure == "final_holdout":
        fold_metrics[-1]["challenger_total_wape"] = 0.11
    else:
        challenger_metrics["rollover_rate_mae_pp"] = 6.0

    report = _promotion_report(
        challenger_metrics=challenger_metrics,
        fold_metrics=fold_metrics,
    )

    assert report["status"] == "blocked"
    assert expected_reason in report["reasons"]
