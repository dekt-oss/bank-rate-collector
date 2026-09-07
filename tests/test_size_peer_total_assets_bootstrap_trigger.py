from pathlib import Path


WORKFLOW = Path(".github/workflows/collect-size-peer-total-assets.yml")


def test_size_peer_total_assets_bootstrap_push_is_narrow() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "push:" in source
    assert "branches:\n      - main" in source
    assert "paths:\n      - .github/workflows/collect-size-peer-total-assets.yml" in source
    assert "if: ${{ github.event_name == 'workflow_dispatch' }}" in source
    assert "if: ${{ github.event_name != 'pull_request' }}" in source
    assert "group: rate-data-writer" in source
    assert "queue: max" in source
    assert 'VALIDATED_COMMON_BAS_YM: "202512"' in source
