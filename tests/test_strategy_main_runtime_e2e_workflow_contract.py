from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "strategy-main-runtime-e2e.yml"
SMOKE = ROOT / "scripts" / "strategy_main_runtime_external_context_smoke.js"
WORKSPACE_SMOKE = ROOT / "scripts" / "strategy_workspace_smoke.js"
BRAND_SPEC = ROOT / "docs" / "specs" / "20260819-strategy-brand-visual-system-v3.md"


def test_strategy_main_runtime_e2e_is_isolated_and_observable() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert 'branches: [main, "feat/strategy-main-runtime-e2e-*", "feat/strategy-ux-*"]' in text
    assert "workflow_dispatch:" in text
    assert 'RATE_MONITOR_STRATEGY_DASHBOARD: "1"' in text
    assert "storage restore --dest work/rate_monitor.sqlite3" in text
    assert "build-site" in text
    assert "strategy-main-runtime-e2e" in text
    assert "statuses: write" in text
    assert "strategy_main_runtime_external_context_smoke.js" in text
    assert "strategy_preview_smoke.js" in text
    assert "strategy_workspace_smoke.js" in text
    assert "strategy_workspace_presentation.py" in text
    assert "strategy_brand_theme_presentation.py" in text
    assert "test_strategy_brand_theme_presentation.py" in text
    assert 'grep -q \'id="strategy-brand-theme-script"\'' in text

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


def test_strategy_workspace_smoke_locks_decision_first_order_and_mobile_density() -> None:
    text = WORKSPACE_SMOKE.read_text(encoding="utf-8")

    assert "decisionBeforeExternal" in text
    assert "insightBeforePreference" in text
    assert "preferenceBeforeDetail" in text
    assert "recent change details should start collapsed" in text
    assert "KPI cards are not two-column" in text
    assert "evidence cards are not two-column" in text
    assert "compact map height" in text
    assert "horizontal overflow" in text
    assert 'strategyPalette === "main-brand-v2"' in text
    assert 'accent.toUpperCase() === "#D33A7C"' in text
    assert "Korea land fill is not light branded surface" in text
    assert "analytical microcopy too small" in text


def test_strategy_brand_visual_spec_locks_palette_typography_and_scope() -> None:
    text = BRAND_SPEC.read_text(encoding="utf-8")

    assert "#4D2D58" in text
    assert "#5B2F64" in text
    assert "#734A7E" in text
    assert "#D33A7C" in text
    assert "Pretendard Variable" in text
    assert "analytical microcopy: 10.5px 미만 금지" in text
    assert "Production Strategy Release Gate ON" in text
