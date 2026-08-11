"""게이트가 원천마다 자동으로 분다 (v4 PR 8).

예전에는 `scripts/verify_gate.py`에 원천 이름을 손으로 적었다.

    ("kfcc", "새마을금고"), ("nh_local", "농·축협")

같은 목록이 세 군데 흩어져 있어서, 원천을 하나 더할 때마다 그 파일을 고쳐야
했다. **잊으면 그 원천은 아무 검사도 안 받은 채 발행된다.**

이제 어댑터가 자기 계약을 밝히고 게이트가 그걸 읽는다. 이 파일은 그 구조가
무너지지 않는지 본다.
"""

from pathlib import Path

import pytest

GATE = (Path(__file__).resolve().parents[1] / "scripts" / "verify_gate.py").read_text(
    encoding="utf-8"
)


@pytest.fixture(autouse=True)
def keys(monkeypatch):
    # 어댑터를 세우려면 인증키가 필요하다. 게이트는 클래스만 보므로 값은
    # 아무거나 된다.
    monkeypatch.setenv("FINLIFE_API_KEY", "test")
    monkeypatch.setenv("ECOS_API_KEY", "test")


def _adapters() -> dict:
    from rate_monitor.cli import ADAPTERS

    return ADAPTERS


def test_every_adapter_declares_whether_it_gives_a_max_rate() -> None:
    """이 값이 없으면 게이트가 그 원천의 max_rate 규칙을 검사하지 않는다.

    새마을금고 103,844행과 농·축협 4,920행이 `False`다 — 원천 화면에
    최고우대금리 열이 아예 없다. 그걸 `base_rate`로 메우면 우대금리가 있는
    상품처럼 보인다 (v3 §8.4).
    """
    missing = [
        name for name, cls in _adapters().items()
        if not hasattr(cls, "provides_max_rate")
    ]
    assert missing == [], f"provides_max_rate를 안 밝힌 수집원: {missing}"


def test_the_sources_without_a_max_rate_are_the_ones_we_measured() -> None:
    """실측과 다르면 둘 중 하나가 틀린 것이다."""
    without = {
        name for name, cls in _adapters().items() if not cls.provides_max_rate
    }
    assert without == {"kfcc", "nh_local"}


def test_every_adapter_declares_its_sector() -> None:
    """업권이 섞이면 화면이 둘을 못 가른다."""
    missing = [name for name, cls in _adapters().items() if not getattr(cls, "sector", None)]
    assert missing == []


def test_the_gate_reads_the_adapters_instead_of_a_hand_list() -> None:
    """원천을 더할 때 게이트도 같이 늘어야 한다."""
    assert "from rate_monitor.cli import ADAPTERS" in GATE
    assert "for source_id, adapter_cls in sorted(ADAPTERS.items()):" in GATE
    assert 'getattr(adapter_cls, "provides_max_rate", True)' in GATE


def test_the_gate_skips_a_source_it_has_no_data_for() -> None:
    """0 == 0으로 통과시키면 검사가 아니라 장식이 된다.

    시중은행이 실제로 그랬다 — PR 5를 머지할 때 관측 0건이라 게이트 셋이
    전부 "통과"로 찍혔다. 이제 건너뛴 것을 건너뛰었다고 적는다.
    """
    assert "[건너뜀]" in GATE


def test_the_gate_reports_a_failed_source_without_blocking() -> None:
    """한 원천이 실패해도 나머지는 발행한다. 다만 로그에 남긴다."""
    assert "마지막 수집이 실패한 원천" in GATE
    assert "CONFIRMED_RUN_STATUSES" in GATE


def test_only_fixed_scope_sources_get_a_scope_check() -> None:
    """원천에 따라 갈리는 곳에 기대값을 지어내지 않는다.

    finlife는 권역이 `rate_scope`를 정하므로 고정값이 있다. 새마을금고·신협은
    상품마다 다르므로 안 적었다.
    """
    fixed = {
        name for name, cls in _adapters().items()
        if getattr(cls, "expected_rate_scope", None)
    }
    assert fixed == {"finlife_bank", "finlife_savings_bank"}


# ── 수집 주기 (2026-08-06) ──────────────────────────────────────────────


