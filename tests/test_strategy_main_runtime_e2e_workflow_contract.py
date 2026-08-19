from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "strategy-main-runtime-e2e.yml"
SMOKE = ROOT / "scripts" / "strategy_main_runtime_external_context_smoke.js"


def test_strategy_main_runtime_e2e_is_isolated_and_observable() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert 'branches: [main, "feat/strategy-main-runtime-e2e-*"]' in text
    assert "workflow_dispatch:" in text
    assert 'RATE_MONITOR_STRATEGY_DASHBOARD: "1"' in text
    assert "storage restore --dest work/rate_monitor.sqlite3" in text
    assert "build-site" in text
    assert "strategy-main-runtime-e2e" in text
    assert "statuses: write" in text
    assert "strategy_main_runtime_external_context_smoke.js" in text
    assert "strategy_preview_smoke.js" in text

    # This workflow must never publish the runner-local DB or Strategy site.
    assert "rate-monitor storage upload" not in text
    assert "git push" not in text
    assert "vercel" not in text.lower()
    assert "rate-data writer" not in text.lower()


def test_strategy_main_runtime_smoke_requires_populated_external_context() -> None:
    text = SMOKE.read_text(encoding="utf-8")

    assert 'features?.status === "ready"' in text
    assert 'features.deposit_market?.status === "ready"' in text
    assert 'result.rateCards === 3' in text
    assert 'result.flowCards === 4' in text
    assert 'result.badge.includes("BOK · 정상")' in text
    assert 'value !== "—"' in text
    assert "농·축협과 1:1 동일하지 않음" in text
    assert "DOM/payload mismatch" in text
