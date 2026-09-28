from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "web" / "public-structural-v2" / "enrollment_filter.js"


def _run(rows: list[dict]) -> list[dict]:
    node = shutil.which("node")
    assert node is not None, "가입방식 browser contract 검증에는 node가 필요합니다"
    script = """
const f=require(process.argv[1]);
const rows=JSON.parse(process.argv[2]);
process.stdout.write(JSON.stringify(rows.map(row=>({
  classification:f.classify(row),
  all:f.matches(row,"all"),
  remote:f.matches(row,"remote"),
  face:f.matches(row,"face")
}))));
""".strip()
    completed = subprocess.run(
        [node, "-e", script, str(MODULE), json.dumps(rows, ensure_ascii=False)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        ({"join_channel": "branch", "product": "정기예금"}, "face"),
        ({"join_channel": "agent", "product": "정기예금"}, "face"),
        ({"join_channel": "internet", "product": "정기예금"}, "remote"),
        ({"join_channel": "mobile", "product": "정기예금"}, "remote"),
        ({"join_channel": "any", "product": "GPS 정기예금(비대면)"}, "remote"),
        ({"join_channel": "any", "product": "Fi 정기예금 (대면)"}, "face"),
        (
            {
                "join_channel": "unknown",
                "product": "정기예금",
                "preference_tags": "DIGITAL_CHANNEL",
            },
            "remote",
        ),
        ({"join_channel": "any", "product": "정기예금"}, "unknown"),
        ({"join_channel": "unknown", "product": "정기예금"}, "unknown"),
    ],
)
def test_enrollment_filter_classifies_only_explicit_evidence(row: dict, expected: str) -> None:
    [result] = _run([row])
    assert result["classification"]["mode"] == expected
    assert result["all"] is True
    assert result["remote"] is (expected == "remote")
    assert result["face"] is (expected == "face")


def test_enrollment_filter_fails_closed_on_conflicting_product_copy() -> None:
    [result] = _run(
        [{"join_channel": "any", "product": "대면/비대면 동시 가능 정기예금"}]
    )
    assert result["classification"]["mode"] == "unknown"
    assert result["remote"] is False
    assert result["face"] is False
