"""Strategy production release must survive every canonical site writer."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STRATEGY_RELEASE_ENV = 'RATE_MONITOR_STRATEGY_DASHBOARD: "1"'
PUBLISH_WORKFLOWS = (
    ".github/workflows/collect.yml",
    ".github/workflows/collect-savings-fast.yml",
    ".github/workflows/nh-attempt.yml",
)


def test_every_rate_data_writer_publishes_strategy() -> None:
    for relative in PUBLISH_WORKFLOWS:
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert STRATEGY_RELEASE_ENV in text, relative
        assert "rate-monitor build-site" in text, relative
        assert "cp -r site-public" in text, relative


def test_production_smoke_runs_after_every_site_writer() -> None:
    text = (ROOT / ".github/workflows/production-smoke.yml").read_text(encoding="utf-8")
    for workflow_name in (
        "수집 — 일반·새마을금고",
        "Collect bank rates fast",
        "수집 — 농·축협",
    ):
        assert workflow_name in text

    assert "strategy.html" in (ROOT / "scripts/production_smoke.py").read_text(
        encoding="utf-8"
    )
