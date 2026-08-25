from __future__ import annotations

from datetime import date

import pytest

from rate_monitor.services.inflow_calibration_protocol import (
    MIN_PROMOTION_FOLDS,
    assess_challenger_promotion,
    build_expanding_window_splits,
    model_candidate_registry,
    protocol_summary,
    validate_feature_columns,
)

_SHA_A = "a" * 64
_SHA_B = "b" * 64
_SHA_C = "c" * 64


def _promotion_evidence() -> dict[str, str]:
    return {
        "experiment_id": "experiment-001",
        "model_artifact_sha256": _SHA_A,
        "training_data_fingerprint_sha256": _SHA_B,
        "feature_schema_sha256": _SHA_C,
    }


def _month_dates(count: int) -> list[str]:
    year = 2023
    month = 1
    values: list[str] = []
    for _ in range(count):
        values.append(date(year, month, 1).isoformat())
        month += 1
        if month == 13:
            year += 1
            month = 1
    return values


def _features() -> list[str]:
    return [
        "own_rate_pct",
        "rate_change_bp",
        "market_gap_bp",
        "term_months",
        "special_offer_flag",
        "lag_1_new_money_amount",
        "maturity_amount",
        "prior_rollover_rate_pct",
        "bok_base_rate_pct",
        "month_sin",
        "month_cos",
    ]


def _challenger_metrics() -> dict[str, float]:
    return {
        "total_wape": 0.09,
        "new_money_wape": 0.10,
        "rollover_rate_mae_pp": 1.00,
        "bias_ratio": 0.01,
        "event_direction_accuracy": 0.70,
    }


def _incumbent_metrics() -> dict[str, float]:
    return {
        "total_wape": 0.10,
        "new_money_wape": 0.11,
        "rollover_rate_mae_pp": 1.10,
        "bias_ratio": 0.02,
        "event_direction_accuracy": 0.60,
    }


def _folds() -> list[dict[str, float | str]]:
    return [
        {
            "role": "development_oos",
            "challenger_total_wape": 0.11,
            "incumbent_total_wape": 0.12,
        },
        {
            "role": "development_oos",
            "challenger_total_wape": 0.10,
            "incumbent_total_wape": 0.11,
        },
        {
            "role": "development_oos",
            "challenger_total_wape": 0.09,
            "incumbent_total_wape": 0.10,
        },
        {
            "role": "final_holdout",
            "challenger_total_wape": 0.08,
            "incumbent_total_wape": 0.09,
        },
    ]


def test_protocol_exposes_human_review_only_promotion_policy() -> None:
    summary = protocol_summary()

    assert summary["promotion_policy"] == "human_review_required_no_auto_promotion"
    assert summary["private_runtime_required"] is True
    assert summary["model_coefficients_changed"] is False
    assert summary["database_written"] is False


def test_candidate_registry_keeps_reference_and_multiple_challenger_tiers() -> None:
    registry = model_candidate_registry()
    by_key = {row["key"]: row for row in registry}

    assert by_key["structural_v2_reference"]["role"] == "incumbent_reference"
    assert by_key["regularized_elasticity_v1"]["role"] == "challenger"
    assert by_key["segment_interaction_v1"]["role"] == "challenger"
    assert by_key["nonlinear_residual_v1"]["minimum_observation_dates"] == 60


def test_feature_contract_rejects_target_future_and_unknown_columns() -> None:
    report = validate_feature_columns(
        [*_features(), "new_money_amount", "future_market_gap_bp", "mystery_feature"]
    )

    assert report["status"] == "invalid"
    assert "new_money_amount" in report["forbidden_features"]
    assert "future_market_gap_bp" in report["forbidden_features"]
    assert report["unknown_features"] == ["mystery_feature"]


def test_feature_contract_requires_core_pricing_inputs() -> None:
    report = validate_feature_columns(["market_gap_bp", "maturity_amount"])

    assert report["status"] == "invalid"
    assert any(reason.startswith("missing_core_features:") for reason in report["errors"])


def test_recommended_36_dates_yield_four_expanding_oos_folds_and_final_holdout() -> None:
    folds = build_expanding_window_splits(_month_dates(36))

    assert len(folds) == MIN_PROMOTION_FOLDS == 4
    assert folds[0]["train_observation_dates"] == 24
    assert folds[0]["test_observation_dates"] == 3
    assert folds[-1]["role"] == "final_holdout"
    assert folds[-1]["train_observation_dates"] == 33
    assert folds[-1]["test_observation_dates"] == 3
    assert folds[0]["train_end"] < folds[0]["test_start"]


def test_24_dates_are_intake_research_history_but_not_enough_for_oos_promotion() -> None:
    assert build_expanding_window_splits(_month_dates(24)) == []


