from __future__ import annotations

import json
from pathlib import Path

import pytest

from rate_monitor.services.public_structural_v2_market_position_service import (
    market_position,
    normalize_rate,
    public_market_position_config,
)

ROOT = Path(__file__).resolve().parents[1]
VECTORS = ROOT / "tests" / "data" / "public_structural_v2_market_position_vectors.json"
EXPECTED_FIELDS = (
    "universe_count",
    "rank_best",
    "rank_worst",
    "tie_competitor_count",
    "top10_cutoff",
    "top25_cutoff",
    "newly_outpriced",
    "newly_tied",
    "newly_lost_to",
    "newly_tied_down",
)


def _load_cases() -> list[dict]:
    return json.loads(VECTORS.read_text(encoding="utf-8"))["cases"]


def _rows(case: dict) -> tuple[list[dict], str]:
    rows: list[dict] = []
    anchor_rate = normalize_rate(case["anchor_rate"])
    anchor_id = "anchor"
    anchor_assigned = False
    serial = 0
    for cluster in case["clusters"]:
        for _ in range(int(cluster["count"])):
            rate = normalize_rate(cluster["rate"])
            if rate == anchor_rate and not anchor_assigned:
                product_id = anchor_id
                anchor_assigned = True
            else:
                product_id = f"p-{serial}"
                serial += 1
            rows.append({"product_id": product_id, "rate": float(rate)})
    assert anchor_assigned
    return rows, anchor_id


def test_market_position_matches_all_a0_golden_vectors() -> None:
    for case in _load_cases():
        rows, anchor_id = _rows(case)
        actual = market_position(
            rows=rows,
            anchor_product_id=anchor_id,
            current_own_rate=float(case["current_rate"]),
            proposal_rate=float(case["proposal_rate"]),
        )
        for field in EXPECTED_FIELDS:
            expected = case["expected"][field]
            if field.endswith("cutoff"):
                expected = float(expected)
            assert actual[field] == expected, f"{case['name']}.{field}"


def test_market_position_config_is_grounded_in_storage_precision() -> None:
    config = public_market_position_config()

    assert config["version"] == "public-structural-v2-market-position-v1"
    assert config["rate_normalization_decimals"] == 4
    assert config["counterfactual"] == "replace_anchor_product"
    assert config["crowding_windows_pp"] == [0.05, 0.1]


def test_rate_normalization_distinguishes_fourth_decimal() -> None:
    assert normalize_rate("3.5450") != normalize_rate("3.5451")


def test_anchor_is_not_counted_as_a_competitor_after_replace() -> None:
    rows = [
        {"product_id": "anchor", "rate": 3.50},
        {"product_id": "peer", "rate": 3.50},
    ]
    result = market_position(
        rows=rows,
        anchor_product_id="anchor",
        current_own_rate=3.50,
        proposal_rate=3.55,
    )

    assert result["universe_count"] == 2
    assert result["newly_outpriced"] == 1
    assert result["exact_tie_count"] == 0


def test_crowding_counts_are_overlapping_not_additive() -> None:
    rows = [
        {"product_id": "anchor", "rate": 3.50},
        {"product_id": "tie", "rate": 3.55},
        {"product_id": "near", "rate": 3.60},
        {"product_id": "far", "rate": 3.70},
    ]
    result = market_position(
        rows=rows,
        anchor_product_id="anchor",
        current_own_rate=3.50,
        proposal_rate=3.55,
    )

    assert result["exact_tie_count"] == 1
    assert result["within_5bp_count"] == 2
    assert result["within_10bp_count"] == 2


@pytest.mark.parametrize(
    ("rows", "anchor", "current", "message"),
    [
        ([], "anchor", 3.50, "market rows"),
        ([{"product_id": "a", "rate": 3.5}], "missing", 3.50, "anchor_product_id"),
        (
            [
                {"product_id": "a", "rate": 3.5},
                {"product_id": "a", "rate": 3.6},
            ],
            "a",
            3.50,
            "duplicate product_id",
        ),
        ([{"product_id": "a", "rate": 3.5}], "a", 3.51, "anchor rate"),
    ],
)
def test_market_position_invalid_contracts_fail_closed(rows, anchor, current, message) -> None:
    with pytest.raises(ValueError, match=message):
        market_position(
            rows=rows,
            anchor_product_id=anchor,
            current_own_rate=current,
            proposal_rate=3.60,
        )
