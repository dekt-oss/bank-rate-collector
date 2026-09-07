from pathlib import Path


def test_strategy_runtime_ia_doc_matches_smoke_labels() -> None:
    doc = Path("docs/ops/20260907-strategy-runtime-smoke-ia-contract.md").read_text(
        encoding="utf-8"
    )
    smoke = Path("scripts/strategy_workspace_smoke.js").read_text(encoding="utf-8")

    for label in ("시장 방향", "경쟁사 TOP5", "세부 비교", "자동추천 범위"):
        assert label in doc
        assert label in smoke
    assert "기본 접힘 `세부 인사이트`" in doc
    assert "details.strategy-secondary-insights" in smoke
