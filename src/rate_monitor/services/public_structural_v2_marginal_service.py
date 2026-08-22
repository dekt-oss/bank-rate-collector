"""Public Structural v2의 고정 5bp marginal surface-cost 계산.

시장 threshold/proposal 같은 임의 간격 점은 marginal step에 섞지 않는다.
현재 단계에서는 구조적 추가수신과 표면이자비용의 변화액만 공개하며,
불안정한 비율·연환산 한계조달금리·FTP 해석은 만들지 않는다.
"""

from __future__ import annotations

from decimal import Decimal
from itertools import pairwise
from typing import Any

from rate_monitor.services.public_structural_v2_market_position_service import normalize_rate

MARGINAL_VERSION = "public-structural-v2-marginal-v1"
FIXED_STEP_PP = Decimal("0.05")


def build_fixed_5bp_marginals(surface: dict[str, Any]) -> dict[str, Any]:
    """Decision Surface의 economics grid 인접점 사이 변화액만 계산한다."""
    candidate_set = surface.get("candidate_set") or {}
    forecast = surface.get("forecast") or {}
    grid = [normalize_rate(rate) for rate in candidate_set.get("economics_grid") or []]
    scenarios = forecast.get("scenarios") or []
    if len(grid) < 2:
        raise ValueError("economics_grid는 최소 2개 금리가 필요하다")
    if not scenarios:
        raise ValueError("forecast scenarios가 필요하다")

    ordered = sorted(grid)
    adjacent_pairs = list(pairwise(ordered))
    if any(right - left != FIXED_STEP_PP for left, right in adjacent_pairs):
        raise ValueError("marginal은 정확히 5bp 인접점에서만 계산한다")

    by_rate = {normalize_rate(row["rate_pct"]): row for row in scenarios}
    missing = [rate for rate in grid if rate not in by_rate]
    if missing:
        raise ValueError("economics_grid와 forecast rate가 일치하지 않는다")

    marginals: list[dict[str, float | int]] = []
    for left, right in adjacent_pairs:
        before = by_rate[left]
        after = by_rate[right]
        delta_total = round(
            float(after["predicted_total"]) - float(before["predicted_total"]),
            4,
        )
        delta_surface_interest = round(
            float(after["surface_interest_delta"])
            - float(before["surface_interest_delta"]),
            4,
        )
        marginals.append(
            {
                "from_rate_pct": float(left),
                "to_rate_pct": float(right),
                "step_bp": 5,
                "structural_total_delta": delta_total,
                "surface_interest_delta": delta_surface_interest,
            }
        )

    return {
        "version": MARGINAL_VERSION,
        "step_bp": 5,
        "ratio_metric_status": "not_exposed_uncalibrated_denominator",
        "annualized_marginal_rate_status": "not_exposed",
        "marginals": marginals,
    }
