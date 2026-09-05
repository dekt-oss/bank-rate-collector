from __future__ import annotations

import json
import subprocess
from pathlib import Path


TARGET_CANDIDATE = Path("web/public-structural-v2/target_candidate.js")


def run_selector(scenarios: list[dict[str, float]], target: float) -> dict[str, object]:
    script = f"""
const selector = require('./{TARGET_CANDIDATE.as_posix()}');
const result = selector.findFirstCandidate({json.dumps(scenarios)}, {target});
process.stdout.write(JSON.stringify(result));
"""
    completed = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_selects_lowest_existing_rate_that_meets_target() -> None:
    result = run_selector(
        [
            {"rate_pct": 3.55, "predicted_total": 118},
            {"rate_pct": 3.45, "predicted_total": 101},
            {"rate_pct": 3.50, "predicted_total": 110},
        ],
        109,
    )

    assert result["status"] == "ready"
    assert result["rate_pct"] == 3.50
    assert result["predicted_total"] == 110
    assert result["selection_semantics"] == (
        "first_existing_candidate_meeting_target_no_interpolation"
    )


def test_does_not_interpolate_between_candidates() -> None:
    result = run_selector(
        [
            {"rate_pct": 3.45, "predicted_total": 100},
            {"rate_pct": 3.50, "predicted_total": 120},
        ],
        110,
    )

    assert result["rate_pct"] == 3.50


def test_returns_out_of_support_above_surface_max() -> None:
    result = run_selector(
        [
            {"rate_pct": 3.45, "predicted_total": 100},
            {"rate_pct": 3.50, "predicted_total": 120},
        ],
        121,
    )

    assert result == {
        "version": "strategy-target-candidate-v1",
        "status": "out_of_support",
        "reason": "target_above_surface_max",
        "target_total": 121,
        "max_candidate_total": 120,
    }


def test_rejects_invalid_target_and_empty_surface() -> None:
    invalid = run_selector([{"rate_pct": 3.5, "predicted_total": 100}], -1)
    empty = run_selector([], 100)

    assert invalid["status"] == "unavailable"
    assert invalid["reason"] == "target_invalid"
    assert empty["status"] == "unavailable"
    assert empty["reason"] == "surface_empty"
