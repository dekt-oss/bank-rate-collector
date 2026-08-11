"""NH/KFCC resumable-acquisition workflow 경계를 고정한다.

두 장시간 수집원 모두 같은 workflow 안에서 최대 한 번만 복구하고,
schedule/concurrency/source split/R2 credential 계약을 바꾸지 않는지 정적으로 검사한다.
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
    for name in ("Prepare NH checkpoint context", "Prepare KFCC checkpoint context"):
        env = _step(name).get("env") or {}
        assert env.get("GITHUB_TOKEN") == "${{ secrets.GITHUB_TOKEN }}"


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
    for name in (
        "Collect NH local",
        "Recover NH local",
        "Collect KFCC",
        "Recover KFCC",
    ):
        env = _step(name).get("env") or {}
        assert set(env) >= R2_ENV_KEYS, f"{name} checkpoint R2 env 누락"
        assert env.get("SCOPE") is not None

    for name in ("Decide NH recovery", "Decide KFCC recovery"):
        env = _step(name).get("env") or {}
        assert set(env) >= R2_ENV_KEYS, f"{name} checkpoint R2 env 누락"


def _assert_manual_fresh_contract(source: str, input_name: str) -> None:
    workflow = _workflow()
    triggers = workflow.get("on", workflow.get(True))
    mode = triggers["workflow_dispatch"]["inputs"][input_name]
    assert mode["type"] == "choice"
    assert mode["default"] == "auto"
    assert mode["options"] == ["auto", "fresh"]

    first = _step(source)
    assert (first.get("env") or {}).get("RESUME_MODE") == f"${{{{ inputs.{input_name} || 'auto' }}}}"
    assert '--resume "$RESUME_MODE"' in first["run"]


def test_manual_fresh_is_operator_only_and_recovery_stays_auto() -> None:
    _assert_manual_fresh_contract("Collect NH local", "nh_resume_mode")
    _assert_manual_fresh_contract("Collect KFCC", "kfcc_resume_mode")

    for name in ("Recover NH local", "Recover KFCC"):
        recovery = _step(name)
        assert "RESUME_MODE" not in (recovery.get("env") or {})
        assert "--resume auto" in recovery["run"]


def _assert_one_shot_recovery_graph(
    *,
    prepare: str,
    collect: str,
    collect_id: str,
    decide: str,
    decide_id: str,
    recover: str,
) -> None:
    names = [str(step.get("name") or "") for step in _steps()]
    for name in (prepare, collect, decide, recover):
        assert names.count(name) == 1

    first = _step(collect)
    decision = _step(decide)
    recovery = _step(recover)
    assert first["continue-on-error"] is True
    assert '--resume "$RESUME_MODE"' in first["run"]
    assert f"steps.{collect_id}.outcome == 'failure'" in str(decision["if"])
    assert "--attempt-failed" in decision["run"]
    condition = str(recovery["if"])
    assert f"steps.{collect_id}.outcome == 'failure'" in condition
    assert f"steps.{decide_id}.outcome == 'success'" in condition
    assert f"steps.{decide_id}.outputs.eligible == 'true'" in condition
    assert recovery["continue-on-error"] is True
    assert "--resume auto" in recovery["run"]


def test_nh_checkpoint_recovery_graph_is_bounded_to_one_attempt() -> None:
    _assert_one_shot_recovery_graph(
        prepare="Prepare NH checkpoint context",
        collect="Collect NH local",
        collect_id="collect_nh_local",
        decide="Decide NH recovery",
        decide_id="decide_nh_recovery",
        recover="Recover NH local",
    )


def test_kfcc_checkpoint_recovery_graph_is_bounded_to_one_attempt() -> None:
    _assert_one_shot_recovery_graph(
        prepare="Prepare KFCC checkpoint context",
        collect="Collect KFCC",
        collect_id="collect_kfcc",
        decide="Decide KFCC recovery",
        decide_id="decide_kfcc_recovery",
        recover="Recover KFCC",
    )


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
