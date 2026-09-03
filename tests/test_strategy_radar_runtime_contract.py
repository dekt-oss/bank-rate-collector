from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "strategy-ux-production-copy-e2e.yml"
RADAR_SMOKE = ROOT / "scripts" / "special_offer_radar_runtime_smoke.js"


def test_strategy_ux_production_copy_e2e_has_enough_runtime_and_radar_coverage() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert '"feat/strategy-ux-*"' in text
    assert "timeout-minutes: 40" in text
    assert "storage restore --dest work/rate_monitor.sqlite3" in text
    assert 'RATE_MONITOR_STRATEGY_DASHBOARD: "1"' in text
    assert "special_offer_radar_presentation.py" in text
    assert "special_offer_radar_runtime_smoke.js" in text
    assert 'grep -q \'id="special-offer-radar-style"\'' in text
    assert 'grep -q \'id="special-offer-radar-script"\'' in text
    assert 'RADAR_REQUIRE_LIVE_UNKNOWN: "0"' in text
    assert 'RADAR_REQUIRE_NO_CONFIRMED: "0"' in text
    assert "strategy_preview_smoke.js" in text
    assert "strategy_workspace_smoke.js" in text
    assert "strategy_main_runtime_external_context_smoke.js" in text
    assert "special-offer-radar-runtime-metrics.json" in text

    lower = text.lower()
    assert "uv run rate-monitor storage upload" not in text
    assert "\ngit push " not in lower
    assert "vercel deploy" not in lower
    assert "vercel --prod" not in lower


def test_radar_smoke_can_verify_canonical_evidence_without_synthesizing_state() -> None:
    text = RADAR_SMOKE.read_text(encoding="utf-8")

    assert 'process.env.RADAR_REQUIRE_LIVE_UNKNOWN !== "0"' in text
    assert 'process.env.RADAR_REQUIRE_NO_CONFIRMED !== "0"' in text
    assert "Radar activation unexpectedly changed" in text
    assert "unknown promotion policy changed" in text
    assert "ranking population changed" in text
