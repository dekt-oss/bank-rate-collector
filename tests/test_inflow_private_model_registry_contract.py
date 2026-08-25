from __future__ import annotations

from copy import deepcopy

from rate_monitor.services.inflow_calibration_protocol import (
    PROTOCOL_VERSION,
    assess_challenger_promotion,
)
from rate_monitor.services.inflow_private_model_registry_contract import (
    LIFECYCLE_CANDIDATE,
    LIFECYCLE_CHAMPION,
    LIFECYCLE_RETIRED,
    REGISTRY_CONTRACT_VERSION,
    assess_champion_activation,
    promotion_report_digest,
    validate_private_registry_entry,
    validate_private_registry_snapshot,
)

_SHA_A = "a" * 64
_SHA_B = "b" * 64
_SHA_C = "c" * 64


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


def _promotion_report() -> dict[str, object]:
    return assess_challenger_promotion(
        candidate_key="regularized_elasticity_v1",
        observation_date_count=36,
        pricing_event_oos_count=8,
        feature_columns=_features(),
        challenger_metrics={
            "total_wape": 0.09,
            "new_money_wape": 0.10,
            "rollover_rate_mae_pp": 1.00,
            "bias_ratio": 0.01,
            "event_direction_accuracy": 0.70,
        },
        incumbent_metrics={
            "total_wape": 0.10,
            "new_money_wape": 0.11,
            "rollover_rate_mae_pp": 1.10,
            "bias_ratio": 0.02,
            "event_direction_accuracy": 0.60,
        },
        fold_metrics=[
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
        ],
    )


def _candidate_entry() -> dict[str, object]:
    return {
        "registry_version": REGISTRY_CONTRACT_VERSION,
        "registry_id": "registry-001",
        "model_id": "model-001",
        "candidate_key": "regularized_elasticity_v1",
        "scope_key": "portfolio:all",
        "lifecycle_status": LIFECYCLE_CANDIDATE,
        "protocol_version": PROTOCOL_VERSION,
        "experiment_id": "experiment-001",
        "model_artifact_sha256": _SHA_A,
        "training_data_fingerprint_sha256": _SHA_B,
        "feature_schema_sha256": _SHA_C,
        "promotion_report_sha256": None,
        "promotion_status": "not_assessed",
        "training_cutoff_date": "2025-09-30",
        "evaluation_cutoff_date": "2025-12-31",
        "human_approved": False,
    }


def _champion_entry(
    *,
    model_id: str = "model-001",
    registry_id: str = "registry-001",
    scope_key: str = "portfolio:all",
    supersedes_model_id: str | None = None,
) -> dict[str, object]:
    report = _promotion_report()
    return {
        "registry_version": REGISTRY_CONTRACT_VERSION,
        "registry_id": registry_id,
        "model_id": model_id,
        "candidate_key": "regularized_elasticity_v1",
        "scope_key": scope_key,
        "lifecycle_status": LIFECYCLE_CHAMPION,
        "protocol_version": PROTOCOL_VERSION,
        "experiment_id": f"experiment-{model_id}",
        "model_artifact_sha256": _SHA_A,
        "training_data_fingerprint_sha256": _SHA_B,
        "feature_schema_sha256": _SHA_C,
        "promotion_report_sha256": promotion_report_digest(report),
        "promotion_status": "eligible_for_human_review",
        "training_cutoff_date": "2025-09-30",
        "evaluation_cutoff_date": "2025-12-31",
        "effective_from_date": "2026-01-04",
        "human_approved": True,
        "human_approver": "deposit-strategy-owner",
        "human_approval_at": "2026-01-03T09:00:00+09:00",
        "human_approval_ref": "approval:2026-001",
        "supersedes_model_id": supersedes_model_id,
    }


def _retired_entry(*, model_id: str = "model-old") -> dict[str, object]:
    entry = _champion_entry(model_id=model_id, registry_id=f"registry-{model_id}")
    entry["lifecycle_status"] = LIFECYCLE_RETIRED
    entry["retired_at"] = "2026-02-01T09:00:00+09:00"
    entry["retired_by"] = "deposit-strategy-owner"
    entry["retirement_ref"] = "retirement:2026-001"
    entry["retirement_reason"] = "superseded_after_review"
    return entry


def test_candidate_can_be_registered_before_promotion_assessment() -> None:
    report = validate_private_registry_entry(_candidate_entry())

    assert report["status"] == "valid"
    assert report["activation_candidate"] is False
    assert report["database_written"] is False


def test_promotion_report_digest_is_deterministic_for_key_order() -> None:
    first = {"status": "eligible_for_human_review", "candidate_key": "x"}
    second = {"candidate_key": "x", "status": "eligible_for_human_review"}

    assert promotion_report_digest(first) == promotion_report_digest(second)


