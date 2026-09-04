"""Static safety contract for one-shot scheduled collection recovery."""

from pathlib import Path

import yaml

WORKFLOW = Path(".github/workflows/recover-failed-scheduled-collection.yml")


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_recovery_workflow_yaml_parses() -> None:
    payload = yaml.safe_load(_text())
    assert isinstance(payload, dict)


def test_recovery_is_bounded_to_failed_schedules() -> None:
    text = _text()
    assert "github.event.workflow_run.conclusion == 'failure'" in text
    assert "github.event.workflow_run.event == 'schedule'" in text
    assert "types: [completed]" in text
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


def test_ambiguous_general_schedule_recovery_fails_closed() -> None:
    text = _text()
    assert "KFCC_ONLY: true" in text
    assert "KFCC_ONLY: false" in text
    assert "refusing ambiguous recovery" in text
