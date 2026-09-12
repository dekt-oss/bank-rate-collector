from pathlib import Path

WORKFLOW = Path(".github/workflows/source-health-watch.yml")


def test_source_health_watch_has_independent_issue_permission() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "issues: write" in text
    assert "actions: write" in text
    assert "scripts/source_health_incident.py" in text
    assert "--source cu" in text
    assert "--source kfcc" in text
    assert "--source nh_local" in text


def test_incident_issue_sync_is_fail_closed() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "Synchronize CU/KFCC incident issues" in text
    assert "Synchronize NH incident issue" in text
    assert "continue-on-error: true" not in text


def test_cu_retry_is_bounded_to_triggering_attempt_and_non_dispatch() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "retry_cu_once:" in text
    assert "github.event.workflow_run.event != 'workflow_dispatch'" in text
    assert 'manual_target="신협만"' in text
    assert "needs.inspect.outputs.cu_attempted == 'true'" in text
    assert "needs.inspect.outputs.cu_incident == 'true'" in text
    assert "TRIGGER_STARTED_AT" in text


def test_watch_only_operates_on_main_collection_runs() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "github.event.workflow_run.head_branch == 'main'" in text
    assert "ref: main" in text
