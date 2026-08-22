"""Confidential 수신예측 엔진과 public Strategy 사이의 fail-closed 계약.

이 모듈은 실제 내부자료나 calibration을 다루지 않는다. confidential runtime이 만든
예측 결과 중 public Strategy에 노출해도 되는 필드만 allowlist로 검증한다.
unknown field를 조용히 제거하지 않고 거부해 private diagnostic의 우발적 노출을 막는다.
"""

from __future__ import annotations

import math
from typing import Any

PUBLIC_FORECAST_CONTRACT_VERSION = "inflow-public-forecast-v1"
PUBLIC_AMOUNT_UNIT = "KRW_100M"
PUBLIC_RATE_UNIT = "percent"
PUBLIC_STATUS_VALUES = frozenset({"ready", "unavailable"})

_ALLOWED_TOP_LEVEL_FIELDS = frozenset(
    {
        "version",
        "generated_at",
        "status",
        "amount_unit",
        "rate_unit",
        "scenarios",
    }
)
_REQUIRED_TOP_LEVEL_FIELDS = _ALLOWED_TOP_LEVEL_FIELDS

_ALLOWED_SCENARIO_FIELDS = frozenset(
    {
        "rate_pct",
        "predicted_new_money",
        "predicted_rollover",
        "predicted_total",
        "incremental_total",
        "surface_interest_delta",
        "predicted_total_lower",
        "predicted_total_upper",
    }
)
_REQUIRED_SCENARIO_FIELDS = frozenset(
    {
        "rate_pct",
        "predicted_new_money",
        "predicted_rollover",
        "predicted_total",
        "incremental_total",
        "surface_interest_delta",
    }
)
_INTERVAL_FIELDS = frozenset({"predicted_total_lower", "predicted_total_upper"})
_NON_NEGATIVE_SCENARIO_FIELDS = frozenset(
    {
        "predicted_new_money",
        "predicted_rollover",
        "predicted_total",
        "predicted_total_lower",
        "predicted_total_upper",
    }
)


def public_forecast_allowlist() -> dict[str, list[str]]:
    """감사/테스트용 public allowlist를 정렬된 형태로 반환한다."""
    return {
        "top_level": sorted(_ALLOWED_TOP_LEVEL_FIELDS),
        "scenario": sorted(_ALLOWED_SCENARIO_FIELDS),
    }


def _unknown_fields(payload: dict[str, Any], allowed: frozenset[str]) -> list[str]:
    return sorted(set(payload) - allowed)


def _missing_fields(payload: dict[str, Any], required: frozenset[str]) -> list[str]:
    return sorted(required - set(payload))


def _finite_number(value: Any, *, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field}:must_be_finite_number")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field}:must_be_finite_number") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"{field}:must_be_finite_number")
    return parsed


def _validate_scenario(row: Any, *, index: int) -> None:
    if not isinstance(row, dict):
        raise ValueError(f"scenario_{index}:must_be_object")

    unknown = _unknown_fields(row, _ALLOWED_SCENARIO_FIELDS)
    if unknown:
        raise ValueError(f"scenario_{index}:unknown_fields:{','.join(unknown)}")

    missing = _missing_fields(row, _REQUIRED_SCENARIO_FIELDS)
    if missing:
        raise ValueError(f"scenario_{index}:missing_fields:{','.join(missing)}")

    interval_present = set(row) & _INTERVAL_FIELDS
    if interval_present and interval_present != set(_INTERVAL_FIELDS):
        raise ValueError(f"scenario_{index}:prediction_interval_requires_both_bounds")

    numeric: dict[str, float] = {}
    for field in row:
        numeric[field] = _finite_number(row[field], field=f"scenario_{index}.{field}")

    if not 0 <= numeric["rate_pct"] <= 100:
        raise ValueError(f"scenario_{index}.rate_pct:out_of_range")

    for field in _NON_NEGATIVE_SCENARIO_FIELDS & set(numeric):
        if numeric[field] < 0:
            raise ValueError(f"scenario_{index}.{field}:must_be_non_negative")

    component_total = numeric["predicted_new_money"] + numeric["predicted_rollover"]
    if not math.isclose(
        numeric["predicted_total"],
        component_total,
        rel_tol=1e-9,
        abs_tol=1e-6,
    ):
        raise ValueError(f"scenario_{index}:predicted_total_component_mismatch")

    if interval_present:
        lower = numeric["predicted_total_lower"]
        upper = numeric["predicted_total_upper"]
        total = numeric["predicted_total"]
        if not lower <= total <= upper:
            raise ValueError(f"scenario_{index}:prediction_interval_does_not_cover_total")


def validate_public_forecast_payload(payload: Any) -> dict[str, Any]:
    """Public Strategy로 나가기 직전 forecast payload를 fail-closed 검증한다.

    이 함수는 sanitizer가 아니다. unknown/private field를 삭제해 통과시키지 않는다.
    allowlist 밖의 필드가 하나라도 있으면 호출자가 오류를 처리하도록 ValueError를 낸다.
    """
    if not isinstance(payload, dict):
        raise ValueError("public_forecast:must_be_object")

    unknown = _unknown_fields(payload, _ALLOWED_TOP_LEVEL_FIELDS)
    if unknown:
        raise ValueError(f"public_forecast:unknown_fields:{','.join(unknown)}")

    missing = _missing_fields(payload, _REQUIRED_TOP_LEVEL_FIELDS)
    if missing:
        raise ValueError(f"public_forecast:missing_fields:{','.join(missing)}")

    if payload["version"] != PUBLIC_FORECAST_CONTRACT_VERSION:
        raise ValueError("public_forecast:unsupported_version")
    if payload["amount_unit"] != PUBLIC_AMOUNT_UNIT:
        raise ValueError("public_forecast:unsupported_amount_unit")
    if payload["rate_unit"] != PUBLIC_RATE_UNIT:
        raise ValueError("public_forecast:unsupported_rate_unit")

    generated_at = payload["generated_at"]
    if not isinstance(generated_at, str) or not generated_at.strip():
        raise ValueError("public_forecast:generated_at_required")

    status = payload["status"]
    if not isinstance(status, str) or status not in PUBLIC_STATUS_VALUES:
        raise ValueError("public_forecast:unsupported_status")

    scenarios = payload["scenarios"]
    if not isinstance(scenarios, list):
        raise ValueError("public_forecast:scenarios_must_be_list")
    if status == "ready" and not scenarios:
        raise ValueError("public_forecast:ready_requires_scenarios")
    if status == "unavailable" and scenarios:
        raise ValueError("public_forecast:unavailable_must_not_include_scenarios")

    for index, row in enumerate(scenarios):
        _validate_scenario(row, index=index)

    return payload
