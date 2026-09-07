from pathlib import Path


def test_bootstrap_scope_is_workflow_only() -> None:
    workflow = Path(".github/workflows/collect-size-peer-total-assets.yml").read_text(
        encoding="utf-8"
    )

    assert "push:" in workflow
    assert "collect-total-assets" in workflow
    assert "rate-data-writer" in workflow
