from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "strategy-main-runtime-e2e.yml"
SMOKE = ROOT / "scripts" / "strategy_main_runtime_external_context_smoke.js"
PREVIEW_SMOKE = ROOT / "scripts" / "strategy_preview_smoke.js"
WORKSPACE_SMOKE = ROOT / "scripts" / "strategy_workspace_smoke.js"
BRAND_SPEC = ROOT / "docs" / "specs" / "20260819-strategy-brand-visual-system-v3.md"


def test_strategy_main_runtime_e2e_is_isolated_and_observable() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    for branch in (
        "main",
        '"feat/strategy-main-runtime-e2e-*"',
        '"feat/strategy-ux-*"',
        '"feat/unify-main-strategy-production-*"',
        '"fix/strategy-release-gate-*"',
    ):
        assert branch in text
    assert "workflow_dispatch:" in text
    assert "Validate canonical Strategy release gate contract" in text
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
    assert "test_strategy_production_release.py" in text
    assert 'grep -q \'id="strategy-brand-theme-script"\'' in text
    assert "insufficient_history" in text
    assert "non_consecutive_months" in text
    assert "source_contract_mismatch" not in text
    assert "schema_unavailable" not in text
    assert "invalid_previous_balance" not in text

    for release_path in (
        ".github/workflows/collect.yml",
        ".github/workflows/collect-savings-fast.yml",
        ".github/workflows/nh-attempt.yml",
    ):
        assert release_path in text

    # This workflow may inspect Vercel-related files by name, but it must never
    # deploy or publish the runner-local DB/Strategy site.
    lower = text.lower()
    assert "rate-monitor storage upload" not in text
    assert "git push" not in text
    assert "vercel deploy" not in lower
    assert "vercel --prod" not in lower
    assert "deploy_to_vercel" not in lower
    assert "rate-data writer" not in lower


def test_strategy_main_runtime_smoke_accepts_fail_closed_external_context() -> None:
    text = SMOKE.read_text(encoding="utf-8")

    assert '["ready", "partial", "no_data"]' in text
    assert "insufficient_history" in text
    assert "non_consecutive_months" in text
    assert "source_contract_mismatch" not in text
    assert "requiredRateKeys" in text
    assert "primary_realized_deposit_rate" in text
    assert "term_deposit_1y_rate" in text
    assert "requiredFlowKeys" in text
    for key in ("savings_bank", "credit_union", "kfcc", "broad_mutual_finance"):
        assert key in text
    assert 'result.rateCards === 3' in text
    assert 'result.flowCards === 4' in text
    assert 'result.badge.includes("BOK ·")' in text
    assert 'item?.status === "ready"' in text
    assert "DOM/payload mismatch" in text
    assert "농·축협과 1:1 동일하지 않음" in text


def test_strategy_preview_smoke_uses_search_handoff_instead_of_hidden_map() -> None:
    text = PREVIEW_SMOKE.read_text(encoding="utf-8")

    assert "assertStrategyRoleSplit" in text
    assert "Strategy 지역 지도는 검색 조회로 이관되어 숨겨져야 함" in text
    assert "지역·지도 상세는 검색 조회로 통합했습니다." in text
    assert "금리결정 준비도 카드가 보이지 않음" in text
    assert "Strategy 보고서 출력 버튼이 보이지 않음" in text
    assert 'data-market-mode="combined"' in text
    assert "기본 비교모드가 저축은행 + 상호금융이 아님" in text
    assert '#geo-map [data-region="부산"]' not in text
    assert '[data-map-sector="' not in text


def test_strategy_workspace_smoke_locks_decision_first_order_and_role_split() -> None:
    text = WORKSPACE_SMOKE.read_text(encoding="utf-8")

    assert "readiness -> insight -> TOP5 -> planning order=" in text
    assert "product section label/order wrong" in text
    assert "duplicated legacy/detail shell not hidden" in text
    assert "Search 지역 상세 handoff가 유지되지 않음" in text
    assert "model evidence should start collapsed" in text
    assert "horizontal overflow" in text
    assert 'data-strategy-workspace="decision-first-v1"' in text
    assert 'data-strategy-palette="main-brand-v2"' in text
    assert "assertVisualRuntimeContracts" in text
    assert "computed brand accent=" in text
    assert "Strategy regional map resurfaced" in text
    assert "active Public Structural Response Surface missing" in text
    assert "Public Structural Response Surface not rendered" in text
    assert "Factual Finder runtime host missing" in text
    assert 'waitForSelector("#public-structural-v2-factual-rate-finder"' in text
    assert "Public Structural computed font below 10.5px" in text
    assert "candidate-card pseudo label content missing=" in text
    assert "candidate-card pseudo label not rendered" in text
    assert "candidate-card pseudo label font=" in text
    assert "visible Response Surface x-axis collision=" in text


def test_strategy_brand_visual_spec_locks_palette_typography_and_scope() -> None:
    text = BRAND_SPEC.read_text(encoding="utf-8")

    assert "#4D2D58" in text
    assert "#5B2F64" in text
    assert "#734A7E" in text
    assert "#D33A7C" in text
    assert "Pretendard Variable" in text
    assert "analytical microcopy: 10.5px 미만 금지" in text
    assert "Production Strategy Release Gate ON" in text
