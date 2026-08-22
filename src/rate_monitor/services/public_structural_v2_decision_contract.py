"""Public Structural v2의 후보금리와 공개 forecast adapter.

factual market marker와 고정 5bp economics grid를 분리한다. Structural provider의
내부 계산 결과는 #168 `inflow-public-forecast-v1` allowlist로 축소한 뒤에만 이후
Decision UX로 전달한다.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from rate_monitor.services.inflow_public_forecast_contract import (
    PUBLIC_AMOUNT_UNIT,
    PUBLIC_FORECAST_CONTRACT_VERSION,
    PUBLIC_RATE_UNIT,
    validate_public_forecast_payload,
)
from rate_monitor.services.public_structural_v2_inflow_service import (
    predict_structural_v2_range,
)
from rate_monitor.services.public_structural_v2_market_position_service import normalize_rate

FIXED_ECONOMICS_STEP_PP = Decimal("0.05")
CANDIDATE_SET_VERSION = "public-structural-v2-candidate-set-v1"


def _rate_float(value: Decimal) -> float:
    return float(value)


def build_candidate_rate_sets(
    *,
    current_rate: float,
    proposal_rate: float,
    top25_cutoff: float,
    top10_cutoff: float,
    market_max_rate: float,
    economics_min_rate: float,
    economics_max_rate: float,
) -> dict[str, Any]:
    """시장 reference marker와 고정 5bp economics grid를 분리해 반환한다."""
    current = normalize_rate(current_rate)
    proposal = normalize_rate(proposal_rate)
    minimum = normalize_rate(economics_min_rate)
    maximum = normalize_rate(economics_max_rate)
    if minimum > current or maximum < current or minimum > maximum:
        raise ValueError("economics range는 current_rate를 포함해야 한다")

    marker_inputs = (
        ("current", current),
        ("proposal", proposal),
        ("top25", normalize_rate(top25_cutoff)),
        ("top10", normalize_rate(top10_cutoff)),
        ("market_max", normalize_rate(market_max_rate)),
    )
    marker_groups: dict[Decimal, list[str]] = {}
    for label, rate in marker_inputs:
        marker_groups.setdefault(rate, []).append(label)
    factual_markers = [
        {"rate_pct": _rate_float(rate), "labels": labels}
        for rate, labels in sorted(marker_groups.items())
    ]

    grid: set[Decimal] = {current}
    rate = current - FIXED_ECONOMICS_STEP_PP
    while rate >= minimum:
        grid.add(rate)
        rate -= FIXED_ECONOMICS_STEP_PP
    rate = current + FIXED_ECONOMICS_STEP_PP
    while rate <= maximum:
        grid.add(rate)
        rate += FIXED_ECONOMICS_STEP_PP

    economics_grid = [_rate_float(rate) for rate in sorted(grid)]
    proposal_on_grid = proposal in grid

    return {
        "version": CANDIDATE_SET_VERSION,
        "fixed_step_bp": 5,
        "factual_markers": factual_markers,
        "economics_grid": economics_grid,
        "proposal_rate": _rate_float(proposal),
        "proposal_on_economics_grid": proposal_on_grid,
    }


def build_public_structural_v2_forecast(
    *,
    generated_at: str,
    candidate_rates: list[float],
    baseline_new_money: float,
    maturity_amount: float,
    current_rollover_rate_pct: float,
    current_own_rate: float,
    term_months: int,
) -> dict[str, Any]:
    """Public Structural v2 결과를 #168 공개 forecast shape로 변환한다."""
    timestamp = str(generated_at or "").strip()
    if not timestamp:
        raise ValueError("generated_at이 필요하다")
    if not candidate_rates:
        raise ValueError("candidate_rates가 필요하다")

    normalized_rates: list[Decimal] = []
    seen: set[Decimal] = set()
    for raw_rate in candidate_rates:
        rate = normalize_rate(raw_rate)
        if rate in seen:
            raise ValueError("candidate_rates에는 중복 금리가 없어야 한다")
        seen.add(rate)
        normalized_rates.append(rate)
    normalized_rates.sort()

    rows: list[dict[str, float]] = []
    for rate in normalized_rates:
        result = predict_structural_v2_range(
            baseline_new_money=baseline_new_money,
            maturity_amount=maturity_amount,
            current_rollover_rate_pct=current_rollover_rate_pct,
            current_own_rate=current_own_rate,
            proposed_rate=float(rate),
            term_months=term_months,
        )
        base = result["base"]
        bounds = result["predicted_total_range"]
        public_new = float(base["predicted_new_money"])
        public_rollover = float(base["predicted_rollover"])
        public_total = round(public_new + public_rollover, 4)
        public_incremental = round(public_total - float(base["baseline_total"]), 4)
        rows.append(
            {
                "rate_pct": float(rate),
                "predicted_new_money": public_new,
                "predicted_rollover": public_rollover,
                "predicted_total": public_total,
                "incremental_total": public_incremental,
                "surface_interest_delta": float(base["surface_interest_delta"]),
                "predicted_total_lower": float(bounds["min"]),
                "predicted_total_upper": float(bounds["max"]),
            }
        )

    payload = {
        "version": PUBLIC_FORECAST_CONTRACT_VERSION,
        "generated_at": timestamp,
        "status": "ready",
        "amount_unit": PUBLIC_AMOUNT_UNIT,
        "rate_unit": PUBLIC_RATE_UNIT,
        "scenarios": rows,
    }
    validate_public_forecast_payload(payload)
    return payload