def test_strong_regularized_challenger_is_only_eligible_for_human_review() -> None:
    report = assess_challenger_promotion(
        **_promotion_evidence(),
        candidate_key="regularized_elasticity_v1",
        observation_date_count=36,
        pricing_event_oos_count=8,
        feature_columns=_features(),
        challenger_metrics=_challenger_metrics(),
        incumbent_metrics=_incumbent_metrics(),
        fold_metrics=_folds(),
    )

    assert report["status"] == "eligible_for_human_review"
    assert report["primary_relative_improvement"] == pytest.approx(0.1)
    assert report["improved_fold_share"] == 1.0
    assert report["reasons"] == []
    assert report["auto_promote"] is False
    assert report["human_review_required"] is True
    assert report["model_coefficients_changed"] is False
    assert report["experiment_id"] == "experiment-001"
    assert report["model_artifact_sha256"] == _SHA_A
    assert report["training_data_fingerprint_sha256"] == _SHA_B
    assert report["feature_schema_sha256"] == _SHA_C


def test_good_aggregate_metrics_cannot_hide_a_bad_final_holdout() -> None:
    folds = _folds()
    folds[-1]["challenger_total_wape"] = 0.10
    folds[-1]["incumbent_total_wape"] = 0.09

    report = assess_challenger_promotion(
        **_promotion_evidence(),
        candidate_key="regularized_elasticity_v1",
        observation_date_count=36,
        pricing_event_oos_count=8,
        feature_columns=_features(),
        challenger_metrics=_challenger_metrics(),
        incumbent_metrics=_incumbent_metrics(),
        fold_metrics=folds,
    )

    assert report["status"] == "blocked"
    assert "final_holdout_not_better_than_incumbent" in report["reasons"]


def test_component_regression_blocks_promotion_even_when_total_improves() -> None:
    challenger = _challenger_metrics()
    challenger["rollover_rate_mae_pp"] = 1.30

    report = assess_challenger_promotion(
        **_promotion_evidence(),
        candidate_key="regularized_elasticity_v1",
        observation_date_count=36,
        pricing_event_oos_count=8,
        feature_columns=_features(),
        challenger_metrics=challenger,
        incumbent_metrics=_incumbent_metrics(),
        fold_metrics=_folds(),
    )

    assert report["status"] == "blocked"
    assert "component_regression:rollover_rate_mae_pp" in report["reasons"]


def test_sparse_pricing_events_block_promotion() -> None:
    report = assess_challenger_promotion(
        **_promotion_evidence(),
        candidate_key="regularized_elasticity_v1",
        observation_date_count=36,
        pricing_event_oos_count=2,
        feature_columns=_features(),
        challenger_metrics=_challenger_metrics(),
        incumbent_metrics=_incumbent_metrics(),
        fold_metrics=_folds(),
    )

    assert report["status"] == "blocked"
    assert any(
        reason.startswith("insufficient_pricing_event_oos_count:") for reason in report["reasons"]
    )


def test_nonlinear_candidate_requires_longer_history_before_promotion_review() -> None:
    report = assess_challenger_promotion(
        **_promotion_evidence(),
        candidate_key="nonlinear_residual_v1",
        observation_date_count=48,
        pricing_event_oos_count=8,
        feature_columns=_features(),
        challenger_metrics=_challenger_metrics(),
        incumbent_metrics=_incumbent_metrics(),
        fold_metrics=_folds(),
    )

    assert report["status"] == "blocked"
    assert "insufficient_observation_dates:48<60" in report["reasons"]


def test_unknown_candidate_fails_closed() -> None:
    report = assess_challenger_promotion(
        **_promotion_evidence(),
        candidate_key="mystery_model",
        observation_date_count=60,
        pricing_event_oos_count=8,
        feature_columns=_features(),
        challenger_metrics=_challenger_metrics(),
        incumbent_metrics=_incumbent_metrics(),
        fold_metrics=_folds(),
    )

    assert report["status"] == "blocked"
    assert "unknown_or_non_challenger_candidate" in report["reasons"]


@pytest.mark.parametrize(
    ("field", "value", "expected_reason"),
    [
        ("experiment_id", " experiment-001", "experiment_id:invalid_identifier"),
        ("model_artifact_sha256", "x" * 64, "model_artifact_sha256:invalid_sha256"),
        (
            "training_data_fingerprint_sha256",
            "B" * 64,
            "training_data_fingerprint_sha256:invalid_sha256",
        ),
        ("feature_schema_sha256", "c" * 63, "feature_schema_sha256:invalid_sha256"),
    ],
)
def test_promotion_evidence_identity_fails_closed(
    field: str,
    value: str,
    expected_reason: str,
) -> None:
    evidence = _promotion_evidence()
    evidence[field] = value

    report = assess_challenger_promotion(
        **evidence,
        candidate_key="regularized_elasticity_v1",
        observation_date_count=36,
        pricing_event_oos_count=8,
        feature_columns=_features(),
        challenger_metrics=_challenger_metrics(),
        incumbent_metrics=_incumbent_metrics(),
        fold_metrics=_folds(),
    )

    assert report["status"] == "blocked"
    assert expected_reason in report["reasons"]
