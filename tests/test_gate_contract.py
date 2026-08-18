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
    monkeypatch.setenv("FINLIFE_API_KEY", "test")
    monkeypatch.setenv("ECOS_API_KEY", "test")


def _adapters() -> dict:
    from rate_monitor.cli import ADAPTERS

    return ADAPTERS


def test_every_adapter_declares_whether_it_gives_a_max_rate() -> None:
    missing = [
        name
        for name, cls in _adapters().items()
        if not hasattr(cls, "provides_max_rate")
    ]
    assert missing == [], f"provides_max_rate를 안 밝힌 수집원: {missing}"


def test_the_sources_without_a_max_rate_are_the_ones_we_measured() -> None:
    without = {
        name for name, cls in _adapters().items() if not cls.provides_max_rate
    }
    assert without == {"kfcc", "nh_local"}


def test_every_adapter_declares_its_sector() -> None:
    missing = [
        name for name, cls in _adapters().items() if not getattr(cls, "sector", None)
    ]
    assert missing == []


def test_the_gate_reads_the_adapters_instead_of_a_hand_list() -> None:
    assert "from rate_monitor.cli import ADAPTERS" in GATE
    assert "for source_id, adapter_cls in sorted(ADAPTERS.items()):" in GATE
    assert 'getattr(adapter_cls, "provides_max_rate", True)' in GATE


def test_the_gate_skips_a_source_it_has_no_data_for() -> None:
    assert "[건너뜀]" in GATE


def test_the_gate_reports_a_failed_source_without_blocking() -> None:
    assert "마지막 수집이 실패한 원천" in GATE
    assert "CONFIRMED_RUN_STATUSES" in GATE


def test_only_fixed_scope_sources_get_a_scope_check() -> None:
    fixed = {
        name
        for name, cls in _adapters().items()
        if getattr(cls, "expected_rate_scope", None)
    }
    assert fixed == {"finlife_bank", "finlife_savings_bank"}


# ── 수집 주기 ───────────────────────────────────────────────────────────


def _workflow() -> dict:
    import yaml

    path = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "collect.yml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _nh_workflow() -> dict:
    import yaml

    path = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "collect-nh.yml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _nh_attempt_workflow() -> dict:
    import yaml

    path = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "nh-attempt.yml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _triggers(workflow: dict) -> dict:
    return workflow.get("on", workflow.get(True))


def test_core_and_kfcc_schedules_keep_their_kst_times() -> None:
    """core 00:17, KFCC 04:17은 기존 시간 계약을 유지한다."""
    import datetime as dt

    crons = [s["cron"] for s in _triggers(_workflow())["schedule"]]
    assert crons == ["17 15 * * 0-4", "17 19 * * 0-4"]

    kst = dt.timezone(dt.timedelta(hours=9))
    cases = [(0, 17, 15), (4, 17, 19)]
    for local_hour, local_minute, utc_hour in cases:
        for day in range(10, 17):
            local = dt.datetime(
                2026, 8, day, local_hour, local_minute, tzinfo=kst
            )
            utc = local.astimezone(dt.UTC)
            assert (utc.hour, utc.minute) == (utc_hour, 17)
            cron_weekday = (utc.weekday() + 1) % 7
            caught = 0 <= cron_weekday <= 4
            weekday = local.weekday() < 5
            assert caught is weekday, f"{local:%m-%d %a %H:%M}가 어긋난다"


def test_nh_has_its_own_0037_kst_schedule() -> None:
    """NH는 core/KFCC와 별도 workflow에서 평일 00:37 KST에 시작한다."""
    import datetime as dt

    crons = [s["cron"] for s in _triggers(_nh_workflow())["schedule"]]
    assert crons == ["37 15 * * 0-4"]

    kst = dt.timezone(dt.timedelta(hours=9))
    for day in range(10, 17):
        local = dt.datetime(2026, 8, day, 0, 37, tzinfo=kst)
        utc = local.astimezone(dt.UTC)
        assert (utc.hour, utc.minute) == (15, 37)
        cron_weekday = (utc.weekday() + 1) % 7
        assert (0 <= cron_weekday <= 4) is (local.weekday() < 5)


def test_core_workflow_no_longer_contains_nh_collection() -> None:
    steps = _workflow()["jobs"]["collect"]["steps"]
    names = {str(step.get("name", "")) for step in steps}
    assert "Collect NH local" not in names
    assert "Prepare NH checkpoint context" not in names
    assert "Recover NH local" not in names


