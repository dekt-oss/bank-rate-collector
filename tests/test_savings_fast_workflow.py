"""저축은행 경량 수집 lane의 실행 계약.

긴 전국 수집과 분리한 목적은 FINLIFE 저축은행과 저축은행중앙회만 하루 중
세 번 다시 확인하는 것이다. 크론 시간이나 수집원 범위가 조용히 넓어지면
비용·원천 부하·최신성 계약이 모두 달라지므로 정적으로 고정한다.
"""

import datetime as dt
from pathlib import Path

import yaml

WORKFLOW = (
    Path(__file__).resolve().parents[1] / ".github" / "workflows" / "collect-savings-fast.yml"
)


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _triggers(workflow: dict) -> dict:
    # PyYAML 1.1은 키 `on`을 bool True로 읽을 수 있다.
    return workflow.get("on", workflow.get(True))


def test_fast_lane_runs_weekdays_at_ten_three_and_six_kst() -> None:
    workflow = _workflow()
    schedules = _triggers(workflow)["schedule"]
    crons = [item["cron"] for item in schedules]
    assert crons == ["0 1 * * 1-5", "0 6 * * 1-5", "0 9 * * 1-5"]

    kst = dt.timezone(dt.timedelta(hours=9))
    expected_hours = [10, 15, 18]
    for cron, expected_hour in zip(crons, expected_hours, strict=True):
        utc_hour = int(cron.split()[1])
        for day in range(10, 15):  # 2026-08-10(월)~14(금)
            utc = dt.datetime(2026, 8, day, utc_hour, 0, tzinfo=dt.UTC)
            local = utc.astimezone(kst)
            assert local.weekday() < 5
            assert (local.hour, local.minute) == (expected_hour, 0)


def test_fast_lane_has_no_manual_or_push_trigger() -> None:
    triggers = _triggers(_workflow())
    assert set(triggers) == {"schedule"}


def test_fast_lane_serializes_with_the_existing_rate_data_writer() -> None:
    concurrency = _workflow()["concurrency"]
    assert concurrency["group"] == "rate-data-writer"
    assert concurrency["cancel-in-progress"] is False


def test_fast_lane_collects_only_the_two_savings_bank_sources() -> None:
    steps = _workflow()["jobs"]["collect-savings"]["steps"]
    collectors = [
        step for step in steps if str(step.get("name", "")).startswith("Collect ")
    ]
    assert [step["name"] for step in collectors] == [
        "Collect finlife savings bank",
        "Collect FSB",
    ]

    finlife = collectors[0]
    assert "--source finlife_savings_bank" in finlife["run"]
    assert "--groups 030300" in finlife["run"]
    assert "secrets.FINLIFE_API_KEY" in str(finlife["env"])

    fsb = collectors[1]
    assert "--source fsb" in fsb["run"]


def test_fast_lane_keeps_persistence_validation_and_publish_gates() -> None:
    steps = _workflow()["jobs"]["collect-savings"]["steps"]
    names = [step.get("name") for step in steps]
    required = {
        "Decide storage backend",
        "Restore previous database",
        "Apply migrations",
        "Snapshot",
        "Validate stored data",
        "Build dashboard",
        "Export full dataset",
        "Build public site",
        "Verify P1-A gate",
        "Volume gate",
        "Stage rate-data payload",
        "Size gate",
        "Upload state to R2",
        "Publish to rate-data branch",
    }
    assert required <= set(names)

    # 잘못 수집한 DB를 authoritative R2에 올리기 전에 데이터 게이트가 먼저 돈다.
    assert names.index("Verify P1-A gate") < names.index("Volume gate")
    assert names.index("Volume gate") < names.index("Upload state to R2")
    assert names.index("Size gate") < names.index("Upload state to R2")
    assert names.index("Upload state to R2") < names.index("Publish to rate-data branch")
