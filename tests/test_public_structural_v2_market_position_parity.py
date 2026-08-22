from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from rate_monitor.services.public_structural_v2_market_position_service import (
    market_position,
    normalize_rate,
    public_market_position_config,
)

ROOT = Path(__file__).resolve().parents[1]
VECTORS = ROOT / "tests" / "data" / "public_structural_v2_market_position_vectors.json"
JS_ENGINE = ROOT / "web" / "public-structural-v2" / "market_position.js"
PARITY_FIELDS = (
    "universe_count",
    "proposal_rate",
    "rank_best",
    "rank_worst",
    "tie_competitor_count",
    "mean_rate",
    "median_rate",
    "top25_cutoff",
    "top10_cutoff",
    "market_max_rate",
    "gap_to_mean_bp",
    "gap_to_median_bp",
    "gap_to_top25_bp",
    "gap_to_top10_bp",
    "gap_to_market_max_bp",
    "exact_tie_count",
    "within_5bp_count",
    "within_10bp_count",
    "top25_reached",
    "top25_exceeded",
    "top10_reached",
    "top10_exceeded",
    "newly_outpriced",
    "newly_tied",
    "newly_lost_to",
    "newly_tied_down",
)


def _payloads() -> list[dict]:
    cases = json.loads(VECTORS.read_text(encoding="utf-8"))["cases"]
    payloads: list[dict] = []
    for case in cases:
        anchor_rate = normalize_rate(case["anchor_rate"])
        rows: list[dict] = []
        anchor_assigned = False
        serial = 0
        for cluster in case["clusters"]:
            for _ in range(int(cluster["count"])):
                rate = normalize_rate(cluster["rate"])
                if rate == anchor_rate and not anchor_assigned:
                    product_id = "anchor"
                    anchor_assigned = True
                else:
                    product_id = f"p-{serial}"
                    serial += 1
                rows.append({"product_id": product_id, "rate": float(rate)})
        payloads.append(
            {
                "name": case["name"],
                "args": {
                    "rows": rows,
                    "anchor_product_id": "anchor",
                    "current_own_rate": float(case["current_rate"]),
                    "proposal_rate": float(case["proposal_rate"]),
                },
            }
        )
    return payloads


def _run_node(payloads: list[dict], *, drift: bool = False) -> list[dict]:
    node = shutil.which("node")
    assert node is not None, "market-position parity에는 node가 필요합니다"
    script = JS_ENGINE.read_text(encoding="utf-8")
    if drift:
        marker = "competitorRates.filter(rate=>rate>proposal).length"
        assert marker in script
        script = script.replace(
            marker,
            "competitorRates.filter(rate=>rate>=proposal).length",
            1,
        )
    config = public_market_position_config()
    harness = "\n".join(
        [
            script,
            f"const config={json.dumps(config, ensure_ascii=False)};",
            f"const payloads={json.dumps(payloads, ensure_ascii=False)};",
            (
                "const out=payloads.map(p=>({name:p.name,result:"
                "PublicStructuralV2MarketPosition.marketPosition(p.args,config)}));"
            ),
            "process.stdout.write(JSON.stringify(out));",
        ]
    )
    completed = subprocess.run(
        [node, "-e", harness],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def _assert_same(actual: dict, expected: dict, *, context: str) -> None:
    for field in PARITY_FIELDS:
        assert actual[field] == expected[field], f"{context}.{field}"


def test_market_position_js_matches_python_for_all_a0_vectors() -> None:
    payloads = _payloads()
    expected = {
        payload["name"]: market_position(**payload["args"])
        for payload in payloads
    }

    for row in _run_node(payloads):
        _assert_same(row["result"], expected[row["name"]], context=row["name"])


def test_market_position_deliberate_rank_drift_is_rejected() -> None:
    payload = next(p for p in _payloads() if p["name"] == "dense_tie_raise_10bp")
    expected = market_position(**payload["args"])
    actual = _run_node([payload], drift=True)[0]["result"]

    with pytest.raises(AssertionError):
        _assert_same(actual, expected, context="deliberate-rank-drift")
