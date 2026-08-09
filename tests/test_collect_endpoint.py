"""화면에서 바로 수집을 시작하는 함수 (명세서 v3.1 §12.5).

이 파일이 검사하는 것은 **함수가 배포까지 실려 나가는가**와 **약속이
지켜지는가**다. 동작 자체는 개발할 때 Node로 직접 돌려 확인했다 — 그렇게
해서 ESM에 `require`를 섞은 것과 지운 변수를 계속 쓰던 것을 잡았다. 여기서는
CI가 Node 없이도 지킬 수 있는 계약만 못박는다.

첫째, `site_service.INLINE_KEYS`처럼 «코드에도 데이터에도 값이 있는데 화면
에서만 비는» 종류의 사고다. 여기서는 파일이 그렇다. `web/api/collect.js`를
만들어 두어도 발행 단계가 `rate-data`로 옮기지 않으면 주소가 404다.

둘째, Vercel은 **배포 루트의 `api/`만** 함수로 잡는다. `site-public/api/`에
두면 함수가 아니라 그냥 자바스크립트 파일로 내려간다 — 소스가 통째로 공개된다.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / ".github" / "workflows" / "collect.yml").read_text(encoding="utf-8")
FUNCTION = (ROOT / "web" / "api" / "collect.js").read_text(encoding="utf-8")
VERCEL = (ROOT / "vercel.json").read_text(encoding="utf-8")


# ── 배포까지 실려 나가는가 ──────────────────────────────────────────────


def test_the_function_is_staged_and_published() -> None:
    """만들어 두기만 하면 주소가 404다. 옮기는 줄이 둘 다 있어야 한다."""
    assert "cp -r web/api stage/api" in WORKFLOW, "스테이지에 안 담긴다"
    assert "cp -r stage/latest stage/site-public stage/api ." in WORKFLOW, "발행에 안 담긴다"
    assert re.search(r"git add -f .*\bapi\b", WORKFLOW), "커밋에 안 담긴다"


def test_the_stale_copy_is_removed_before_publishing() -> None:
    """발행은 부모 없는 커밋으로 브랜치를 갈아 끼운다.

    지우는 목록에서 빠지면 예전 함수 파일이 남아, 고친 줄 알았는데 옛것이
    도는 상태가 된다.
    """
    assert re.search(r"rm -rf latest site site-public vercel\.json api", WORKFLOW)


def test_the_function_sits_at_the_deploy_root_not_inside_the_static_output() -> None:
    """`site-public/` 안에 두면 함수가 아니라 소스 파일이 내려간다.

    Vercel은 `outputDirectory`와 별개로 배포 루트의 `api/`를 함수로 잡는다.
    """
    assert '"outputDirectory": "site-public"' in VERCEL
    assert "cp -r web/api stage/site-public" not in WORKFLOW


# ── 암호와 토큰 ────────────────────────────────────────────────────────


def test_the_settings_come_from_the_environment_only() -> None:
    """값을 코드에 박으면 저장소가 공개라 그 순간 공개된다."""
    for name in ("GITHUB_DISPATCH_TOKEN", "GITHUB_REPOSITORY"):
        assert f"process.env.{name}" in FUNCTION, name
    # 저장소 이름도 박지 않는다. 포크가 남의 저장소를 돌리게 된다.
    assert "dekt-oss" not in FUNCTION


def test_only_the_token_has_to_be_entered_by_hand() -> None:
    """넣어야 할 것이 적을수록 «설정이 반만 된» 상태도 덜 생긴다.

    Vercel은 어느 저장소에서 배포했는지 이미 알고 그 값을 환경에 넣어 준다.
    다만 그 노출은 프로젝트 설정에 달려 있어 꺼져 있을 수 있으므로,
    명시적으로 넣은 값이 있으면 그쪽이 이긴다.
    """
    assert "process.env.VERCEL_GIT_REPO_OWNER" in FUNCTION
    assert "process.env.VERCEL_GIT_REPO_SLUG" in FUNCTION
    assert 'process.env.GITHUB_REPOSITORY\n    || (owner && repo' in FUNCTION


def test_the_password_lives_only_in_the_github_secret() -> None:
    """비밀을 두 곳에 두면 언젠가 한쪽만 바뀐다.

    그날 화면은 «틀렸다»고 하고 GitHub은 맞다고 하는데, 어느 쪽이 진짜인지
    화면으로는 알 수 없다. 그래서 `DASHBOARD_PASSWORD` 하나만 둔다.
    """
    assert "COLLECT_PASSWORD" not in FUNCTION
    # 대조하지 않으므로 상수시간 비교도 없어야 한다. 남아 있으면 «검사한다»는
    # 인상만 주고 실제로는 아무것도 안 하는 코드가 된다.
    assert "timingSafeEqual" not in FUNCTION
    assert "buildInputs(body)" in FUNCTION


def test_the_success_message_does_not_claim_the_password_was_right() -> None:
    """대조는 그 실행 안에서 일어난다. 틀리면 몇 초 뒤 빨간 X로 끝난다.

    «시작했습니다»만 적으면 보는 사람은 맞았다고 믿고 세 시간을 기다린다.
    """
    assert "틀리면" in FUNCTION


def test_an_empty_password_never_reaches_github() -> None:
    """보내 봐야 실행 하나를 버리고, 그 실행이 시도 계산에 들어간다."""
    assert "if (!body.password)" in FUNCTION


def test_a_missing_setting_turns_the_feature_off_loudly() -> None:
    """반쯤 켜진 상태가 제일 나쁘다.

    조용히 실패하면 누르는 사람은 암호가 틀린 줄 알고 계속 눌러 본다.
    """
    assert "configured: false" in FUNCTION
    assert "503" in FUNCTION


def test_github_error_bodies_are_not_forwarded() -> None:
    """GitHub 응답에는 토큰 범위 같은 것이 섞여 있다. 그대로 흘리면 샌다."""
    assert "GitHub ${dispatch.status}" in FUNCTION
    assert "await dispatch.text()" not in FUNCTION
    assert "await dispatch.json()" not in FUNCTION


# ── 남용 막기 ──────────────────────────────────────────────────────────


def test_a_second_collection_is_refused_while_one_is_running() -> None:
    """전국 한 바퀴는 실측 3시간 41분이고 원천 9,743곳에 요청을 보낸다.

    실수로 두 번 누르는 것과 일부러 도배하는 것을 같이 막는다.
    """
    assert '"in_progress"' in FUNCTION
    assert '"queued"' in FUNCTION
    assert "409" in FUNCTION


def test_the_publish_only_runs_do_not_block_a_collection() -> None:
    """main 푸시로 도는 실행은 수집이 아니라 발행(2분)이다.

    그것 때문에 간격 제한을 걸면, 머지한 직후에는 아무도 수집을 못 돌린다.
    """
    assert 'r.event !== "push"' in FUNCTION


def test_the_interval_is_configurable_with_a_stated_default() -> None:
    assert "DEFAULT_MIN_INTERVAL_MINUTES = 30" in FUNCTION
    assert "COLLECT_MIN_INTERVAL_MINUTES" in FUNCTION


def test_guessing_is_bounded_by_counting_attempts() -> None:
    """암호를 워크플로가 대조하므로 틀린 값도 실행을 하나 남긴다.

    세지 않으면 이 주소가 그대로 무제한 추측기가 된다.
    """
    assert "ATTEMPT_WINDOW_MINUTES = 60" in FUNCTION
    assert "MAX_ATTEMPTS_PER_WINDOW = 5" in FUNCTION
    # 실패만 세면 맞는 암호를 사이에 섞어 계산을 지울 수 있다.
    assert 'r.event === "workflow_dispatch" && minutesSince(r) < ATTEMPT_WINDOW_MINUTES' in FUNCTION


def test_a_typo_does_not_lock_out_the_next_real_attempt() -> None:
    """간격 제한이 실패한 실행까지 세면 오타 한 번에 30분을 기다린다."""
    assert 'r.event !== "push" && r.conclusion === "success"' in FUNCTION


def test_only_known_inputs_reach_the_workflow() -> None:
    """화면이 보낸 것을 그대로 넘기면 화면 코드 한 줄로 아무 입력이나 건드린다."""
    assert "const FLAGS = [" in FUNCTION
    assert "SCOPES.includes(" in FUNCTION
    # 통째로 펼치지 않는다.
    assert "...body" not in FUNCTION


def test_the_workflow_is_the_only_place_the_password_is_checked() -> None:
    """여기가 사라지면 암호를 보는 곳이 아무 데도 없게 된다.

    함수는 대조하지 않고 그대로 실어 보내므로, 이 단계가 유일한 문이다.
    """
    assert "secrets.DASHBOARD_PASSWORD" in WORKFLOW
    assert 'if [ "${GIVEN}" != "${EXPECTED}" ]; then' in WORKFLOW
