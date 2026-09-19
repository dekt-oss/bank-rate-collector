from pathlib import Path


def test_strategy_workspace_smoke_tracks_current_lean_ia_contract() -> None:
    source = Path("scripts/strategy_workspace_smoke.js").read_text(encoding="utf-8")

    assert 'document.getElementById("external-market-context")' in source
    assert 'document.getElementById("market-funding-competition")' in source
    assert 'document.getElementById("workspace-competitor-position")' in source
    assert 'competitor?.querySelector(".top5-card")' in source
    assert 'competitor?.querySelector("#institution-funding-position")' in source
    assert 'hidden("#market-flow details.changes")' in source
    assert 'hidden(".strategy-market-direction")' in source
    assert 'hidden(".ux-decision-readiness")' in source
    assert 'hidden(".ux-decision-menu")' in source
    assert 'hidden("#relative-pricing-r1")' in source
    assert 'hidden("#rate-funding-matrix")' in source
    assert '["경쟁사 · 기관 포지션", "workspace-competitor-position"]' in source
    assert "Lean IA order=" in source
    assert "market -> readiness -> TOP5 -> secondary insight -> planning" not in source
