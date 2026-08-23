"""Public Structural v2 forecast provider adapter.

Decision Surface/Cockpit은 provider 구현체가 아니라 #168의
``inflow-public-forecast-v1`` 결과만 소비한다. 이 모듈은 current structural
provider를 같은 경계 뒤에 두고 future confidential provider가 public allowlist
밖의 metadata를 흘리지 못하게 fail-closed 검증한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from rate_monitor.services.inflow_public_forecast_contract import (
    PUBLIC_AMOUNT_UNIT,
    PUBLIC_FORECAST_CONTRACT_VERSION,
    PUBLIC_RATE_UNIT,
    validate_public_forecast_payload,
)
from rate_monitor.services.public_structural_v2_decision_contract import (
    build_public_structural_v2_forecast,
)
from rate_monitor.services.public_structural_v2_market_position_service import normalize_rate

PROVIDER_ADAPTER_VERSION = "public-structural-v2-forecast-provider-v1"


@dataclass(frozen=True)
class PublicForecastRequest:
    """Provider에 전달 가능한 public 계산입력만 보관한다."""

    generated_at: str
    candidate_rates: tuple[float, ...]
    baseline_new_money: float
    maturity_amount: float
    current_rollover_rate_pct: float
    current_own_rate: float
    term_months: int


class ForecastProvider(Protocol):
    """Private metadata를 노출하지 않는 forecast provider callable 계약."""

    def __call__(self, request: PublicForecastRequest) -> dict[str, Any]: ...


class ForecastProviderUnavailable(RuntimeError):
    """Provider가 정상적으로 결과를 제공할 수 없음을 명시적으로 알린다."""


def _normalized_expected_rates(request: PublicForecastRequest) -> list[float]:
    if not request.candidate_rates:
        raise ValueError("forecast_provider:candidate_rates_required")

    normalized = [normalize_rate(rate) for rate in request.candidate_rates]
    if len(set(normalized)) != len(normalized):
        raise ValueError("forecast_provider:candidate_rates_duplicate")
    return [float(rate) for rate in sorted(normalized)]


def _validate_rate_axis(
    payload: dict[str, Any],
    *,
    expected_rates: list[float],
) -> None:
    if payload["status"] == "unavailable":
        return

    actual = [float(normalize_rate(row["rate_pct"])) for row in payload["scenarios"]]
    if len(set(actual)) != len(actual):
        raise ValueError("forecast_provider:scenario_rates_duplicate")
    if actual != expected_rates:
        raise ValueError("forecast_provider:scenario_rate_axis_mismatch")


def unavailable_public_forecast(*, generated_at: str) -> dict[str, Any]:
    """명시적 provider unavailable을 strict public payload로 표현한다."""
    timestamp = str(generated_at or "").strip()
    if not timestamp:
        raise ValueError("forecast_provider:generated_at_required")
    payload = {
        "version": PUBLIC_FORECAST_CONTRACT_VERSION,
        "generated_at": timestamp,
        "status": "unavailable",
        "amount_unit": PUBLIC_AMOUNT_UNIT,
        "rate_unit": PUBLIC_RATE_UNIT,
        "scenarios": [],
    }
    validate_public_forecast_payload(payload)
    return payload


def public_structural_forecast_provider(
    request: PublicForecastRequest,
) -> dict[str, Any]:
    """현재 Public Structural v2 계산기를 provider 구현체로 감싼다."""
    return build_public_structural_v2_forecast(
        generated_at=request.generated_at,
        candidate_rates=list(request.candidate_rates),
        baseline_new_money=request.baseline_new_money,
        maturity_amount=request.maturity_amount,
        current_rollover_rate_pct=request.current_rollover_rate_pct,
        current_own_rate=request.current_own_rate,
        term_months=request.term_months,
    )


def resolve_public_forecast(
    *,
    request: PublicForecastRequest,
    provider: ForecastProvider | None = None,
) -> dict[str, Any]:
    """Provider 결과를 public allowlist와 candidate rate axis로 fail-closed 검증한다."""
    expected_rates = _normalized_expected_rates(request)
    active_provider = provider or public_structural_forecast_provider

    try:
        payload = active_provider(request)
    except ForecastProviderUnavailable:
        return unavailable_public_forecast(generated_at=request.generated_at)

    validated = validate_public_forecast_payload(payload)
    _validate_rate_axis(validated, expected_rates=expected_rates)
    return validated
