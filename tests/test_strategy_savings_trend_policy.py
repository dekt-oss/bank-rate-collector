from rate_monitor.services.strategy_savings_trend_policy import (
    build_savings_trend_display_policy,
)


def _history(
    installment_rates: list[float],
    flexible_rates: list[float],
    *,
    installment_count: int = 20,
    flexible_count: int = 20,
) -> dict:
    count = max(len(installment_rates), len(flexible_rates))
    dates = [f"2026-08-{20 + i:02d}" for i in range(count)]

    def points(rates: list[float], count: int) -> list[dict]:
        return [
            {
                "date": dates[i],
                "mean_max_rate": rate,
                "market_max_rate": rate + 0.2,
                "our_company_max_rate": None,
                "product_count": count,
            }
            for i, rate in enumerate(rates)
        ]

    return {
        "terms": [12],
        "scopes": {
            "savings_installment": {
                "12": {"rate_trend": {"points": points(installment_rates, installment_count)}}
            },
            "savings_flexible": {
                "12": {"rate_trend": {"points": points(flexible_rates, flexible_count)}}
            },
        },
    }


def test_small_gap_keeps_one_combined_savings_trend() -> None:
    policy = build_savings_trend_display_policy(
        _history([3.00, 3.02, 3.04], [3.04, 3.05, 3.06])
    )["terms"]["12"]

    assert policy["display_mode"] == "combined"
    assert policy["reason"] == "difference_not_material"
    assert policy["max_gap_pp"] < 0.20


def test_large_gap_splits_installment_and_flexible_trends() -> None:
    policy = build_savings_trend_display_policy(
        _history([3.00, 3.02, 3.05], [3.25, 3.28, 3.30])
    )["terms"]["12"]

    assert policy["display_mode"] == "split"
    assert policy["reason"] == "large_max_gap"
    assert policy["max_gap_pp"] >= 0.20


def test_material_average_gap_respects_minor_subtype_share() -> None:
    material = build_savings_trend_display_policy(
        _history(
            [3.00, 3.00, 3.00],
            [3.12, 3.12, 3.12],
            installment_count=80,
            flexible_count=20,
        )
    )["terms"]["12"]
    immaterial = build_savings_trend_display_policy(
        _history(
            [3.00, 3.00, 3.00],
            [3.12, 3.12, 3.12],
            installment_count=95,
            flexible_count=5,
        )
    )["terms"]["12"]

    assert material["display_mode"] == "split"
    assert material["reason"] == "material_mean_gap"
    assert immaterial["display_mode"] == "combined"


def test_opposite_material_directions_split_even_without_large_level_gap() -> None:
    policy = build_savings_trend_display_policy(
        _history([3.00, 3.05, 3.10], [3.10, 3.05, 3.00])
    )["terms"]["12"]

    assert policy["display_mode"] == "split"
    assert policy["reason"] == "divergent_direction"


def test_insufficient_overlap_fails_closed_to_combined() -> None:
    policy = build_savings_trend_display_policy(_history([3.00], [3.30]))["terms"]["12"]

    assert policy["display_mode"] == "combined"
    assert policy["reason"] == "insufficient_overlap"
    assert policy["overlap_points"] == 1
