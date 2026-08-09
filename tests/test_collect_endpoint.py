"""화면에서 바로 수집을 시작하는 함수 (명세서 v3.1 §12.5).

이 파일이 검사하는 것은 **함수가 배포까지 실려 나가는가**와 **암호가 새지
않는가**다. 자바스크립트 자체를 돌려보지는 않는다 — 이 저장소에 Node 실행
환경이 없다. 대신 두 번 데인 자리를 못박는다.

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


def test_the_secrets_come_from_the_environment_only() -> None:
    """값을 코드에 박으면 저장소가 공개라 그 순간 공개된다."""
    for name in ("COLLECT_PASSWORD", "GITHUB_DISPATCH_TOKEN", "GITHUB_REPOSITORY"):
        assert f"process.env.{name}" in FUNCTION, name
    # 저장소 이름도 박지 않는다. 포크가 남의 저장소를 돌리게 된다.
    assert "dekt-oss" not in FUNCTION


def test_a_missing_setting_turns_the_feature_off_loudly() -> None:
    """반쯤 켜진 상태가 제일 나쁘다.

    조용히 실패하면 누르는 사람은 암호가 틀린 줄 알고 계속 눌러 본다.
    """
    assert "configured: false" in FUNCTION
    assert "503" in FUNCTION


def test_the_password_is_compared_in_constant_time() -> None:
    """`===`로 비교하면 앞글자가 맞을수록 늦게 끝난다. 그게 단서가 된다."""
    assert "timingSafeEqual" in FUNCTION
    assert "constantTimeEqual(body.password, password)" in FUNCTION


def test_a_wrong_password_is_slowed_and_told_nothing() -> None:
    """추측을 초당 수천 번에서 초당 한 번으로 낮춘다.

    이유를 알려주지 않는 것도 같은 이유다 — «짧다»까지만 알려줘도 크다.
    """
    assert "WRONG_PASSWORD_DELAY_MS = 1000" in FUNCTION
    assert "await sleep(WRONG_PASSWORD_DELAY_MS)" in FUNCTION
    # 틀린 이유를 나눠 적지 않는다. 한 문구로만 답한다.
    assert FUNCTION.count("error: REJECT") == 1


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


def test_only_known_inputs_reach_the_workflow() -> None:
    """화면이 보낸 것을 그대로 넘기면 화면 코드 한 줄로 아무 입력이나 건드린다."""
    assert "const FLAGS = [" in FUNCTION
    assert "SCOPES.includes(" in FUNCTION
    # 통째로 펼치지 않는다.
    assert "...body" not in FUNCTION


def test_the_workflow_still_checks_the_password_itself() -> None:
    """함수의 토큰이 새더라도 워크플로의 대조가 남아야 한다.

    한 겹으로 줄이면, 토큰 하나로 남의 수집을 마음대로 돌릴 수 있게 된다.
    """
    assert "secrets.DASHBOARD_PASSWORD" in WORKFLOW
    assert 'if [ "${GIVEN}" != "${EXPECTED}" ]; then' in WORKFLOW
    # 함수는 대조한 암호를 그대로 실어 보낸다. GitHub이 시크릿과 같은
    # 문자열을 로그에서 가린다 (run 31232386844 실측: `GIVEN: ***`).
    assert "buildInputs(body, password)" in FUNCTION
