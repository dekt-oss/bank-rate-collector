from __future__ import annotations

import json
import math
import shutil
import subprocess
from pathlib import Path

import pytest

from rate_monitor.services.public_structural_v2_inflow_service import (
    predict_structural_v2_range,
    public_structural_v2_config,
)

ROOT = Path(__file__).resolve().parents[1]
VECTORS = ROOT / "tests" / "data" / "public_structural_v2_inflow_vectors.json"
JS_ENGINE = ROOT / "web" / "public-structural-v2" / "inflow_engine.js"
FIELDS = (
    "predicted_new_money",
    "predicted_rollover_rate_pct",
    "predicted_rollover",
    "predicted_total",
    "incremental_total",
    "surface_interest_delta",
)


def _load_vectors() -> list[dict]:
    payload = json.loads(VECTORS.read_text(encoding="utf-8"))
    assert payload["version"] == "public-structural-v2-inflow-v1"
    vectors = payload["vectors"]
    assert vectors
    return vectors


def _node_results(vectors: list[dict], *, drift: bool = False) -> list[dict]:
    node = shutil.which("node")
    assert node is not None, "Public Structural v2 parity에는 node가 필요합니다"

    config = public_structural_v2_config()
    script = JS_ENGINE.read_text(encoding="utf-8")
    if drift:
        marker = "scenario.new_money_log_change_per_10bp*rateSteps"
        assert marker in script
        script = script.replace(
            marker,
            "(scenario.new_money_log_change_per_10bp+0.001)*rateSteps",
            1,
        )

    harness = "\n".join(
        [
            script,
            f"const config={json.dumps(config, ensure_ascii=False)};",
            f"const vectors={json.dumps(vectors, ensure_ascii=False)};",
            "const out=vectors.map(v=>({name:v.name,result:PublicStructuralV2Inflow.predictRange(v.inputs,config)}));",
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
    for key in ("low", "base", "high"):
        for field in FIELDS:
            assert math.isclose(
                float(actual["scenarios"][key][field]),
                float(expected["scenarios"][key][field]),
                rel_tol=1e-9,
                abs_tol=1e-9,
            ), f"{context}.{key}.{field}"
    assert actual["predicted_total_range"] == expected["predicted_total_range"]


def test_node_mirror_matches_python_for_all_v2_vectors() -> None:
    vectors = _load_vectors()
    python_results = {
        vector["name"]: predict_structural_v2_range(**vector["inputs"])
        for vector in vectors
    }

    for row in _node_results(vectors):
        _assert_same(
            row["result"],
            python_results[row["name"]],
            context=row["name"],
        )


def test_deliberate_one_sided_js_drift_is_rejected() -> None:
    vector = next(v for v in _load_vectors() if v["name"] == "plus_10bp_60pct")
    expected = predict_structural_v2_range(**vector["inputs"])
    actual = _node_results([vector], drift=True)[0]["result"]

    with pytest.raises(AssertionError):
        _assert_same(actual, expected, context="deliberate-drift")
