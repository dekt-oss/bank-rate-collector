"""적금 전체 추이를 통합/분리 표시할지 실제 이력 차이로 판정한다."""

from __future__ import annotations

from typing import Any

MIN_OVERLAP_POINTS = 2
LARGE_MAX_GAP_PP = 0.20
MATERIAL_MEAN_GAP_PP = 0.10
MATERIAL_MINOR_SHARE = 0.20
DIRECTION_DIVERGENCE_PP = 0.10


def _trend_points(
    product_history: dict[str, Any], scope_key: str, term: int
) -> dict[str, dict[str, Any]]:
    points = (
        product_history.get("scopes", {})
        .get(scope_key, {})
        .get(str(term), {})
        .get("rate_trend", {})
        .get("points", [])
    )
    result: dict[str, dict[str, Any]] = {}
    for point in points:
        date = str(point.get("date") or "")
        mean_rate = point.get("mean_max_rate")
        if not date or mean_rate is None:
            continue
        result[date] = point
    return result


def _term_policy(product_history: dict[str, Any], term: int) -> dict[str, Any]:
    installment = _trend_points(product_history, "savings_installment", term)
    flexible = _trend_points(product_history, "savings_flexible", term)
    overlap = sorted(set(installment) & set(flexible))
    base = {
        "display_mode": "combined",
        "reason": "insufficient_overlap",
        "overlap_points": len(overlap),
        "max_gap_pp": None,
        "mean_gap_pp": None,
        "minor_product_share": None,
        "installment_delta_pp": None,
        "flexible_delta_pp": None,
    }
    if len(overlap) < MIN_OVERLAP_POINTS:
        return base

    gaps: list[float] = []
    installment_counts: list[float] = []
    flexible_counts: list[float] = []
    installment_values: list[float] = []
    flexible_values: list[float] = []
    for date in overlap:
        installment_point = installment[date]
        flexible_point = flexible[date]
        installment_rate = float(installment_point["mean_max_rate"])
        flexible_rate = float(flexible_point["mean_max_rate"])
        installment_values.append(installment_rate)
        flexible_values.append(flexible_rate)
        gaps.append(abs(installment_rate - flexible_rate))
        installment_counts.append(float(installment_point.get("product_count") or 0))
        flexible_counts.append(float(flexible_point.get("product_count") or 0))

    max_gap = max(gaps)
    mean_gap = sum(gaps) / len(gaps)
    installment_count = sum(installment_counts) / len(installment_counts)
    flexible_count = sum(flexible_counts) / len(flexible_counts)
    total_count = installment_count + flexible_count
    minor_share = min(installment_count, flexible_count) / total_count if total_count else 0.0
    installment_delta = installment_values[-1] - installment_values[0]
    flexible_delta = flexible_values[-1] - flexible_values[0]
    opposite_direction = installment_delta * flexible_delta < 0
    direction_gap = abs(installment_delta - flexible_delta)

    large_gap = max_gap >= LARGE_MAX_GAP_PP
    material_gap = (
        mean_gap >= MATERIAL_MEAN_GAP_PP and minor_share >= MATERIAL_MINOR_SHARE
    )
    divergent_direction = (
        opposite_direction and direction_gap >= DIRECTION_DIVERGENCE_PP
    )
    split = large_gap or material_gap or divergent_direction
    if large_gap:
        reason = "large_max_gap"
    elif material_gap:
        reason = "material_mean_gap"
    elif divergent_direction:
        reason = "divergent_direction"
    else:
        reason = "difference_not_material"

    return {
        **base,
        "display_mode": "split" if split else "combined",
        "reason": reason,
        "max_gap_pp": round(max_gap, 4),
        "mean_gap_pp": round(mean_gap, 4),
        "minor_product_share": round(minor_share, 4),
        "installment_delta_pp": round(installment_delta, 4),
        "flexible_delta_pp": round(flexible_delta, 4),
    }


def build_savings_trend_display_policy(
    product_history: dict[str, Any],
) -> dict[str, Any]:
    """기간별 적금 전체 추이의 통합/분리 표시 정책을 계산한다."""
    terms = [int(term) for term in product_history.get("terms", [])]
    return {
        "version": "savings-trend-display-v1",
        "thresholds": {
            "min_overlap_points": MIN_OVERLAP_POINTS,
            "large_max_gap_pp": LARGE_MAX_GAP_PP,
            "material_mean_gap_pp": MATERIAL_MEAN_GAP_PP,
            "material_minor_share": MATERIAL_MINOR_SHARE,
            "direction_divergence_pp": DIRECTION_DIVERGENCE_PP,
        },
        "terms": {str(term): _term_policy(product_history, term) for term in terms},
    }
