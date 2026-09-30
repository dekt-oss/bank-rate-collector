from pathlib import Path


COLLECT = Path(".github/workflows/collect.yml")
REFRESH = Path(".github/workflows/special-offer-catalog-refresh.yml")


def test_special_offer_refresh_reuses_single_writer_pipeline() -> None:
    collect = COLLECT.read_text(encoding="utf-8")
    refresh = REFRESH.read_text(encoding="utf-8")

    assert '- "특판만"' in collect
    assert "SPECIAL_OFFER_ONLY: ${{ inputs.manual_target == '특판만' }}" in collect
    assert "scripts/special_offer_catalog_refresh.py" in collect
    assert "if: ${{ env.SPECIAL_OFFER_ONLY == 'true' }}" in collect
    assert (
        'if [ "${PUBLISH_ONLY}" = "true" ] || '
        '[ "${SPECIAL_OFFER_ONLY}" = "true" ]; then'
    ) in collect
    assert (
        "if: steps.storage.outputs.backend != 'github_legacy' "
        "&& env.PUBLISH_ONLY != 'true'"
    ) in collect

    assert "workflow_dispatch:" in refresh
    assert "schedule:" not in refresh
    assert "uses: ./.github/workflows/collect.yml" in refresh
    assert 'manual_target: "특판만"' in refresh


def test_special_offer_refresh_activation_stays_manual() -> None:
    refresh = REFRESH.read_text(encoding="utf-8")
    assert "not scheduled automatically yet" in refresh
    assert "workflow_dispatch:" in refresh
    assert "cron:" not in refresh
