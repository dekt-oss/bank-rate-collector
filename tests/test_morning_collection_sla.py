"""Static contract for the next-business-morning collection SLA."""

from pathlib import Path

CORE = Path(".github/workflows/collect.yml").read_text(encoding="utf-8")
NH = Path(".github/workflows/collect-nh.yml").read_text(encoding="utf-8")
FUNDING = Path(".github/workflows/collect-institution-funding.yml").read_text(encoding="utf-8")
FAST = Path(".github/workflows/collect-savings-fast.yml").read_text(encoding="utf-8")


def test_morning_sla_crons_are_reserved_in_kst_order() -> None:
    # Previous evening, Sunday-Thursday -> next business morning Monday-Friday.
    assert '- cron: "30 8 * * 0-4"' in NH  # 17:30 KST NH
    assert '- cron: "40 8 * * 0-4"' in CORE  # 17:40 KST KFCC

    # After midnight KST; UTC is still the previous calendar day.
    assert '- cron: "15 15 * * 0-4"' in FUNDING  # 00:15 KST funding
    assert '- cron: "0 16 * * 0-4"' in CORE  # 01:00 KST core

    # collect.yml has two schedules, so its source-routing conditions must use
    # the exact same cron literals. Otherwise core and KFCC can swap scopes.
    assert "github.event.schedule == '40 8 * * 0-4'" in CORE
    assert "github.event.schedule == '0 16 * * 0-4'" in CORE


def test_evening_fast_refresh_does_not_compete_with_nightly_sla_lane() -> None:
    assert '- cron: "0 1 * * 1-5"' in FAST  # 10:00 KST
    assert '- cron: "0 6 * * 1-5"' in FAST  # 15:00 KST
    assert '- cron: "0 9 * * 1-5"' not in FAST  # retired 18:00 KST refresh


def test_canonical_writer_safety_is_preserved() -> None:
    for workflow in (CORE, NH, FUNDING, FAST):
        assert "group: rate-data-writer" in workflow
        assert "queue: max" in workflow
        assert "cancel-in-progress: false" in workflow


def _finish_time_with_uniform_scheduler_delay(delay_minutes: int) -> int:
    """Return serialized finish minute on an axis starting previous-day 00:00 KST."""

    # Recent production upper-bound observations used for scheduling capacity,
    # including acquisition, validation, site build and canonical publication.
    jobs = (
        (17 * 60 + 30, 267),  # NH: 4h27
        (17 * 60 + 40, 186),  # KFCC: ~3h06
        (24 * 60 + 15, 40),  # funding: ~40m
        (25 * 60, 69),  # core: ~1h09
    )
    writer_available = 0
    for scheduled_minute, duration in jobs:
        start = max(writer_available, scheduled_minute + delay_minutes)
        writer_available = start + duration
    return writer_available


def test_schedule_has_four_hour_scheduler_delay_budget_before_0730() -> None:
    deadline = 24 * 60 + 7 * 60 + 30
    nominal_finish = _finish_time_with_uniform_scheduler_delay(0)
    delayed_finish = _finish_time_with_uniform_scheduler_delay(4 * 60)

    # Nominally the serialized chain finishes around 02:52 KST, leaving a wide
    # recovery window. Even a uniform four-hour GitHub schedule delay still
    # finishes around 06:52 KST, before the 07:30 operational SLA.
    assert deadline - nominal_finish >= 4 * 60
    assert delayed_finish <= deadline
