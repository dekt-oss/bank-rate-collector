"""화면에서 바로 수집을 시작하는 함수 (명세서 v3.1 §12.5).

NH가 독립 workflow로 분리된 뒤에도 관리자 버튼 하나가 core와 NH를 모두
시작하고, 함수/암호/남용방지 계약이 배포까지 유지되는지 정적으로 검사한다.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / ".github" / "workflows" / "collect.yml").read_text(encoding="utf-8")
NH_WORKFLOW = (ROOT / ".github" / "workflows" / "collect-nh.yml").read_text(
    encoding="utf-8"
)
FUNCTION = (ROOT / "web" / "api" / "collect.js").read_text(encoding="utf-8")
VERCEL = (ROOT / "vercel.json").read_text(encoding="utf-8")


# ── 배포까지 실려 나가는가 ──────────────────────────────────────────────


def test_the_function_is_staged_and_published() -> None:
    assert "cp -r web/api stage/api" in WORKFLOW, "스테이지에 안 담긴다"
    assert "cp -r stage/latest stage/site-public stage/api ." in WORKFLOW, "발행에 안 담긴다"
    assert re.search(r"git add -f .*\bapi\b", WORKFLOW), "커밋에 안 담긴다"


def test_the_stale_copy_is_removed_before_publishing() -> None:
    assert re.search(r"rm -rf latest site site-public vercel\.json api", WORKFLOW)


def test_the_function_sits_at_the_deploy_root_not_inside_the_static_output() -> None:
    assert '"outputDirectory": "site-public"' in VERCEL
    assert "cp -r web/api stage/site-public" not in WORKFLOW


# ── 암호와 토큰 ────────────────────────────────────────────────────────


def test_the_settings_come_from_the_environment_only() -> None:
    for name in ("GITHUB_DISPATCH_TOKEN", "GITHUB_REPOSITORY"):
        assert f"process.env.{name}" in FUNCTION, name
    assert "dekt-oss" not in FUNCTION


def test_only_the_token_has_to_be_entered_by_hand() -> None:
    assert "process.env.VERCEL_GIT_REPO_OWNER" in FUNCTION
    assert "process.env.VERCEL_GIT_REPO_SLUG" in FUNCTION
    assert 'process.env.GITHUB_REPOSITORY\n    || (owner && repo' in FUNCTION


def test_the_password_lives_only_in_the_github_secret() -> None:
    assert "COLLECT_PASSWORD" not in FUNCTION
    assert "timingSafeEqual" not in FUNCTION
    assert "buildInputs(body)" in FUNCTION


def test_the_success_message_does_not_claim_the_password_was_right() -> None:
    assert "틀리면" in FUNCTION


def test_an_empty_password_never_reaches_github() -> None:
    assert "if (!body.password)" in FUNCTION


def test_a_missing_setting_turns_the_feature_off_loudly() -> None:
    assert "configured: false" in FUNCTION
    assert "503" in FUNCTION


def test_github_error_bodies_are_not_forwarded() -> None:
    assert "response.status" in FUNCTION
    assert "await coreDispatch.text()" not in FUNCTION
    assert "await nhDispatch.text()" not in FUNCTION
    assert "await coreDispatch.json()" not in FUNCTION
    assert "await nhDispatch.json()" not in FUNCTION


# ── 독립 NH dispatch ────────────────────────────────────────────────────


def test_admin_button_dispatches_core_and_independent_nh() -> None:
    assert 'const CORE_WORKFLOW = "collect.yml"' in FUNCTION
    assert 'const NH_WORKFLOW = "collect-nh.yml"' in FUNCTION
    assert "dispatchWorkflow(token, slug, CORE_WORKFLOW, inputs.core)" in FUNCTION
    assert "dispatchWorkflow(token, slug, NH_WORKFLOW, inputs.nh)" in FUNCTION


def test_obsolete_nh_inputs_never_reach_core_workflow() -> None:
    assert '"skip_nh_local"' not in FUNCTION
    core_inputs = WORKFLOW.split("workflow_dispatch:", 1)[1].split("push:", 1)[0]
    assert "nh_local_scope:" not in core_inputs
    assert "skip_nh_local:" not in core_inputs
    assert "nh_local_scope:" in NH_WORKFLOW


def test_partial_dual_dispatch_is_reported_not_hidden() -> None:
    assert "partial" in FUNCTION
    assert "수집 일부만 시작됐습니다" in FUNCTION


# ── 남용 막기 ──────────────────────────────────────────────────────────


def test_a_second_collection_is_refused_while_core_or_nh_is_running() -> None:
    assert "WORKFLOWS.map" in FUNCTION
    assert '"in_progress"' in FUNCTION
    assert '"queued"' in FUNCTION
    assert "409" in FUNCTION


def test_the_publish_only_runs_do_not_block_a_collection() -> None:
    assert 'run.event !== "push"' in FUNCTION


def test_the_interval_is_configurable_with_a_stated_default() -> None:
    assert "DEFAULT_MIN_INTERVAL_MINUTES = 30" in FUNCTION
    assert "COLLECT_MIN_INTERVAL_MINUTES" in FUNCTION


def test_guessing_counts_one_human_attempt_not_two_workflows() -> None:
    assert "ATTEMPT_WINDOW_MINUTES = 60" in FUNCTION
    assert "MAX_ATTEMPTS_PER_WINDOW = 5" in FUNCTION
    assert "const coreRuns = groups[0].runs" in FUNCTION
    assert 'run.event === "workflow_dispatch" && minutesSince(run) < ATTEMPT_WINDOW_MINUTES' in FUNCTION


def test_a_typo_does_not_lock_out_the_next_real_attempt() -> None:
    assert 'run.event !== "push" && run.conclusion === "success"' in FUNCTION


def test_only_known_inputs_reach_each_workflow() -> None:
    assert "const FLAGS = [" in FUNCTION
    assert "SCOPES.includes(" in FUNCTION
    assert "...body" not in FUNCTION


def test_both_workflows_check_the_same_github_password_secret() -> None:
    for workflow in (WORKFLOW, NH_WORKFLOW):
        assert "secrets.DASHBOARD_PASSWORD" in workflow
        assert 'if [ "$GIVEN" != "$EXPECTED" ]; then' in workflow
