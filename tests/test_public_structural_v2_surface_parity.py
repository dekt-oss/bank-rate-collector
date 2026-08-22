from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from rate_monitor.services.public_structural_v2_inflow_service import public_structural_v2_config
from rate_monitor.services.public_structural_v2_market_position_service import (
    public_market_position_config,
)
from rate_monitor.services.public_structural_v2_surface_service import (
    build_public_structural_v2_surface,
)

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web" / "public-structural-v2"


def test_surface_js_matches_python_view_model() -> None:
    node = shutil.which("node")
    assert node is not None, "surface parity에는 node가 필요합니다"
    args = {
        "generated_at": "2026-08-22T17:00:00+09:00",
        "market_rows": [
            {"product_id": "top", "rate": 3.70},
            {"product_id": "peer-a", "rate": 3.60},
            {"product_id": "peer-b", "rate": 3.55},
            {"product_id": "anchor", "rate": 3.50},
            {"product_id": "peer-c", "rate": 3.45},
        ],
        "anchor_product_id": "anchor",
        "current_own_rate": 3.50,
        "proposal_rate": 3.63,
        "economics_min_rate": 3.40,
        "economics_max_rate": 3.70,
        "baseline_new_money": 100.0,
        "maturity_amount": 200.0,
        "current_rollover_rate_pct": 60.0,
        "term_months": 12,
    }
    expected = build_public_structural_v2_surface(**args)
    sources = [
        (WEB / "inflow_engine.js").read_text(encoding="utf-8"),
        (WEB / "market_position.js").read_text(encoding="utf-8"),
        (WEB / "decision_contract.js").read_text(encoding="utf-8"),
        (WEB / "surface.js").read_text(encoding="utf-8"),
        f"const args={json.dumps(args, ensure_ascii=False)};",
        f"const marketConfig={json.dumps(public_market_position_config())};",
        f"const inflowConfig={json.dumps(public_structural_v2_config(), ensure_ascii=False)};",
        (
            "const out=PublicStructuralV2Surface.buildSurface(args,"
            "PublicStructuralV2MarketPosition,marketConfig,"
            "PublicStructuralV2DecisionContract,PublicStructuralV2Inflow,inflowConfig);"
        ),
        "process.stdout.write(JSON.stringify(out));",
    ]
    completed = subprocess.run(
        [node, "-e", "\n".join(sources)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == expected
