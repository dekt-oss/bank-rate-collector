"""Static safety contract for one-shot scheduled collection recovery."""

from pathlib import Path

import yaml

WORKFLOW = Path(".github/workflows/recover-failed-scheduled-collection.yml")
MORNING_RECOVERY = Path(".github/workflows/recover-morning-current-main.yml")
MORNING_PLAN = Path("scripts/morning_failure_recovery_plan.py")


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_recovery_workflow_yaml_parses() -> None:
    for path in (WORKFLOW, MORNING_RECOVERY):
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert isinstance(payload, dict)


def test_recovery_is_bounded_to_terminal_schedules_and_proven_soft_failures() -> None:
    text = _text()
    assert "github.event.workflow_run.event == 'schedule'" in text
    assert "types: [completed]" in text
    assert "env.PARENT_CONCLUSION == 'failure'" in text
    assert "env.PARENT_CONCLUSION == 'success'" in text
    assert "Build recovery plan for soft-source failures" in text
    assert "soft-recovery-plan.json" in text
    assert "--ref main" in text


def test_recovery_covers_all_canonical_scheduled_collectors() -> None:
    text = _text()
    for workflow in (
        "수집 — 일반·새마을금고",
        "수집 — 농·축협",
        "수집 — Data.go 기관별 수신잔액",
        "Collect bank rates fast",
    ):
        assert workflow in text

    assert "manual_target=\"일반 전체\"" in text
    assert "manual_target=\"새마을금고만\"" in text
    assert "nh_local_scope=\"전국\"" in text
    assert "mode=incremental" in text

    morning = MORNING_RECOVERY.read_text(encoding="utf-8")
    assert 'uses: ./.github/workflows/collect-nh.yml' in morning
    assert 'uses: ./.github/workflows/collect-institution-funding.yml' in morning
    assert 'uses: ./.github/workflows/collect.yml' in morning
    assert 'manual_target: "아침 전체"' in morning


def test_ambiguous_general_schedule_recovery_fails_closed() -> None:
    text = _text()
    assert "KFCC_ONLY: true" in text
    assert "KFCC_ONLY: false" in text
    assert "refusing ambiguous recovery" in text


def test_complete_checkpoint_terminal_recovery_restarts_fresh() -> None:
    text = _text()
    assert "COMPLETE_REPLAY_UNPROVEN" in text
    assert 'KFCC_RESUME_MODE="fresh"' in text
    assert 'NH_RESUME_MODE="fresh"' in text
    assert '-f kfcc_resume_mode="$KFCC_RESUME_MODE"' in text
    assert '-f nh_resume_mode="$NH_RESUME_MODE"' in text
    assert text.count('-f kfcc_resume_mode="$KFCC_RESUME_MODE"') == 1
    assert text.count('-f kfcc_resume_mode=auto') == 1


def test_morning_terminal_failure_recovers_suffix_on_current_main() -> None:
    text = _text()
    morning = MORNING_RECOVERY.read_text(encoding="utf-8")

    plan = MORNING_PLAN.read_text(encoding="utf-8")
    assert '"nh / surface"' in plan
    assert '"funding / collect"' in plan
    assert '"market / collect"' in plan
    assert "morning_failure_recovery_plan.py" in text
    assert "morning_start_stage" in text
    assert "recover-morning-current-main.yml" in text

    # Re-running the parent would keep the old scheduled SHA and can repeat a
    # stale-writer failure. The recovery must instead run the remaining suffix
    # from the recovery workflow's current-main commit.
    assert 'gh run rerun "$PARENT_RUN_ID"' not in text
    assert "--failed" not in text

    assert "workflow_call:" in morning
    assert "workflow_dispatch:" not in morning
    assert "start_stage:" in morning
    assert "needs: nh" in morning
    assert "needs: [nh, funding]" in morning
    assert 'nh_resume_mode: "auto"' in text
    assert 'kfcc_resume_mode: "auto"' in text


def test_morning_recovery_preserves_successful_prefix() -> None:
    morning = MORNING_RECOVERY.read_text(encoding="utf-8")

    assert "inputs.start_stage == 'nh'" in morning
    assert "inputs.start_stage == 'funding'" in morning
    assert "inputs.start_stage == 'market'" in morning
    assert 'test "$NH_RESULT" = "skipped"' in morning
    assert 'test "$FUNDING_RESULT" = "skipped"' in morning
    assert 'test "$MARKET_RESULT" = "success"' in morning
    assert "group: rate-data-writer" not in morning
