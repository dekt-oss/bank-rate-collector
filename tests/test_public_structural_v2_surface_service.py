from __future__ import annotations

from rate_monitor.services.public_structural_v2_surface_service import (
    DISCLOSURE,
    build_public_structural_v2_surface,
)


def _market_rows() -> list[dict]:
    return [
        {"product_id": "top", "rate": 3.70},
        {"product_id": "peer-a", "rate": 3.60},
        {"product_id": "peer-b", "rate": 3.55},
        {"product_id": "anchor", "rate": 3.50},
        {"product_id": "peer-c", "rate": 3.45},
    ]


def _surface(**overrides):
    args = {
        "generated_at": "2026-08-22T17:00:00+09:00",
        "market_rows": _market_rows(),
        "anchor_product_id": "anchor",
        "current_own_rate": 3.50,
        "proposal_rate": 3.60,
        "economics_min_rate": 3.40,
        "economics_max_rate": 3.70,
        "baseline_new_money": 100.0,
        "maturity_amount": 200.0,
        "current_rollover_rate_pct": 60.0,
        "term_months": 12,
    }
    args.update(overrides)
    return build_public_structural_v2_surface(**args)


def test_surface_keeps_market_and_structural_sections_separate() -> None:
    surface = _surface()

    assert surface["version"] == "public-structural-v2-decision-surface-v1"
    assert surface["range_semantics"] == "uncalibrated_stress_range_not_prediction_interval"
    assert surface["market_amount_relation"] == (
        "separate_no_direct_market_effect_in_amount_formula"
    )
    assert surface["disclosure"] == DISCLOSURE
    assert "시장 순위·밀집도 변화는 금액식에 직접 반영되지 않습니다" in DISCLOSURE
    assert surface["market_positions"]
    assert surface["forecast"]["status"] == "ready"


def test_surface_uses_same_rate_axis_for_position_and_sanitized_forecast() -> None:
    surface = _surface(proposal_rate=3.63)

    position_rates = [row["proposal_rate"] for row in surface["market_positions"]]
    forecast_rates = [row["rate_pct"] for row in surface["forecast"]["scenarios"]]
    assert position_rates == forecast_rates
    assert 3.63 in position_rates
    assert surface["candidate_set"]["proposal_on_economics_grid"] is False


def test_surface_does_not_expose_structural_private_or_raw_formula_fields() -> None:
    serialized = repr(_surface()).lower()

    for forbidden in (
        "new_money_log_change_per_10bp",
        "rollover_log_odds_change_per_10bp",
        "raw_new_money_log_effect",
        "applied_new_money_log_effect",
        "coefficient_provenance",
        "training",
        "feature_importance",
        "private_model",
    ):
        assert forbidden not in serialized


def test_market_rank_changes_independently_from_amount_disclosure_contract() -> None:
    low_market = _surface(
        market_rows=[
            {"product_id": "a", "rate": 3.45},
            {"product_id": "anchor", "rate": 3.50},
            {"product_id": "b", "rate": 3.40},
        ]
    )
    high_market = _surface(
        market_rows=[
            {"product_id": "a", "rate": 3.95},
            {"product_id": "anchor", "rate": 3.50},
            {"product_id": "b", "rate": 3.90},
        ]
    )

    low_proposal = next(
        row for row in low_market["market_positions"] if row["proposal_rate"] == 3.60
    )
    high_proposal = next(
        row for row in high_market["market_positions"] if row["proposal_rate"] == 3.60
    )
    low_forecast = next(
        row for row in low_market["forecast"]["scenarios"] if row["rate_pct"] == 3.60
    )
    high_forecast = next(
        row for row in high_market["forecast"]["scenarios"] if row["rate_pct"] == 3.60
    )

    assert low_proposal["rank_best"] != high_proposal["rank_best"]
    assert low_forecast == high_forecast
