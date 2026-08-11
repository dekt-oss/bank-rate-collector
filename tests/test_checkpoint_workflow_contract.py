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
    for name in ("Collect NH local", "Collect KFCC"):
        env = _step(name).get("env") or {}
        assert set(env) >= R2_ENV_KEYS, f"{name} checkpoint R2 env 누락"
        assert env.get("GITHUB_TOKEN") == "${{ secrets.GITHUB_TOKEN }}"
        assert env.get("SCOPE") is not None


def test_common_infrastructure_does_not_enable_checkpoint_collection_yet() -> None:
    """PR A alone must not change live source behavior.

    Adapter loops do not consume the checkpoint service until NH/KFCC integration PRs.
    Therefore workflow source commands must not pass a resume/checkpoint flag yet.
    """
    for name in ("Collect NH local", "Collect KFCC"):
        body = _step(name)["run"]
        assert "--resume" not in body
        assert "checkpoint" not in body.lower()


def test_common_infrastructure_does_not_install_recovery_steps_early() -> None:
    names = {str(step.get("name") or "") for step in _steps()}
    assert not any(name.startswith("Decide NH recovery") for name in names)
    assert not any(name.startswith("Recover NH local") for name in names)
    assert not any(name.startswith("Decide KFCC recovery") for name in names)
    assert not any(name.startswith("Recover KFCC") for name in names)


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
