from pathlib import Path

COLLECT = Path(".github/workflows/collect.yml")
RECOVERY = Path(".github/workflows/recover-failed-scheduled-collection.yml")


def test_main_push_does_not_enter_canonical_collection_writer() -> None:
    text = COLLECT.read_text(encoding="utf-8")
    trigger_block = text.split("concurrency:", 1)[0]
    assert "\n  push:\n" not in trigger_block
    assert "github.event_name == 'push'" not in text


def test_publication_gates_run_before_authoritative_r2_upload() -> None:
    text = COLLECT.read_text(encoding="utf-8")
    stage = text.index("      - name: Stage rate-data payload")
    size_gate = text.index("      - name: Size gate")
    volume_gate = text.index("      - name: Volume gate")
    r2_upload = text.index("      - name: Upload state to R2")
    rate_data_publish = text.index("      - name: Publish to rate-data branch")

    assert stage < size_gate < volume_gate < r2_upload < rate_data_publish


def test_r2_upload_remains_after_validation_and_p1a_gate() -> None:
    text = COLLECT.read_text(encoding="utf-8")
    assert text.index("      - name: Validate stored data") < text.index(
        "      - name: Upload state to R2"
    )
    assert text.index("      - name: Verify P1-A gate") < text.index(
        "      - name: Upload state to R2"
    )


def test_scheduled_recovery_inspects_successful_soft_failures_without_owning_writer_lock() -> None:
    text = RECOVERY.read_text(encoding="utf-8")

    assert (
        "if: ${{ github.event.workflow_run.event == 'schedule'"
        " && github.event.workflow_run.head_branch == 'main' }}"
    ) in text
    assert "PARENT_CONCLUSION: ${{ github.event.workflow_run.conclusion }}" in text
    assert "scripts/scheduled_soft_failure_recovery.py" in text
    assert "collection-run-$PARENT_RUN_ID" in text
    assert "bank-rates-fast-$PARENT_RUN_ID" in text
    assert "group: rate-data-writer" not in text


def test_soft_failure_recovery_is_bounded_targeted_and_non_recursive() -> None:
    text = RECOVERY.read_text(encoding="utf-8")

    for target in ("참고지표만", "저축은행만", "신협만", "새마을금고만", "일반 전체"):
        assert target in text
    assert "-f accept_volume_drop=false" in text
    assert "-f kfcc_resume_mode=auto" in text
    assert "--ref main" in text

    # The trigger is workflow_run only. Child repairs are workflow_dispatch runs,
    # so they cannot recursively satisfy this schedule-only recovery job.
    trigger = text.split("concurrency:", 1)[0]
    assert "workflow_run:" in trigger
    assert "workflow_dispatch:" not in trigger


def test_terminal_failure_recovery_contract_is_preserved() -> None:
    text = RECOVERY.read_text(encoding="utf-8")

    assert "env.PARENT_CONCLUSION == 'failure'" in text
    assert 'gh workflow run collect-nh.yml' in text
    assert 'gh workflow run collect-institution-funding.yml' in text
    assert 'manual_target="일반 전체"' in text
