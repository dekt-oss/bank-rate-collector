from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from rate_monitor.services.public_structural_v2_decision_contract import (
    build_candidate_rate_sets,
    build_public_structural_v2_forecast,
)
from rate_monitor.services.public_structural_v2_inflow_service import public_structural_v2_config

ROOT = Path(__file__).resolve().parents[1]
INFLOW_JS = ROOT / "web" / "public-structural-v2" / "inflow_engine.js"
DECISION_JS = ROOT / "web" / "public-structural-v2" / "decision_contract.js"


def _run_node(script_body: str) -> dict:
    node = shutil.which("node")
    assert node is not None, "Decision contract parity에는 node가 필요합니다"
    source = "\n".join(
        [
            INFLOW_JS.read_text(encoding="utf-8"),
            DECISION_JS.read_text(encoding="utf-8"),
            script_body,
        ]
    )
    completed = subprocess.run(
        [node, "-e", source],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_candidate_rate_set_js_matches_python() -> None:
    args = {
        "current_rate": 3.50,
        "proposal_rate": 3.63,
        "top25_cutoff": 3.57,
        "top10_cutoff": 3.68,
        "market_max_rate": 3.77,
        "economics_min_rate": 3.40,
        "economics_max_rate": 3.70,
    }
    expected = build_candidate_rate_sets(**args)
    body = "\n".join(
        [
            f"const args={json.dumps(args)};",
            (
                "const out=PublicStructuralV2DecisionContract."
                "buildCandidateRateSets(args);"
            ),
            "process.stdout.write(JSON.stringify(out));",
        ]
    )

    assert _run_node(body) == expected


def test_public_forecast_js_matches_python_sanitized_shape() -> None:
    args = {
        "generated_at": "2026-08-22T17:00:00+09:00",
        "candidate_rates": [3.40, 3.50, 3.60],
        "baseline_new_money": 100.0,
        "maturity_amount": 200.0,
        "current_rollover_rate_pct": 60.0,
        "current_own_rate": 3.50,
        "term_months": 12,
    }
    expected = build_public_structural_v2_forecast(**args)
    config = public_structural_v2_config()
    body = "\n".join(
        [
            f"const args={json.dumps(args)};",
            f"const config={json.dumps(config, ensure_ascii=False)};",
            (
                "const out=PublicStructuralV2DecisionContract.buildPublicForecast("
                "args,PublicStructuralV2Inflow,config);"
            ),
            "process.stdout.write(JSON.stringify(out));",
        ]
    )

    assert _run_node(body) == expected
