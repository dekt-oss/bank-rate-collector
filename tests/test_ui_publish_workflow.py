"""UI/presentation changes on main must republish the public static site."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLISH = (ROOT / ".github/workflows/publish-ui.yml").read_text(encoding="utf-8")
COLLECT = (ROOT / ".github/workflows/collect.yml").read_text(encoding="utf-8")


def test_main_ui_changes_trigger_publish_only_workflow() -> None:
    assert "name: Publish UI — main presentation changes" in PUBLISH
    assert "push:" in PUBLISH
    assert "- main" in PUBLISH
    assert '".github/workflows/publish-ui.yml"' in PUBLISH
    assert '"src/rate_monitor/services/*presentation.py"' in PUBLISH
    assert '"web/templates/**"' in PUBLISH
    assert '"web/public-structural-v2/**"' in PUBLISH


def test_ui_publish_reuses_existing_publish_only_path() -> None:
    assert "uses: ./.github/workflows/collect.yml" in PUBLISH
    assert 'manual_target: "화면만 재발행"' in PUBLISH
    assert "secrets: inherit" in PUBLISH
    assert "PUBLISH_ONLY: ${{ inputs.manual_target == '화면만 재발행' }}" in COLLECT


def test_publish_only_does_not_rewrite_authoritative_r2_state() -> None:
    assert (
        "if: steps.storage.outputs.backend != 'github_legacy' "
        "&& env.PUBLISH_ONLY != 'true'"
    ) in COLLECT
    assert "uv run rate-monitor storage upload --db publish/rate_monitor.sqlite3" in COLLECT


def test_publish_only_keeps_collection_steps_guarded() -> None:
    # Every source-collection family in the reusable workflow is already guarded
    # by PUBLISH_ONLY. Keep enough guards present that a refactor cannot silently
    # turn a presentation push into a source collection run.
    assert COLLECT.count("env.PUBLISH_ONLY != 'true'") >= 6
    assert 'if [ "${PUBLISH_ONLY}" = "true" ]; then' in COLLECT
    assert 'SKIP_RAW="--no-collection"' in COLLECT
