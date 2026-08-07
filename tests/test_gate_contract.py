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


def test_the_schedule_is_monday_wednesday_friday_at_two_am_kst() -> None:
    """월·수·금 02:00 KST.

    **요일이 하루 밀린다.** cron은 UTC로 도는데 02:00 KST는 전날 17:00
    UTC이므로, 월·수·금 새벽은 일·화·목(0,2,4) UTC다. 이걸 1,3,5로 적으면
    화·목·토 새벽에 돈다 — 조용히 틀리는 종류라 테스트로 박는다.
    """
    import datetime as dt
    from pathlib import Path

    import yaml

    workflow = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "collect.yml"
    # `on:`은 YAML 1.1에서 True로 읽힌다. 키를 그대로 두고 찾는다.
    loaded = yaml.safe_load(workflow.read_text(encoding="utf-8"))
    triggers = loaded.get("on", loaded.get(True))
    crons = [s["cron"] for s in triggers["schedule"]]
    assert crons == ["0 17 * * 0,2,4"]

    # 적어 둔 환산이 실제로 맞는지 되짚는다.
    kst = dt.timezone(dt.timedelta(hours=9))
    for day, weekday in ((10, "Mon"), (12, "Wed"), (14, "Fri")):
        local = dt.datetime(2026, 8, day, 2, 0, tzinfo=kst)
        assert local.strftime("%a") == weekday
        utc = local.astimezone(dt.UTC)
        assert utc.hour == 17
        assert (utc.weekday() + 1) % 7 in (0, 2, 4)


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
