"""Private inflow feature table의 row-level as-of leakage Gate.

열 이름이 ``lag_*``라고 해서 실제 과거값임을 신뢰하지 않는다. Private adapter는 각
feature가 언제 확정된 값인지 ``feature_as_of_dates``로 함께 기록해야 하며, 이 Gate는
모든 feature가 forecast origin 시점에 실제로 이용 가능했는지 fail-closed 검증한다.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from rate_monitor.services.inflow_calibration_protocol import validate_feature_columns

AS_OF_CONTRACT_VERSION = "inflow-asof-feature-contract-v1"


def _parse_date(value: Any, *, field: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    candidates = (text, f"{text}-01" if len(text) == 7 else text)
    for candidate in candidates:
        try:
            return date.fromisoformat(candidate)
        except ValueError:
            continue
    raise ValueError(f"{field}:invalid_date")


def validate_as_of_feature_row(
    *,
    forecast_origin: Any,
    target_date: Any,
    feature_values: dict[str, Any],
    feature_as_of_dates: dict[str, Any],
) -> dict[str, Any]:
    """한 forecast row의 feature availability를 예측시점 기준으로 검증한다."""
    errors: list[str] = []

    try:
        origin = _parse_date(forecast_origin, field="forecast_origin")
    except ValueError as exc:
        errors.append(str(exc))
        origin = None
    try:
        target = _parse_date(target_date, field="target_date")
    except ValueError as exc:
        errors.append(str(exc))
        target = None

    if origin is not None and target is not None and target <= origin:
        errors.append("target_date_must_be_after_forecast_origin")

    if not isinstance(feature_values, dict):
        errors.append("feature_values:must_be_object")
        normalized_values: dict[str, Any] = {}
    else:
        normalized_values = feature_values
    if not isinstance(feature_as_of_dates, dict):
        errors.append("feature_as_of_dates:must_be_object")
        normalized_as_of: dict[str, Any] = {}
    else:
        normalized_as_of = feature_as_of_dates

    feature_report = validate_feature_columns(set(normalized_values))
    if feature_report["status"] != "valid":
        errors.extend(feature_report["errors"])

    value_keys = set(normalized_values)
    as_of_keys = set(normalized_as_of)
    missing_as_of = sorted(value_keys - as_of_keys)
    extra_as_of = sorted(as_of_keys - value_keys)
    if missing_as_of:
        errors.append("missing_feature_as_of_dates:" + ",".join(missing_as_of))
    if extra_as_of:
        errors.append("orphan_feature_as_of_dates:" + ",".join(extra_as_of))

    parsed_as_of: dict[str, str] = {}
    for feature in sorted(value_keys & as_of_keys):
        try:
            feature_date = _parse_date(
                normalized_as_of[feature], field=f"feature_as_of_dates.{feature}"
            )
        except ValueError as exc:
            errors.append(str(exc))
            continue
        parsed_as_of[feature] = feature_date.isoformat()
        if origin is not None and feature_date > origin:
            errors.append(
                f"feature_not_available_at_forecast_origin:{feature}:"
                f"{feature_date.isoformat()}>{origin.isoformat()}"
            )

    return {
        "version": AS_OF_CONTRACT_VERSION,
        "status": "valid" if not errors else "invalid",
        "errors": errors,
        "forecast_origin": origin.isoformat() if origin is not None else None,
        "target_date": target.isoformat() if target is not None else None,
        "feature_as_of_dates": parsed_as_of,
        "feature_report": feature_report,
        "leakage_detected": any(
            error.startswith("feature_not_available_at_forecast_origin:") for error in errors
        ),
        "database_written": False,
    }
