"""NH/KFCC resumable-acquisition workflow 경계를 고정한다.

KFCC는 core workflow 안의 기존 one-shot checkpoint recovery를 유지한다. NH는
독립 workflow의 fresh-runner attempt chain으로 이동하되 같은 checkpoint/R2 계약과
operator-only fresh semantics를 유지하는지 정적으로 검사한다.
"""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CORE_WORKFLOW_PATH = ROOT / ".github" / "workflows" / "collect.yml"
NH_WORKFLOW_PATH = ROOT / ".github" / "workflows" / "collect-nh.yml"
NH_ATTEMPT_PATH = ROOT / ".github" / "workflows" / "nh-attempt.yml"
R2_ENV_KEYS = {
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "R2_ACCOUNT_ID",
    "R2_BUCKET",
    "R2_ENDPOINT",
    "R2_REGION",
}


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _triggers(workflow: dict) -> dict:
    return workflow.get("on", workflow.get(True))


def _core_workflow() -> dict:
    return _load(CORE_WORKFLOW_PATH)


def _nh_workflow() -> dict:
    return _load(NH_WORKFLOW_PATH)


def _core_steps() -> list[dict]:
    return _core_workflow()["jobs"]["collect"]["steps"]


def _nh_steps() -> list[dict]:
    return _load(NH_ATTEMPT_PATH)["jobs"]["attempt"]["steps"]


def _step(steps: list[dict], name: str) -> dict:
    return next(step for step in steps if step.get("name") == name)


def test_checkpoint_workflows_can_read_authenticated_run_metadata() -> None:
    core = _core_workflow()
    nh = _load(NH_ATTEMPT_PATH)
    assert core["permissions"]["actions"] == "read"
    assert nh["permissions"]["actions"] == "read"

    cases = (
        (_core_steps(), "Prepare KFCC checkpoint context"),
        (_nh_steps(), "Prepare NH checkpoint context"),
    )
    for steps, name in cases:
        env = _step(steps, name).get("env") or {}
        assert env.get("GITHUB_TOKEN") == "${{ secrets.GITHUB_TOKEN }}"


def test_checkpoint_workflows_keep_schedule_and_single_writer_contract() -> None:
    core = _core_workflow()
    nh = _nh_workflow()
    assert [item["cron"] for item in _triggers(core)["schedule"]] == [
        "17 15 * * 0-4",
        "17 19 * * 0-4",
    ]
    assert [item["cron"] for item in _triggers(nh)["schedule"]] == [
        "37 15 * * 0-4"
    ]
    expected = {
        "group": "rate-data-writer",
        "cancel-in-progress": False,
    }
    assert core["concurrency"] == expected
    assert nh["concurrency"] == expected


def test_long_running_source_steps_receive_complete_r2_configuration() -> None:
    cases = (
        (_nh_steps(), "Collect NH local"),
        (_core_steps(), "Collect KFCC"),
        (_core_steps(), "Recover KFCC"),
    )
    for steps, name in cases:
        env = _step(steps, name).get("env") or {}
        assert set(env) >= R2_ENV_KEYS, f"{name} checkpoint R2 env 누락"
        assert env.get("SCOPE") is not None

    decision_cases = (
        (_nh_steps(), "Decide checkpoint recovery"),
        (_nh_steps(), "Decide zero-progress fresh-runner recovery"),
        (_core_steps(), "Decide KFCC recovery"),
    )
    for steps, name in decision_cases:
        env = _step(steps, name).get("env") or {}
        assert set(env) >= R2_ENV_KEYS, f"{name} checkpoint R2 env 누락"


def test_manual_fresh_is_operator_only_and_nh_retries_stay_auto() -> None:
    core_input = _triggers(_core_workflow())["workflow_dispatch"]["inputs"][
        "kfcc_resume_mode"
    ]
    nh_input = _triggers(_nh_workflow())["workflow_dispatch"]["inputs"][
        "nh_resume_mode"
    ]
    for mode in (core_input, nh_input):
        assert mode["type"] == "choice"
        assert mode["default"] == "auto"
        assert mode["options"] == ["auto", "fresh"]

    kfcc = _step(_core_steps(), "Collect KFCC")
    assert (kfcc.get("env") or {}).get("RESUME_MODE") == (
        "${{ inputs.kfcc_resume_mode || 'auto' }}"
    )
    assert '--resume "$RESUME_MODE"' in kfcc["run"]

    caller_jobs = _nh_workflow()["jobs"]
    assert caller_jobs["attempt_1"]["with"]["resume_mode"] == (
        "${{ inputs.nh_resume_mode || 'auto' }}"
    )
    assert caller_jobs["attempt_2"]["with"]["resume_mode"] == "auto"
    assert caller_jobs["attempt_3"]["with"]["resume_mode"] == "auto"

    nh_collect = _step(_nh_steps(), "Collect NH local")
    assert (nh_collect.get("env") or {}).get("RESUME_MODE") == (
        "${{ inputs.resume_mode }}"
    )
    assert '--resume "$RESUME_MODE"' in nh_collect["run"]


def test_kfcc_checkpoint_recovery_graph_is_bounded_to_one_attempt() -> None:
    steps = _core_steps()
    names = [str(step.get("name") or "") for step in steps]
    for name in (
        "Prepare KFCC checkpoint context",
        "Collect KFCC",
        "Decide KFCC recovery",
        "Recover KFCC",
    ):
        assert names.count(name) == 1

    first = _step(steps, "Collect KFCC")
    decision = _step(steps, "Decide KFCC recovery")
    recovery = _step(steps, "Recover KFCC")
    assert first["continue-on-error"] is True
    assert '--resume "$RESUME_MODE"' in first["run"]
    assert "steps.collect_kfcc.outcome == 'failure'" in str(decision["if"])
    assert "--attempt-failed" in decision["run"]
    condition = str(recovery["if"])
    assert "steps.collect_kfcc.outcome == 'failure'" in condition
    assert "steps.decide_kfcc_recovery.outcome == 'success'" in condition
    assert "steps.decide_kfcc_recovery.outputs.eligible == 'true'" in condition
    assert recovery["continue-on-error"] is True
    assert "--resume auto" in recovery["run"]


def test_nh_recovery_graph_lives_only_in_reusable_attempt_workflow() -> None:
    core_names = {str(step.get("name") or "") for step in _core_steps()}
    assert "Prepare NH checkpoint context" not in core_names
    assert "Collect NH local" not in core_names
    assert "Recover NH local" not in core_names

    nh_names = [str(step.get("name") or "") for step in _nh_steps()]
    assert nh_names.count("Prepare NH checkpoint context") == 1
    assert nh_names.count("Collect NH local") == 1
    assert "Recover NH local" not in nh_names
    assert nh_names.count("Decide checkpoint recovery") == 1
    assert nh_names.count("Decide zero-progress fresh-runner recovery") == 1


def test_source_split_conditions_match_new_independent_boundary() -> None:
    kfcc = str(_step(_core_steps(), "Collect KFCC").get("if") or "")
    assert "env.SKIP_KFCC_THIS_RUN != 'true'" in kfcc
    assert "env.KFCC_ONLY" not in kfcc

    nh = _step(_nh_steps(), "Collect NH local")
    condition = str(nh.get("if") or "")
    assert "steps.preflight.outputs.admit == 'true'" in condition
    assert "inputs.attempt == inputs.max_attempts" in condition


def test_long_running_source_steps_remain_continue_on_error() -> None:
    assert _step(_nh_steps(), "Collect NH local")["continue-on-error"] is True
    assert _step(_core_steps(), "Collect KFCC")["continue-on-error"] is True
