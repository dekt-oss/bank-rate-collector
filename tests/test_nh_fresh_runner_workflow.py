"""Workflow contract for independent bounded NH fresh-runner recovery."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
COLLECT_NH = ROOT / ".github" / "workflows" / "collect-nh.yml"
ATTEMPT = ROOT / ".github" / "workflows" / "nh-attempt.yml"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _triggers(workflow: dict) -> dict:
    return workflow.get("on", workflow.get(True))


def _attempt_steps() -> list[dict]:
    return _load(ATTEMPT)["jobs"]["attempt"]["steps"]


def test_nh_is_an_independent_scheduled_workflow() -> None:
    workflow = _load(COLLECT_NH)
    triggers = _triggers(workflow)
    assert [item["cron"] for item in triggers["schedule"]] == ["37 15 * * 0-4"]
    assert workflow["concurrency"]["group"] == "rate-data-writer"
    assert workflow["concurrency"]["cancel-in-progress"] is False


def test_nh_has_exactly_three_bounded_attempts() -> None:
    jobs = _load(COLLECT_NH)["jobs"]
    attempts = [name for name in jobs if name.startswith("attempt_")]
    assert attempts == ["attempt_1", "attempt_2", "attempt_3"]

    for number, name in enumerate(attempts, start=1):
        job = jobs[name]
        assert job["uses"] == "./.github/workflows/nh-attempt.yml"
        assert job["with"]["attempt"] == number
        assert job["with"]["max_attempts"] == 3
        assert job["secrets"] == "inherit"

    assert "outputs.outcome == 'retry'" in jobs["attempt_2"]["if"]
    assert "outputs.outcome == 'retry'" in jobs["attempt_3"]["if"]


def test_retry_chain_has_no_explicit_sleep_or_backoff() -> None:
    caller = COLLECT_NH.read_text(encoding="utf-8")
    attempt = ATTEMPT.read_text(encoding="utf-8")
    for token in ("sleep 120", "sleep 300", "2m", "5m"):
        assert token not in caller
        assert token not in attempt


def test_each_attempt_gets_a_fresh_github_hosted_runner() -> None:
    reusable = _load(ATTEMPT)
    assert set(_triggers(reusable)) == {"workflow_call"}
    assert reusable["jobs"]["attempt"]["runs-on"] == "ubuntu-latest"


def test_network_preflight_happens_before_real_collection() -> None:
    names = [step.get("name") for step in _attempt_steps()]
    assert names.index("Probe NH network path") < names.index("Collect NH local")

    preflight = next(
        step
        for step in _attempt_steps()
        if step.get("name") == "Probe NH network path"
    )
    assert "python -m rate_monitor.nh_network_preflight" in preflight["run"]
    assert "nh-network-forensics.json" in preflight["run"]


def test_first_two_bad_preflights_discard_runner_but_final_attempt_records_failure() -> None:
    collect = next(
        step for step in _attempt_steps() if step.get("name") == "Collect NH local"
    )
    condition = str(collect["if"])
    assert "steps.preflight.outputs.admit == 'true'" in condition
    assert "inputs.attempt == inputs.max_attempts" in condition
    assert collect["continue-on-error"] is True


def test_only_checkpoint_or_zero_progress_network_failure_can_retry_after_collection() -> None:
    decision = next(
        step
        for step in _attempt_steps()
        if step.get("name") == "Decide attempt outcome"
    )
    body = decision["run"]
    assert "CHECKPOINT_ELIGIBLE" in body
    assert "ZERO_PROGRESS_ELIGIBLE" in body
    assert "OUTCOME=\"retry\"" in body
    assert "ATTEMPT\" -lt \"$MAX_ATTEMPTS" in body


def test_forensic_evidence_is_kept_for_every_attempt() -> None:
    upload = next(
        step
        for step in _attempt_steps()
        if step.get("name") == "Upload NH attempt evidence"
    )
    assert upload["if"] == "always()"
    assert upload["with"]["retention-days"] == 90
    paths = upload["with"]["path"]
    assert "work/nh-network-forensics.json" in paths
    assert "work/nh-checkpoint-recovery.json" in paths
    assert "work/nh-fresh-runner-decision.json" in paths


def test_intermediate_retry_does_not_publish_canonical_state() -> None:
    by_name = {step.get("name"): step for step in _attempt_steps()}
    for name in (
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
    ):
        assert "steps.decision.outputs.publish == 'true'" in str(by_name[name]["if"])


def test_zero_raw_terminal_network_failure_uses_no_collection_gate() -> None:
    verify = next(
        step
        for step in _attempt_steps()
        if step.get("name") == "Verify P1-A gate"
    )
    assert "steps.decision.outputs.zero_raw_network" in verify["run"]
    assert "--no-collection" in verify["run"]


def test_terminal_surface_fails_when_three_attempts_do_not_succeed() -> None:
    surface = _load(COLLECT_NH)["jobs"]["surface"]
    assert surface["if"] == "always()"
    body = surface["steps"][0]["run"]
    assert 'TERMINAL" = "success' in body
    assert "최대 3회" in body