def test_the_schedule_starts_early_enough_for_eight_am_sla() -> None:
    """평일 core 00:17 KST, KFCC 04:17 KST를 UTC cron으로 정확히 환산한다.

    두 실행 모두 한국시간 자정~새벽이므로 UTC에서는 전날 일~목에 걸린다.
    정각을 피하고, 08:00 hard deadline 앞에 queue/후처리 여유를 둔다.
    """
    import datetime as dt
    from pathlib import Path

    import yaml

    workflow = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "collect.yml"
    loaded = yaml.safe_load(workflow.read_text(encoding="utf-8"))
    triggers = loaded.get("on", loaded.get(True))
    crons = [s["cron"] for s in triggers["schedule"]]
    assert crons == ["17 15 * * 0-4", "17 19 * * 0-4"]

    kst = dt.timezone(dt.timedelta(hours=9))
    cases = [(0, 17, 15), (4, 17, 19)]
    for local_hour, local_minute, utc_hour in cases:
        for day in range(10, 17):                  # 2026-08-10(월)~16(일)
            local = dt.datetime(
                2026, 8, day, local_hour, local_minute, tzinfo=kst
            )
            utc = local.astimezone(dt.UTC)
            assert (utc.hour, utc.minute) == (utc_hour, 17)
            cron_weekday = (utc.weekday() + 1) % 7  # Python 월=0 → cron 일=0
            caught = 0 <= cron_weekday <= 4
            weekday = local.weekday() < 5
            assert caught is weekday, f"{local:%m-%d %a %H:%M}가 어긋난다"


def test_the_two_crons_split_the_work_so_neither_run_hits_six_hours() -> None:
    """정기 수집을 둘로 나눈다. 한 작업에 다 담으면 6시간 한도에서 죽는다.

    실측(run 23)으로 계산하면 새마을금고 전국 2시간 6분 + 농·축협 전국
    3시간 37분 + 나머지 18분 = 6시간 3분이다. GitHub은 작업당 6시간에서
    **경고 없이 죽인다** — 세 시간 반을 받아 둔 것까지 통째로 잃는다.

    나누는 장치는 크론 문자열 비교다. 크론은 입력을 못 실어 보내기 때문에
    다른 손잡이가 없다. 그래서 `env`의 문자열과 `schedule`의 값이 **글자까지
    같아야** 한다 — 한 글자만 어긋나도 둘 다 false가 되어 한 실행이 전부를
    받으려 하고, 그때는 조용히 6시간에서 죽는다.
    """
    workflow = _workflow()
    triggers = workflow.get("on", workflow.get(True))
    crons = {s["cron"] for s in triggers["schedule"]}
    env = workflow["jobs"]["collect"]["env"]

    for key in ("KFCC_ONLY", "SKIP_KFCC_THIS_RUN"):
        quoted = [c for c in crons if f"'{c}'" in env[key]]
        assert len(quoted) == 1, f"{key}가 가리키는 크론이 schedule에 없다: {env[key]}"

    # 서로 다른 크론을 봐야 한다. 같은 것을 보면 한쪽 실행이 통째로 빈다.
    assert env["KFCC_ONLY"] != env["SKIP_KFCC_THIS_RUN"]


def test_each_scheduled_run_collects_a_different_half() -> None:
    """00:17은 새마을금고 말고 전부, 04:17은 새마을금고만."""
    steps = _workflow()["jobs"]["collect"]["steps"]
    collectors = {
        s["name"]: str(s.get("if") or "")
        for s in steps if str(s.get("name", "")).startswith("Collect ")
    }
    assert collectors, "수집 단계를 찾지 못했다"

    kfcc = collectors.pop("Collect KFCC")
    assert "env.SKIP_KFCC_THIS_RUN != 'true'" in kfcc
    assert "env.KFCC_ONLY" not in kfcc, "새마을금고가 자기 실행에서 빠지면 안 된다"

    for name, cond in collectors.items():
        assert "env.KFCC_ONLY != 'true'" in cond, f"{name}이 새마을금고 실행에서도 돈다"
        assert "SKIP_KFCC_THIS_RUN" not in cond, f"{name}이 메인 실행에서 빠진다"


def test_the_scope_comes_from_config_not_from_a_second_default() -> None:
    """수집 범위를 정하는 곳은 config/regions.yaml 하나다.

    예전에는 `--scope "${{ inputs.kfcc_scope || '부산' }}"`이었다. 정기
    수집에는 `inputs`가 통째로 비어서 **항상 뒤의 '부산'이 갔다** — 입력
    기본값도 주석도 전국인데 크론으로 도는 실제 수집은 부산만 받았다.
    기본값이 두 군데 있으면 반드시 어긋나고, 어긋난 쪽이 조용히 이긴다.
    """
    steps = _workflow()["jobs"]["collect"]["steps"]
    for name in ("Collect KFCC", "Collect NH local"):
        body = next(s for s in steps if s.get("name") == name)["run"]
        assert "${SCOPE:+--scope" in body, f"{name}: 값이 있을 때만 붙여야 한다"
        assert "||" not in body, f"{name}: 워크플로에 두 번째 기본값이 남아 있다"


