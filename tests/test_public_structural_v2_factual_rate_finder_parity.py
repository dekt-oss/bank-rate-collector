from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from rate_monitor.services.public_structural_v2_factual_rate_finder_service import (
    factual_rate_constraints,
)

ROOT = Path(__file__).resolve().parents[1]
JS_ENGINE = ROOT / "web" / "public-structural-v2" / "factual_rate_finder.js"


def _cases() -> list[dict]:
    return [
        {
            "name": "exact-grid",
            "args": {
                "rows": [
                    {"product_id": "anchor", "rate": 3.5},
                    {"product_id": "p1", "rate": 3.8},
                    {"product_id": "p2", "rate": 3.75},
                    {"product_id": "p3", "rate": 3.7},
                    {"product_id": "p4", "rate": 3.65},
                ],
                "anchor_product_id": "anchor",
                "current_own_rate": 3.5,
                "selection_step_pp": 0.01,
            },
        },
        {
            "name": "off-grid-market-max",
            "args": {
                "rows": [
                    {"product_id": "anchor", "rate": 3.5},
                    {"product_id": "p1", "rate": 3.8015},
                    {"product_id": "p2", "rate": 3.7555},
                    {"product_id": "p3", "rate": 3.7015},
                    {"product_id": "p4", "rate": 3.6555},
                ],
                "anchor_product_id": "anchor",
                "current_own_rate": 3.5,
                "selection_step_pp": 0.01,
            },
        },
        {
            "name": "half-bp-ui-grid",
            "args": {
                "rows": [
                    {"product_id": "anchor", "rate": 3.5},
                    {"product_id": "p1", "rate": 3.805},
                    {"product_id": "p2", "rate": 3.755},
                    {"product_id": "p3", "rate": 3.705},
                    {"product_id": "p4", "rate": 3.655},
                ],
                "anchor_product_id": "anchor",
                "current_own_rate": 3.5,
                "selection_step_pp": 0.005,
            },
        },
    ]


def _run_node(cases: list[dict], *, drift: bool = False) -> list[dict]:
    node = shutil.which("node")
    assert node is not None, "Stage G parity에는 node가 필요합니다"
    script = JS_ENGINE.read_text(encoding="utf-8")
    if drift:
        marker = "marketMaxUnits%stepUnits===0?marketMaxUnits:null"
        assert marker in script
        script = script.replace(marker, "marketMaxUnits", 1)
    harness = "\n".join(
        [
            script,
            f"const cases={json.dumps(cases, ensure_ascii=False)};",
            (
                "const out=cases.map(c=>({name:c.name,result:"
                "PublicStructuralV2FactualRateFinder.factualRateConstraints(c.args)}));"
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


def test_stage_g_js_matches_python_for_exact_and_off_grid_cases() -> None:
    cases = _cases()
    expected = {
        case["name"]: factual_rate_constraints(**case["args"])
        for case in cases
    }

    for row in _run_node(cases):
        assert row["result"] == expected[row["name"]], row["name"]


def test_stage_g_deliberate_off_grid_tie_drift_is_rejected() -> None:
    case = next(case for case in _cases() if case["name"] == "off-grid-market-max")
    expected = factual_rate_constraints(**case["args"])
    actual = _run_node([case], drift=True)[0]["result"]

    with pytest.raises(AssertionError):
        assert actual == expected


def test_stage_g_js_fails_closed_for_invalid_contracts() -> None:
    node = shutil.which("node")
    assert node is not None
    script = JS_ENGINE.read_text(encoding="utf-8")
    invalid = [
        {
            "rows": [{"product_id": "anchor", "rate": 3.5}],
            "anchor_product_id": "anchor",
            "current_own_rate": 3.5,
        },
        {
            "rows": [
                {"product_id": "anchor", "rate": 3.5},
                {"product_id": "p", "rate": 3.8},
            ],
            "anchor_product_id": "anchor",
            "current_own_rate": 3.51,
        },
        {
            "rows": [
                {"product_id": "anchor", "rate": 3.5},
                {"product_id": "p", "rate": 3.8},
            ],
            "anchor_product_id": "anchor",
            "current_own_rate": 3.5,
            "selection_step_pp": 0.00015,
        },
    ]
    harness = "\n".join(
        [
            script,
            f"const cases={json.dumps(invalid, ensure_ascii=False)};",
            (
                "const out=cases.map(args=>{try{"
                "PublicStructuralV2FactualRateFinder.factualRateConstraints(args);return 'accepted';}"
                "catch(error){return String(error.message||error);}});"
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
    errors = json.loads(completed.stdout)
    assert all(error != "accepted" for error in errors)
