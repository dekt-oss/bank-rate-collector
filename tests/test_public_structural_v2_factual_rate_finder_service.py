from __future__ import annotations

import pytest

from rate_monitor.services.public_structural_v2_factual_rate_finder_service import (
    BENCHMARK_UNIVERSE,
    FACTUAL_RATE_FINDER_VERSION,
    competitor_market_benchmarks,
    factual_rate_constraints,
)


def _rows(*rates: float, anchor_rate: float = 3.50) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = [{"product_id": "anchor", "rate": anchor_rate}]
    rows.extend({"product_id": f"p-{index}", "rate": rate} for index, rate in enumerate(rates))
    return rows


def _condition(result: dict, target: str, relation: str) -> dict:
    return next(
        row
        for row in result["conditions"]
        if row["target"] == target and row["relation"] == relation
    )


def test_factual_constraints_use_competitor_only_benchmarks() -> None:
    rows = _rows(3.80, 3.75, 3.70, 3.65, 3.60, 3.55, 3.50, 3.45, 3.40, 3.35)

    benchmarks = competitor_market_benchmarks(
        rows=rows,
        anchor_product_id="anchor",
        current_own_rate=3.50,
    )
    result = factual_rate_constraints(
        rows=rows,
        anchor_product_id="anchor",
        current_own_rate=3.50,
    )

    assert benchmarks == {
        "benchmark_universe": BENCHMARK_UNIVERSE,
        "competitor_count": 10,
        "top10_cutoff": 3.8,
        "top25_cutoff": 3.7,
        "market_max_rate": 3.8,
    }
    assert result["version"] == FACTUAL_RATE_FINDER_VERSION
    assert result["benchmark_universe"] == BENCHMARK_UNIVERSE
    assert result["competitor_count"] == 10
    assert result["selection_step_pp"] == 0.01
    assert result["selection_step_bp"] == 1.0
    assert _condition(result, "top10", "reach")["minimum_selectable_rate_pct"] == 3.8
    assert _condition(result, "top10", "exceed")["minimum_selectable_rate_pct"] == 3.81
    assert _condition(result, "top25", "reach")["minimum_selectable_rate_pct"] == 3.7
    assert _condition(result, "top25", "exceed")["minimum_selectable_rate_pct"] == 3.71
    assert _condition(result, "market_max", "tie")["minimum_selectable_rate_pct"] == 3.8
    assert _condition(result, "market_max", "exceed")["minimum_selectable_rate_pct"] == 3.81


def test_off_grid_market_max_preserves_exact_tie_unavailable() -> None:
    rows = _rows(3.8015, 3.75, 3.70, 3.65, 3.60, 3.55, 3.50, 3.45, 3.40, 3.35)

    result = factual_rate_constraints(
        rows=rows,
        anchor_product_id="anchor",
        current_own_rate=3.50,
    )

    top10_reach = _condition(result, "top10", "reach")
    top10_exceed = _condition(result, "top10", "exceed")
    market_tie = _condition(result, "market_max", "tie")
    market_exceed = _condition(result, "market_max", "exceed")

    assert top10_reach["benchmark_rate_pct"] == 3.8015
    assert top10_reach["minimum_selectable_rate_pct"] == 3.81
    assert top10_exceed["minimum_selectable_rate_pct"] == 3.81
    assert market_tie == {
        "target": "market_max",
        "relation": "tie",
        "label": "시장 최고 동률",
        "benchmark_rate_pct": 3.8015,
        "status": "unavailable",
        "reason": "exact_tie_not_selectable_on_ui_grid",
    }
    assert market_exceed["minimum_selectable_rate_pct"] == 3.81


def test_selection_step_is_ui_granularity_and_can_be_changed_explicitly() -> None:
    rows = _rows(3.805, 3.75, 3.70, 3.65)

    result = factual_rate_constraints(
        rows=rows,
        anchor_product_id="anchor",
        current_own_rate=3.50,
        selection_step_pp=0.005,
    )

    assert result["selection_step_pp"] == 0.005
    assert result["selection_step_bp"] == 0.5
    assert _condition(result, "market_max", "tie")["minimum_selectable_rate_pct"] == 3.805
    assert _condition(result, "market_max", "exceed")["minimum_selectable_rate_pct"] == 3.81


def test_finder_fails_closed_on_bad_market_contracts() -> None:
    with pytest.raises(ValueError, match="정확히 1개"):
        factual_rate_constraints(
            rows=_rows(3.8, 3.7),
            anchor_product_id="missing",
            current_own_rate=3.50,
        )

    with pytest.raises(ValueError, match="current_own_rate"):
        factual_rate_constraints(
            rows=_rows(3.8, 3.7),
            anchor_product_id="anchor",
            current_own_rate=3.51,
        )

    with pytest.raises(ValueError, match="duplicate product_id"):
        factual_rate_constraints(
            rows=[
                {"product_id": "anchor", "rate": 3.50},
                {"product_id": "p", "rate": 3.80},
                {"product_id": "p", "rate": 3.70},
            ],
            anchor_product_id="anchor",
            current_own_rate=3.50,
        )

    with pytest.raises(ValueError, match="비교상품이 없다"):
        factual_rate_constraints(
            rows=[{"product_id": "anchor", "rate": 3.50}],
            anchor_product_id="anchor",
            current_own_rate=3.50,
        )


@pytest.mark.parametrize("step", [0, -0.01, 0.00015, 1000])
def test_invalid_selection_step_is_rejected(step: float) -> None:
    with pytest.raises(ValueError):
        factual_rate_constraints(
            rows=_rows(3.8, 3.7),
            anchor_product_id="anchor",
            current_own_rate=3.50,
            selection_step_pp=step,
        )