def test_a_merge_to_main_republishes_the_screen_by_itself() -> None:
    """머지만 하면 화면이 바뀌어야 한다.

    이 사이트는 서버가 없다. Vercel은 `rate-data` 브랜치만 빌드하는데 화면
    파일은 이 워크플로가 거기 밀어 넣으므로, **main에는 화면 파일이 아예
    없다.** 그래서 머지가 아무 일도 일으키지 않았고, 화면을 보려면 수집을
    손으로 돌려 2시간 30분을 기다려야 했다.

    파일 목록(`paths:`)으로 거르지 않는 것도 일부러다. 그 목록은 반드시
    낡고, 낡으면 "머지했는데 화면이 안 바뀐다"가 조용히 되돌아온다.
    """
    triggers = _workflow().get("on", _workflow().get(True))
    assert triggers["push"]["branches"] == ["main"]
    assert "paths" not in triggers["push"], "파일 목록으로 거르면 반드시 낡는다"


def test_a_push_never_hits_a_source_but_a_schedule_does() -> None:
    """머지가 금리를 새로 받을 이유는 없다.

    머지마다 전국 한 바퀴를 돌면 원천에 폐가 된다. 반대로 정기 수집은
    실제로 받아야 하므로, 두 경로가 같은 스위치를 다르게 봐야 한다.
    """
    gate = _workflow()["jobs"]["collect"]["env"]["PUBLISH_ONLY"]
    assert "github.event_name == 'push'" in gate
    assert "inputs.publish_only == true" in gate
    # schedule은 어디에도 안 걸린다 → 수집을 한다.
    assert "schedule" not in gate


def test_publish_only_skips_every_collector_but_still_publishes() -> None:
    """화면만 다시 내는 길이 있어야 한다.

    **저축은행 수집만 스위치가 없던 것이 핵심이었다.** 나머지를 다 꺼도
    그 하나가 돌아서 "아무것도 수집하지 않는다"를 말할 수 없었다.
    """
    steps = _workflow()["jobs"]["collect"]["steps"]
    skipped = {
        s["name"] for s in steps
        if "PUBLISH_ONLY != 'true'" in str(s.get("if") or "")
    }
    collectors = {s["name"] for s in steps if str(s.get("name", "")).startswith("Collect ")}
    assert collectors, "수집 단계를 찾지 못했다"
    assert collectors == skipped, f"안 꺼지는 수집 단계: {sorted(collectors - skipped)}"

    # 발행까지 가야 화면이 바뀐다. 이 셋이 꺼지면 스위치가 무의미하다.
    for name in ("Build public site", "Publish to rate-data branch", "Snapshot"):
        step = next(s for s in steps if s.get("name") == name)
        assert "PUBLISH_ONLY" not in str(step.get("if") or ""), name

    # 손으로 돌릴 때 쓰는 체크박스도 그대로 있어야 한다.
    triggers = _workflow().get("on", _workflow().get(True))
    assert "publish_only" in triggers["workflow_dispatch"]["inputs"]


def _workflow() -> dict:
    from pathlib import Path

    import yaml

    path = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "collect.yml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


# ── 수집 암호 (2026-08-07) ──────────────────────────────────────────────


def test_a_manual_run_asks_for_a_password() -> None:
    """손으로 돌릴 때는 암호를 묻는다.

    **이 검사가 막는 것은 실수와 장난이지 침입이 아니다.** 여기까지 오려면
    이미 저장소에 쓰기 권한이 있어야 하고, 그건 GitHub이 먼저 막는다. 그
    위에 한 겹 더 두어 "아무나 두 시간짜리 전국 수집을 눌러 버리는" 일을
    막는다.
    """
    triggers = _workflow().get("on", _workflow().get(True))
    field = triggers["workflow_dispatch"]["inputs"]["password"]
    assert field["required"] is True

    step = _workflow()["jobs"]["collect"]["steps"][0]
    assert step["name"] == "Check collect password", "암호 검사가 맨 앞이 아니다"
    assert "secrets.DASHBOARD_PASSWORD" in str(step["env"])


def test_the_password_is_compared_in_the_shell_not_in_a_condition() -> None:
    """시크릿을 `if:` 식에 쓰면 그 식이 실행 화면에 그대로 보인다."""
    step = _workflow()["jobs"]["collect"]["steps"][0]
    assert "secrets." not in str(step["if"])
    assert "DASHBOARD_PASSWORD" not in str(step["if"])


def test_the_scheduled_and_merge_runs_never_need_a_password() -> None:
    """사람이 없는 경로에 암호를 걸면 그 암호를 또 어딘가 적어 둬야 한다."""
    step = _workflow()["jobs"]["collect"]["steps"][0]
    assert "github.event_name == 'workflow_dispatch'" in str(step["if"])
