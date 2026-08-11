"""Resumable Acquisition PR A의 workflow 경계를 고정한다.

이 PR은 공통 checkpoint 인프라와 R2 credential wiring까지만 넣는다.
NH/KFCC adapter integration과 recovery step은 뒤 PR에서 들어오므로 여기서
실수로 수집 동작·schedule·concurrency를 바꾸지 않았는지 정적으로 검사한다.
"""

from pathlib import Path

import yaml

WORKFLOW_PATH = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "collect.yml"
R2_ENV_KEYS = {
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "R2_ACCOUNT_ID",
    "R2_BUCKET",
    "R2_ENDPOINT",
    "R2_REGION",
}


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


def _steps() -> list[dict]:
    return _workflow()["jobs"]["collect"]["steps"]


def _step(name: str) -> dict:
    return next(step for step in _steps() if step.get("name") == name)


def test_checkpoint_workflow_can_read_its_authenticated_run_metadata() -> None:
    workflow = _workflow()
    assert workflow["permissions"]["actions"] == "read"
    nh_prepare = _step("Prepare NH checkpoint context").get("env") or {}
    assert nh_prepare.get("GITHUB_TOKEN") == "${{ secrets.GITHUB_TOKEN }}"
    kfcc = _step("Collect KFCC").get("env") or {}
    assert kfcc.get("GITHUB_TOKEN") == "${{ secrets.GITHUB_TOKEN }}"


def test_checkpoint_pr_keeps_the_approved_schedule_and_single_writer() -> None:
    workflow = _workflow()
    triggers = workflow.get("on", workflow.get(True))
    assert [item["cron"] for item in triggers["schedule"]] == [
        "17 15 * * 0-4",
        "17 19 * * 0-4",
    ]
    assert workflow["concurrency"] == {
        "group": "rate-data-writer",
        "cancel-in-progress": False,
    }


def test_long_running_source_steps_receive_complete_r2_configuration() -> None:
    for name in ("Collect NH local", "Recover NH local", "Collect KFCC"):
        env = _step(name).get("env") or {}
        assert set(env) >= R2_ENV_KEYS, f"{name} checkpoint R2 env 누락"
    assert (_step("Collect NH local").get("env") or {}).get("SCOPE") is not None
    assert (_step("Recover NH local").get("env") or {}).get("SCOPE") is not None
    assert (_step("Collect KFCC").get("env") or {}).get("SCOPE") is not None
    decision_env = _step("Decide NH recovery").get("env") or {}
    assert set(decision_env) >= R2_ENV_KEYS


def test_kfcc_is_still_outside_checkpoint_integration_pr_b() -> None:
    body = _step("Collect KFCC")["run"]
    assert "--resume" not in body
    names = {str(step.get("name") or "") for step in _steps()}
    assert not any(name.startswith("Decide KFCC recovery") for name in names)
    assert not any(name.startswith("Recover KFCC") for name in names)


def test_nh_checkpoint_recovery_graph_is_bounded_to_one_attempt() -> None:
    names = [str(step.get("name") or "") for step in _steps()]
    assert names.count("Prepare NH checkpoint context") == 1
    assert names.count("Collect NH local") == 1
    assert names.count("Decide NH recovery") == 1
    assert names.count("Recover NH local") == 1

    first = _step("Collect NH local")
    decision = _step("Decide NH recovery")
    recovery = _step("Recover NH local")
    assert first["continue-on-error"] is True
    assert "--resume auto" in first["run"]
    assert "steps.collect_nh_local.outcome == 'failure'" in str(decision["if"])
    assert "--attempt-failed" in decision["run"]
    condition = str(recovery["if"])
    assert "steps.collect_nh_local.outcome == 'failure'" in condition
    assert "steps.decide_nh_recovery.outcome == 'success'" in condition
    assert "steps.decide_nh_recovery.outputs.eligible == 'true'" in condition
    assert recovery["continue-on-error"] is True
    assert "--resume auto" in recovery["run"]


def test_existing_source_split_conditions_are_unchanged() -> None:
    kfcc = str(_step("Collect KFCC").get("if") or "")
    nh = str(_step("Collect NH local").get("if") or "")

    assert "env.SKIP_KFCC_THIS_RUN != 'true'" in kfcc
    assert "env.KFCC_ONLY" not in kfcc
    assert "env.KFCC_ONLY != 'true'" in nh
    assert "SKIP_KFCC_THIS_RUN" not in nh


def test_existing_source_steps_remain_continue_on_error() -> None:
    assert _step("Collect NH local")["continue-on-error"] is True
    assert _step("Collect KFCC")["continue-on-error"] is True
