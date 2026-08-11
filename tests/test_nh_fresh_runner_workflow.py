"""Workflow contract for the bounded NH fresh-runner retry lane."""

from pathlib import Path

import yaml

WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "retry-nh-fresh-runner.yml"
)


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _triggers(workflow: dict) -> dict:
    return workflow.get("on", workflow.get(True))


def _job() -> dict:
    return _workflow()["jobs"]["retry-nh"]


def _steps() -> list[dict]:
    return _job()["steps"]


def test_retry_lane_is_chained_only_from_completed_collect_rates() -> None:
    triggers = _triggers(_workflow())
    assert set(triggers) == {"workflow_run"}
    workflow_run = triggers["workflow_run"]
    assert workflow_run["workflows"] == ["Collect rates"]
    assert workflow_run["types"] == ["completed"]

    condition = _job()["if"]
    assert "workflow_run.conclusion == 'success'" in condition
    assert "workflow_run.event == 'schedule'" in condition


def test_retry_lane_uses_same_single_writer_and_a_github_hosted_runner() -> None:
    workflow = _workflow()
    assert workflow["concurrency"]["group"] == "rate-data-writer"
    assert workflow["concurrency"]["cancel-in-progress"] is False
    assert _job()["runs-on"] == "ubuntu-latest"


def test_retry_decision_is_machine_readable_and_parent_window_scoped() -> None:
    decision = next(step for step in _steps() if step.get("name") == "Decide NH fresh-runner retry")
    assert decision["id"] == "decision"
    assert "github.event.workflow_run.run_started_at" in str(decision["env"])
    assert "github.event.workflow_run.updated_at" in str(decision["env"])
    assert "python -m rate_monitor.nh_runner_retry" in decision["run"]
    assert "--json work/nh-fresh-runner-decision.json" in decision["run"]


def test_retry_lane_collects_only_nh_once_and_has_no_recursive_trigger() -> None:
    collectors = [
        step for step in _steps() if str(step.get("name", "")).startswith("Collect ")
    ]
    assert [step["name"] for step in collectors] == ["Collect NH on fresh runner"]
    collector = collectors[0]
    assert "--source nh_local" in collector["run"]
    assert "--resume auto" in collector["run"]
    assert "steps.decision.outputs.cycle_date" in collector["run"]
    assert collector["continue-on-error"] is True

    # This workflow only listens to Collect rates, not to itself.
    assert _triggers(_workflow())["workflow_run"]["workflows"] == ["Collect rates"]


def test_retry_lane_requires_eligibility_for_every_state_mutating_step() -> None:
    guarded_names = {
        "Collect NH on fresh runner",
        "Snapshot",
        "Validate stored data",
        "Build dashboard",
        "Export full dataset",
        "Build public site",
        "Verify P1-A gate",
        "Volume gate",
        "Stage rate-data payload",
        "Size gate",
        "Upload state to R2",
        "Publish to rate-data branch",
    }
    by_name = {step.get("name"): step for step in _steps()}
    for name in guarded_names:
        assert "steps.decision.outputs.eligible == 'true'" in by_name[name]["if"]


def test_retry_lane_gates_before_authoritative_r2_and_public_publish() -> None:
    names = [step.get("name") for step in _steps()]
    assert names.index("Verify P1-A gate") < names.index("Volume gate")
    assert names.index("Volume gate") < names.index("Size gate")
    assert names.index("Size gate") < names.index("Upload state to R2")
    assert names.index("Upload state to R2") < names.index("Publish to rate-data branch")


def test_failed_retry_is_persisted_then_surfaces_as_workflow_failure() -> None:
    names = [step.get("name") for step in _steps()]
    assert names.index("Publish to rate-data branch") < names.index("Surface failed NH retry")
    surface = next(step for step in _steps() if step.get("name") == "Surface failed NH retry")
    assert "steps.retry_nh.outcome == 'failure'" in surface["if"]