def test_the_two_core_crons_still_select_core_vs_kfcc() -> None:
    workflow = _workflow()
    crons = {s["cron"] for s in _triggers(workflow)["schedule"]}
    env = workflow["jobs"]["collect"]["env"]

    for key in ("KFCC_ONLY", "SKIP_KFCC_THIS_RUN"):
        quoted = [c for c in crons if f"'{c}'" in env[key]]
        assert len(quoted) == 1, f"{key}가 가리키는 크론이 schedule에 없다: {env[key]}"
    assert env["KFCC_ONLY"] != env["SKIP_KFCC_THIS_RUN"]


def test_each_core_scheduled_run_collects_the_expected_group() -> None:
    steps = _workflow()["jobs"]["collect"]["steps"]
    collectors = {
        s["name"]: str(s.get("if") or "")
        for s in steps
        if str(s.get("name", "")).startswith("Collect ")
    }
    assert collectors
    assert "Collect NH local" not in collectors

    kfcc = collectors.pop("Collect KFCC")
    assert "env.SKIP_KFCC_THIS_RUN != 'true'" in kfcc
    assert "env.KFCC_ONLY" not in kfcc

    for name, cond in collectors.items():
        assert "env.KFCC_ONLY != 'true'" in cond, f"{name}이 KFCC 실행에서도 돈다"
        assert "SKIP_KFCC_THIS_RUN" not in cond, f"{name}이 core 실행에서 빠진다"


def test_scope_default_lives_in_config_for_kfcc_and_nh() -> None:
    core_steps = _workflow()["jobs"]["collect"]["steps"]
    kfcc = next(s for s in core_steps if s.get("name") == "Collect KFCC")
    assert "${SCOPE:+--scope" in kfcc["run"]
    assert "||" not in kfcc["run"]

    nh_steps = _nh_attempt_workflow()["jobs"]["attempt"]["steps"]
    nh = next(s for s in nh_steps if s.get("name") == "Collect NH local")
    assert "${SCOPE:+--scope" in nh["run"]
    assert "||" not in nh["run"]


def test_a_merge_to_main_republishes_the_screen_by_itself() -> None:
    triggers = _triggers(_workflow())
    assert triggers["push"]["branches"] == ["main"]
    assert "paths" not in triggers["push"]


def test_a_push_never_hits_a_source_but_a_schedule_does() -> None:
    gate = _workflow()["jobs"]["collect"]["env"]["PUBLISH_ONLY"]
    assert "github.event_name == 'push'" in gate
    assert "inputs.manual_target == '화면만 재발행'" in gate
    assert "schedule" not in gate


def test_publish_only_skips_every_core_collector_but_still_publishes() -> None:
    steps = _workflow()["jobs"]["collect"]["steps"]
    skipped = {
        s["name"]
        for s in steps
        if str(s.get("name", "")).startswith("Collect ")
        and "PUBLISH_ONLY != 'true'" in str(s.get("if") or "")
    }
    collectors = {
        s["name"]
        for s in steps
        if str(s.get("name", "")).startswith("Collect ")
    }
    assert collectors
    assert collectors == skipped, f"안 꺼지는 수집 단계: {sorted(collectors - skipped)}"

    for name in ("Build public site", "Publish to rate-data branch", "Snapshot"):
        step = next(s for s in steps if s.get("name") == name)
        assert "PUBLISH_ONLY" not in str(step.get("if") or ""), name

    inputs = _triggers(_workflow())["workflow_dispatch"]["inputs"]
    assert "publish_only" not in inputs
    assert "화면만 재발행" in inputs["manual_target"]["options"]


# ── 수집 암호 ───────────────────────────────────────────────────────────


def test_a_manual_run_asks_for_a_password() -> None:
    field = _triggers(_workflow())["workflow_dispatch"]["inputs"]["password"]
    assert field["required"] is True

    step = _workflow()["jobs"]["collect"]["steps"][0]
    assert step["name"] == "Check collect password"
    assert "secrets.DASHBOARD_PASSWORD" in str(step["env"])


def test_the_password_is_compared_in_the_shell_not_in_a_condition() -> None:
    step = _workflow()["jobs"]["collect"]["steps"][0]
    assert "secrets." not in str(step["if"])
    assert "DASHBOARD_PASSWORD" not in str(step["if"])


def test_the_scheduled_and_merge_runs_never_need_a_password() -> None:
    step = _workflow()["jobs"]["collect"]["steps"][0]
    assert "github.event_name == 'workflow_dispatch'" in str(step["if"])
