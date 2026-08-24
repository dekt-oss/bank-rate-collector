"""Strategy production release gate must stay OFF in every canonical site writer."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STRATEGY_GATE_OFF_ENV = 'RATE_MONITOR_STRATEGY_DASHBOARD: "0"'
STRATEGY_GATE_ON_ENV = 'RATE_MONITOR_STRATEGY_DASHBOARD: "1"'
PUBLISH_WORKFLOWS = (
    ".github/workflows/collect.yml",
    ".github/workflows/collect-savings-fast.yml",
    ".github/workflows/nh-attempt.yml",
)


def test_every_rate_data_writer_keeps_strategy_gate_off() -> None:
    for relative in PUBLISH_WORKFLOWS:
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert STRATEGY_GATE_OFF_ENV in text, relative
        assert STRATEGY_GATE_ON_ENV not in text, relative
        assert "rate-monitor build-site" in text, relative
        assert "cp -r site-public" in text, relative


def test_production_smoke_verifies_off_after_every_site_writer() -> None:
    workflow = (ROOT / ".github/workflows/production-smoke.yml").read_text(encoding="utf-8")
    for workflow_name in (
        "수집 — 일반·새마을금고",
        "Collect bank rates fast",
        "수집 — 농·축협",
    ):
        assert workflow_name in workflow

    smoke = (ROOT / "scripts/production_smoke.py").read_text(encoding="utf-8")
    assert "STRATEGY_PUBLIC_FILES" in smoke
    assert "_require_strategy_absent" in smoke
    assert "_expect_absent(strategy_url" in smoke
    assert "strategy_gate=off" in smoke
