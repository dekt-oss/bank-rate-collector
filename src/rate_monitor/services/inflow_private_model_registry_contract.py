"""Private inflow champion registry의 공개 가능한 governance contract.

이 모듈은 실제 내부 모델 artifact나 계수, training diagnostics를 저장하지 않는다.
private/local runtime에서 유지할 registry metadata의 형태와 champion 활성화 Gate만 정의한다.

핵심 원칙:
- promotion report가 ``eligible_for_human_review``여도 자동 승격하지 않는다.
- champion은 정확한 promotion report digest와 명시적 human approval이 모두 있어야 한다.
- registry에는 coefficient/raw rows/feature importance/training diagnostics를 embed하지 않는다.
- 실제 registry 값과 model artifact는 public Git/GitHub 밖 private workspace에 둔다.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime
from typing import Any

from rate_monitor.services.inflow_calibration_protocol import (
    PROTOCOL_VERSION,
    model_candidate_registry,
)

REGISTRY_CONTRACT_VERSION = "inflow-private-model-registry-v1"

LIFECYCLE_CANDIDATE = "candidate"
LIFECYCLE_ELIGIBLE = "eligible_for_human_review"
LIFECYCLE_CHAMPION = "champion"
LIFECYCLE_RETIRED = "retired"

_ALLOWED_LIFECYCLE = frozenset(
    {
        LIFECYCLE_CANDIDATE,
        LIFECYCLE_ELIGIBLE,
        LIFECYCLE_CHAMPION,
        LIFECYCLE_RETIRED,
    }
)

_ALLOWED_PROMOTION_STATUS = frozenset(
    {
        "not_assessed",
        "blocked",
        "eligible_for_human_review",
    }
)

_ALLOWED_FIELDS = frozenset(
    {
        "registry_version",
        "registry_id",
        "model_id",
        "candidate_key",
        "scope_key",
        "lifecycle_status",
        "protocol_version",
        "experiment_id",
        "model_artifact_sha256",
        "training_data_fingerprint_sha256",
        "feature_schema_sha256",
        "promotion_report_sha256",
        "promotion_status",
        "training_cutoff_date",
        "evaluation_cutoff_date",
        "effective_from_date",
        "human_approved",
        "human_approver",
        "human_approval_at",
        "human_approval_ref",
        "supersedes_model_id",
        "retired_at",
        "retired_by",
        "retirement_ref",
        "retirement_reason",
    }
)

_REQUIRED_FIELDS = frozenset(
    {
        "registry_version",
        "registry_id",
        "model_id",
        "candidate_key",
        "scope_key",
        "lifecycle_status",
        "protocol_version",
        "experiment_id",
        "model_artifact_sha256",
        "training_data_fingerprint_sha256",
        "feature_schema_sha256",
        "promotion_report_sha256",
        "promotion_status",
        "training_cutoff_date",
        "evaluation_cutoff_date",
        "human_approved",
    }
)

_PRIVATE_EMBEDDED_FIELDS = frozenset(
    {
        "coefficient",
        "coefficients",
        "feature_importance",
        "feature_importances",
        "training_diagnostics",
        "training_rows",
        "raw_rows",
        "raw_data",
        "model_bytes",
        "artifact_bytes",
        "account_number",
        "customer_name",
        "resident_registration_number",
    }
)

_TEXT_FIELDS = frozenset(
    {
        "registry_version",
        "registry_id",
        "model_id",
        "candidate_key",
        "scope_key",
        "lifecycle_status",
        "protocol_version",
        "experiment_id",
        "model_artifact_sha256",
        "training_data_fingerprint_sha256",
        "feature_schema_sha256",
        "promotion_status",
        "training_cutoff_date",
        "evaluation_cutoff_date",
    }
)

_OPTIONAL_TEXT_FIELDS = frozenset(
    {
        "promotion_report_sha256",
        "effective_from_date",
        "human_approver",
        "human_approval_at",
        "human_approval_ref",
        "supersedes_model_id",
        "retired_at",
        "retired_by",
        "retirement_ref",
        "retirement_reason",
    }
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")

_KNOWN_CHALLENGERS = frozenset(
    row["key"] for row in model_candidate_registry() if row["role"] == "challenger"
)


def promotion_report_digest(report: dict[str, Any]) -> str:
    """Promotion report를 deterministic SHA-256으로 바인딩한다."""
    encoded = json.dumps(
        report,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _parse_date(value: Any, *, field: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise ValueError(f"{field}:invalid_date")
    text = value.strip()
    for candidate in (text, f"{text}-01" if len(text) == 7 else text):
        try:
            return date.fromisoformat(candidate)
        except ValueError:
            continue
    raise ValueError(f"{field}:invalid_date")


def _parse_datetime(value: Any, *, field: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        text = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ValueError(f"{field}:invalid_datetime") from exc
    else:
        raise ValueError(f"{field}:invalid_datetime")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field}:timezone_required")
    return parsed


def _nonempty_identifier(value: Any) -> bool:
    return (
        isinstance(value, str)
        and value == value.strip()
        and bool(_ID_RE.fullmatch(value))
    )


def _nonempty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _valid_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and value == value.strip()
        and bool(_SHA256_RE.fullmatch(value))
    )


def _validate_field_types(entry: dict[str, Any], errors: list[str]) -> None:
    for field in sorted(_TEXT_FIELDS & set(entry)):
        if not isinstance(entry[field], str):
            errors.append(f"{field}:must_be_string")
    for field in sorted(_OPTIONAL_TEXT_FIELDS & set(entry)):
        if entry[field] is not None and not isinstance(entry[field], str):
            errors.append(f"{field}:must_be_string_or_null")


def _validate_approval_fields(entry: dict[str, Any], errors: list[str]) -> None:
    approved = entry.get("human_approved")
    if not isinstance(approved, bool):
        errors.append("human_approved:must_be_boolean")
        return

    approval_fields = (
        "human_approver",
        "human_approval_at",
        "human_approval_ref",
    )
    if not approved:
        populated = [field for field in approval_fields if _nonempty_text(entry.get(field))]
        if populated:
            errors.append("human_approval_fields_present_without_approval:" + ",".join(populated))
        return

    for field in approval_fields:
        if not _nonempty_text(entry.get(field)):
            errors.append(f"{field}:required_when_human_approved")

    if _nonempty_text(entry.get("human_approval_at")):
        try:
            _parse_datetime(entry["human_approval_at"], field="human_approval_at")
        except ValueError as exc:
            errors.append(str(exc))


def _validate_retirement_fields(entry: dict[str, Any], errors: list[str]) -> None:
    status = entry.get("lifecycle_status")
    retirement_fields = (
        "retired_at",
        "retired_by",
        "retirement_ref",
        "retirement_reason",
    )

    if status != LIFECYCLE_RETIRED:
        populated = [field for field in retirement_fields if _nonempty_text(entry.get(field))]
        if populated:
            errors.append("retirement_fields_present_while_active:" + ",".join(populated))
        return

    for field in retirement_fields:
        if not _nonempty_text(entry.get(field)):
            errors.append(f"{field}:required_when_retired")

    if _nonempty_text(entry.get("retired_at")):
        try:
            _parse_datetime(entry["retired_at"], field="retired_at")
        except ValueError as exc:
            errors.append(str(exc))


def validate_private_registry_entry(entry: Any) -> dict[str, Any]:
    """한 private registry metadata row를 fail-closed 검증한다."""
    if not isinstance(entry, dict):
        return {
            "status": "invalid",
            "errors": ["registry_entry:must_be_mapping"],
            "activation_candidate": False,
            "database_written": False,
        }

    if any(not isinstance(field, str) for field in entry):
        return {
            "version": REGISTRY_CONTRACT_VERSION,
            "status": "invalid",
            "errors": ["registry_entry:field_names_must_be_strings"],
            "candidate_key": None,
            "lifecycle_status": entry.get("lifecycle_status"),
            "activation_candidate": False,
            "database_written": False,
        }

    errors: list[str] = []
    fields = set(entry)
    missing = sorted(_REQUIRED_FIELDS - fields)
    unknown = sorted(fields - _ALLOWED_FIELDS)
    embedded_private = sorted(fields & _PRIVATE_EMBEDDED_FIELDS)

    if missing:
        errors.append("missing_fields:" + ",".join(missing))
    if unknown:
        errors.append("unknown_fields:" + ",".join(unknown))
    if embedded_private:
        errors.append("embedded_private_fields_forbidden:" + ",".join(embedded_private))

    _validate_field_types(entry, errors)

    if entry.get("registry_version") != REGISTRY_CONTRACT_VERSION:
        errors.append("registry_version:mismatch")
    if entry.get("protocol_version") != PROTOCOL_VERSION:
        errors.append("protocol_version:mismatch")

    for field in ("registry_id", "model_id", "scope_key", "experiment_id"):
        if not _nonempty_identifier(entry.get(field)):
            errors.append(f"{field}:invalid_identifier")

    candidate_key = entry.get("candidate_key")
    if not isinstance(candidate_key, str) or candidate_key.strip() not in _KNOWN_CHALLENGERS:
        errors.append("candidate_key:unknown_or_non_challenger")
    normalized_candidate = candidate_key.strip() if isinstance(candidate_key, str) else ""

    lifecycle_status = entry.get("lifecycle_status")
    if lifecycle_status not in _ALLOWED_LIFECYCLE:
        errors.append("lifecycle_status:invalid")

    promotion_status = entry.get("promotion_status")
    if promotion_status not in _ALLOWED_PROMOTION_STATUS:
        errors.append("promotion_status:invalid")

    for field in (
        "model_artifact_sha256",
        "training_data_fingerprint_sha256",
        "feature_schema_sha256",
    ):
        if not _valid_sha256(entry.get(field)):
            errors.append(f"{field}:invalid_sha256")

    promotion_digest = entry.get("promotion_report_sha256")
    if promotion_status == "not_assessed":
        if promotion_digest not in {None, ""}:
            errors.append("promotion_report_sha256:must_be_empty_when_not_assessed")
    elif not _valid_sha256(promotion_digest):
        errors.append("promotion_report_sha256:invalid_sha256")

    training_date: date | None = None
    evaluation_date: date | None = None
    for field in ("training_cutoff_date", "evaluation_cutoff_date"):
        try:
            parsed = _parse_date(entry.get(field), field=field)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if field == "training_cutoff_date":
            training_date = parsed
        else:
            evaluation_date = parsed

    if (
        training_date is not None
        and evaluation_date is not None
        and evaluation_date <= training_date
    ):
        errors.append("evaluation_cutoff_date:must_be_after_training_cutoff_date")

    effective_from: date | None = None
    if _nonempty_text(entry.get("effective_from_date")):
        try:
            effective_from = _parse_date(entry["effective_from_date"], field="effective_from_date")
        except ValueError as exc:
            errors.append(str(exc))

    _validate_approval_fields(entry, errors)
    _validate_retirement_fields(entry, errors)

    human_approved = entry.get("human_approved") is True
    if lifecycle_status == LIFECYCLE_CANDIDATE:
        if promotion_status == "eligible_for_human_review":
            errors.append("candidate:cannot_claim_eligible_promotion_status")
        if human_approved:
            errors.append("candidate:human_approval_not_allowed")
        if effective_from is not None:
            errors.append("candidate:effective_from_date_not_allowed")

    if lifecycle_status == LIFECYCLE_ELIGIBLE:
        if promotion_status != "eligible_for_human_review":
            errors.append("eligible:promotion_status_must_be_eligible_for_human_review")
        if human_approved:
            errors.append("eligible:human_approval_reserved_for_champion")
        if effective_from is not None:
            errors.append("eligible:effective_from_date_not_allowed")

    if lifecycle_status in {LIFECYCLE_CHAMPION, LIFECYCLE_RETIRED}:
        if promotion_status != "eligible_for_human_review":
            errors.append("champion_history:promotion_status_must_be_eligible_for_human_review")
        if not human_approved:
            errors.append("champion_history:human_approval_required")
        if effective_from is None:
            errors.append("champion_history:effective_from_date_required")

    approval_at: datetime | None = None
    if human_approved and evaluation_date is not None:
        try:
            approval_at = _parse_datetime(entry.get("human_approval_at"), field="human_approval_at")
        except ValueError:
            approval_at = None
        if approval_at is not None and approval_at.date() < evaluation_date:
            errors.append("human_approval_at:cannot_precede_evaluation_cutoff_date")
        elif approval_at is not None and approval_at.date() == evaluation_date:
            errors.append("human_approval_at:must_be_after_evaluation_cutoff_date")
        if (
            effective_from is not None
            and approval_at is not None
            and effective_from <= approval_at.date()
        ):
            errors.append("effective_from_date:must_be_after_human_approval_date")

    retired_at: datetime | None = None
    if lifecycle_status == LIFECYCLE_RETIRED and _nonempty_text(entry.get("retired_at")):
        try:
            retired_at = _parse_datetime(entry["retired_at"], field="retired_at")
        except ValueError:
            retired_at = None
    if retired_at is not None and approval_at is not None and retired_at < approval_at:
        errors.append("retired_at:cannot_precede_human_approval")
    if (
        retired_at is not None
        and effective_from is not None
        and retired_at.date() < effective_from
    ):
        errors.append("retired_at:cannot_precede_effective_from_date")

    supersedes = entry.get("supersedes_model_id")
    if supersedes not in {None, ""}:
        if not _nonempty_identifier(supersedes):
            errors.append("supersedes_model_id:invalid_identifier")
        if supersedes == entry.get("model_id"):
            errors.append("supersedes_model_id:cannot_reference_self")

    return {
        "version": REGISTRY_CONTRACT_VERSION,
        "status": "valid" if not errors else "invalid",
        "errors": errors,
        "candidate_key": normalized_candidate or None,
        "lifecycle_status": lifecycle_status,
        "activation_candidate": lifecycle_status == LIFECYCLE_CHAMPION and not errors,
        "database_written": False,
    }


def assess_champion_activation(
    *,
    entry: Any,
    promotion_report: Any,
) -> dict[str, Any]:
    """정확한 promotion evidence + human approval이 있을 때만 champion 활성화를 허용한다."""
    entry_report = validate_private_registry_entry(entry)
    reasons = list(entry_report["errors"])

    if entry_report.get("lifecycle_status") != LIFECYCLE_CHAMPION:
        reasons.append("registry_entry:not_champion")

    if not isinstance(promotion_report, dict):
        reasons.append("promotion_report:must_be_mapping")
        promotion_digest = None
    else:
        try:
            promotion_digest = promotion_report_digest(promotion_report)
        except (TypeError, ValueError):
            promotion_digest = None
            reasons.append("promotion_report:not_canonical_json")

    if (
        isinstance(entry, dict)
        and promotion_digest is not None
        and promotion_digest != entry.get("promotion_report_sha256")
    ):
        reasons.append("promotion_report:digest_mismatch")

    if isinstance(promotion_report, dict):
        if promotion_report.get("status") != "eligible_for_human_review":
            reasons.append("promotion_report:not_eligible_for_human_review")
        elif promotion_report.get("reasons") != []:
            reasons.append("promotion_report:eligible_report_has_reasons")
        if promotion_report.get("human_review_required") is not True:
            reasons.append("promotion_report:human_review_required_must_be_true")
        if promotion_report.get("auto_promote") is not False:
            reasons.append("promotion_report:auto_promote_must_be_false")
        if isinstance(entry, dict):
            for report_field, entry_field, label in (
                ("version", "protocol_version", "protocol_version"),
                ("candidate_key", "candidate_key", "candidate_key"),
                ("experiment_id", "experiment_id", "experiment_id"),
                (
                    "model_artifact_sha256",
                    "model_artifact_sha256",
                    "model_artifact_sha256",
                ),
                (
                    "training_data_fingerprint_sha256",
                    "training_data_fingerprint_sha256",
                    "training_data_fingerprint_sha256",
                ),
                ("feature_schema_sha256", "feature_schema_sha256", "feature_schema_sha256"),
            ):
                if promotion_report.get(report_field) != entry.get(entry_field):
                    reasons.append(f"promotion_report:{label}_mismatch")

    return {
        "version": REGISTRY_CONTRACT_VERSION,
        "status": "activation_allowed" if not reasons else "blocked",
        "reasons": reasons,
        "auto_activate": False,
        "human_approval_verified": isinstance(entry, dict)
        and entry.get("human_approved") is True
        and not reasons,
        "database_written": False,
    }


def validate_private_registry_snapshot(entries: Any) -> dict[str, Any]:
    """현재 registry snapshot에서 단일 active champion과 replacement 관계를 검증한다."""
    if not isinstance(entries, (list, tuple)):
        return {
            "status": "invalid",
            "errors": ["registry_snapshot:must_be_sequence"],
            "database_written": False,
        }

    errors: list[str] = []
    valid_entries: list[dict[str, Any]] = []
    seen_registry_ids: set[str] = set()
    seen_model_ids: set[str] = set()

    for index, entry in enumerate(entries):
        report = validate_private_registry_entry(entry)
        if report["status"] != "valid":
            errors.extend(f"entry[{index}]:{reason}" for reason in report["errors"])
            continue
        assert isinstance(entry, dict)
        registry_id = entry["registry_id"]
        model_id = entry["model_id"]
        if registry_id in seen_registry_ids:
            errors.append(f"duplicate_registry_id:{registry_id}")
        seen_registry_ids.add(registry_id)
        if model_id in seen_model_ids:
            errors.append(f"duplicate_model_id:{model_id}")
        seen_model_ids.add(model_id)
        valid_entries.append(entry)

    champions_by_scope: dict[str, list[dict[str, Any]]] = {}
    by_model_id = {entry["model_id"]: entry for entry in valid_entries}
    for entry in valid_entries:
        if entry["lifecycle_status"] == LIFECYCLE_CHAMPION:
            champions_by_scope.setdefault(entry["scope_key"], []).append(entry)

    for scope_key, champions in champions_by_scope.items():
        if len(champions) > 1:
            errors.append(f"multiple_active_champions:{scope_key}:{len(champions)}")

    for entry in valid_entries:
        if entry["lifecycle_status"] not in {LIFECYCLE_CHAMPION, LIFECYCLE_RETIRED}:
            continue
        supersedes = entry.get("supersedes_model_id")
        if not supersedes:
            continue
        previous = by_model_id.get(supersedes)
        if previous is None:
            errors.append(f"supersedes_model_id:not_found:{supersedes}")
            continue
        if previous["scope_key"] != entry["scope_key"]:
            errors.append(f"supersedes_model_id:scope_mismatch:{supersedes}")
        if previous["lifecycle_status"] != LIFECYCLE_RETIRED:
            errors.append(f"supersedes_model_id:previous_model_not_retired:{supersedes}")
            continue
        predecessor_retired_at = _parse_datetime(previous["retired_at"], field="retired_at")
        replacement_approval_at = _parse_datetime(
            entry["human_approval_at"], field="human_approval_at"
        )
        replacement_effective_from = _parse_date(
            entry["effective_from_date"], field="effective_from_date"
        )
        if predecessor_retired_at >= replacement_approval_at:
            errors.append(
                "supersedes_model_id:predecessor_not_retired_before_replacement_approval:"
                f"{supersedes}"
            )
        if predecessor_retired_at.date() >= replacement_effective_from:
            errors.append(
                "supersedes_model_id:predecessor_not_retired_before_replacement_effective_date:"
                f"{supersedes}"
            )

    return {
        "version": REGISTRY_CONTRACT_VERSION,
        "status": "valid" if not errors else "invalid",
        "errors": errors,
        "entry_count": len(entries),
        "active_champion_scopes": sorted(champions_by_scope),
        "database_written": False,
    }