def test_champion_activation_requires_exact_promotion_evidence_and_human_approval() -> None:
    report = _promotion_report()
    entry = _champion_entry()

    activation = assess_champion_activation(entry=entry, promotion_report=report)

    assert activation["status"] == "activation_allowed"
    assert activation["auto_activate"] is False
    assert activation["human_approval_verified"] is True


def test_champion_activation_blocks_tampered_promotion_report() -> None:
    report = _promotion_report()
    entry = _champion_entry()
    report["primary_relative_improvement"] = 0.50

    activation = assess_champion_activation(entry=entry, promotion_report=report)

    assert activation["status"] == "blocked"
    assert "promotion_report:digest_mismatch" in activation["reasons"]


def test_champion_activation_blocks_noneligible_report_even_with_matching_digest() -> None:
    report = _promotion_report()
    report["status"] = "blocked"
    report["reasons"] = ["final_holdout_not_better_than_incumbent"]
    entry = _champion_entry()
    entry["promotion_report_sha256"] = promotion_report_digest(report)

    activation = assess_champion_activation(entry=entry, promotion_report=report)

    assert activation["status"] == "blocked"
    assert "promotion_report:not_eligible_for_human_review" in activation["reasons"]


def test_champion_entry_without_human_approval_is_invalid() -> None:
    entry = _champion_entry()
    entry["human_approved"] = False
    entry.pop("human_approver")
    entry.pop("human_approval_at")
    entry.pop("human_approval_ref")

    report = validate_private_registry_entry(entry)

    assert report["status"] == "invalid"
    assert "champion_history:human_approval_required" in report["errors"]


def test_registry_refuses_embedded_coefficients_or_diagnostics() -> None:
    entry = _candidate_entry()
    entry["coefficients"] = {"beta": 0.123}
    entry["training_diagnostics"] = {"loss": 0.01}

    report = validate_private_registry_entry(entry)

    assert report["status"] == "invalid"
    assert any(reason.startswith("embedded_private_fields_forbidden:") for reason in report["errors"])


def test_registry_refuses_nested_value_in_text_metadata_field() -> None:
    entry = _champion_entry()
    entry["human_approver"] = {"coefficients": [1, 2, 3]}

    report = validate_private_registry_entry(entry)

    assert report["status"] == "invalid"
    assert "human_approver:must_be_string_or_null" in report["errors"]


def test_public_structural_reference_cannot_be_private_calibrated_candidate() -> None:
    entry = _candidate_entry()
    entry["candidate_key"] = "structural_v2_reference"

    report = validate_private_registry_entry(entry)

    assert report["status"] == "invalid"
    assert "candidate_key:unknown_or_non_challenger" in report["errors"]


def test_human_approval_cannot_precede_evaluation_cutoff() -> None:
    entry = _champion_entry()
    entry["human_approval_at"] = "2025-12-01T09:00:00+09:00"

    report = validate_private_registry_entry(entry)

    assert report["status"] == "invalid"
    assert "human_approval_at:cannot_precede_evaluation_cutoff_date" in report["errors"]


def test_snapshot_rejects_multiple_active_champions_for_same_scope() -> None:
    first = _champion_entry(model_id="model-a", registry_id="registry-a")
    second = _champion_entry(model_id="model-b", registry_id="registry-b")

    report = validate_private_registry_snapshot([first, second])

    assert report["status"] == "invalid"
    assert "multiple_active_champions:portfolio:all:2" in report["errors"]


def test_replacement_snapshot_requires_previous_model_to_be_retired() -> None:
    previous = _champion_entry(model_id="model-old", registry_id="registry-old")
    current = _champion_entry(
        model_id="model-new",
        registry_id="registry-new",
        supersedes_model_id="model-old",
    )

    report = validate_private_registry_snapshot([previous, current])

    assert report["status"] == "invalid"
    assert "supersedes_model_id:previous_model_not_retired:model-old" in report["errors"]


def test_valid_replacement_snapshot_has_one_champion_and_retired_predecessor() -> None:
    previous = _retired_entry(model_id="model-old")
    current = _champion_entry(
        model_id="model-new",
        registry_id="registry-new",
        supersedes_model_id="model-old",
    )

    report = validate_private_registry_snapshot([previous, current])

    assert report["status"] == "valid"
    assert report["active_champion_scopes"] == ["portfolio:all"]


def test_snapshot_rejects_duplicate_model_identity() -> None:
    first = _candidate_entry()
    second = deepcopy(first)
    second["registry_id"] = "registry-002"

    report = validate_private_registry_snapshot([first, second])

    assert report["status"] == "invalid"
    assert "duplicate_model_id:model-001" in report["errors"]


def test_not_assessed_candidate_cannot_claim_promotion_report_digest() -> None:
    entry = _candidate_entry()
    entry["promotion_report_sha256"] = _SHA_A

    report = validate_private_registry_entry(entry)

    assert report["status"] == "invalid"
    assert "promotion_report_sha256:must_be_empty_when_not_assessed" in report["errors"]
