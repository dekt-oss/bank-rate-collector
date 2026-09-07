from pathlib import Path


def test_strategy_workspace_smoke_tracks_current_progressive_disclosure_contract() -> None:
    source = Path("scripts/strategy_workspace_smoke.js").read_text(encoding="utf-8")

    assert 'document.querySelector(".strategy-market-direction")' in source
    assert 'document.querySelector(".ux-decision-readiness")' in source
    assert 'document.querySelector(".decision-integrated-top5")' in source
    assert 'document.querySelector("details.strategy-secondary-insights")' in source
    assert 'insight.closest("details.strategy-secondary-insights") === secondary' in source
    assert 'Boolean(secondary?.open)' in source
    assert '["시장 방향", "경쟁사 TOP5", "세부 비교", "자동추천 범위"]' in source
    assert "market -> readiness -> TOP5 -> secondary insight -> planning" in source
    assert "readiness -> insight -> TOP5 -> planning" not in source
