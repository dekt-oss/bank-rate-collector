"""Static contract for the next-business-morning collection SLA."""

from pathlib import Path

import yaml

MORNING = Path(".github/workflows/collect-morning-cycle.yml").read_text(encoding="utf-8")
CORE = Path(".github/workflows/collect.yml").read_text(encoding="utf-8")
NH = Path(".github/workflows/collect-nh.yml").read_text(encoding="utf-8")
FUNDING = Path(".github/workflows/collect-institution-funding.yml").read_text(encoding="utf-8")
FAST = Path(".github/workflows/collect-savings-fast.yml").read_text(encoding="utf-8")


def test_morning_sla_workflow_yaml_parses() -> None:
    for workflow in (MORNING, CORE, NH, FUNDING, FAST):
        assert isinstance(yaml.safe_load(workflow), dict)


def test_one_control_plane_schedule_owns_the_morning_cycle() -> None:
    # Reservation is deliberately earlier than collection. The gate prevents
    # source access before 20:30 KST while absorbing the observed GitHub delay.
    assert '- cron: "50 5 * * 0-4"' in MORNING  # 14:50 KST reservation
    assert "20:30 KST" in MORNING
    assert "14 * 60 + 50 <= minute_of_day < 20 * 60 + 30" in MORNING
    assert "20_400" in MORNING  # maximum nominal 14:50 -> 20:30 hold
    assert "timeout-minutes: 358" in MORNING

    # Child writers are no longer separately scheduled. One parent run determines
    # ordering, so downstream cron delays cannot add another 4-10 hours per stage.
    for retired in (
        '- cron: "30 8 * * 0-4"',
        '- cron: "40 8 * * 0-4"',
        '- cron: "15 15 * * 0-4"',
        '- cron: "17 16 * * 0-4"',
    ):
        assert retired not in NH
        assert retired not in CORE
        assert retired not in FUNDING


def test_morning_chain_preserves_order_and_combines_general_with_kfcc() -> None:
    assert "needs: gate" in MORNING
    assert "needs: nh" in MORNING
    assert "needs: funding" in MORNING
    assert 'manual_target: "아침 전체"' in MORNING

    # Parent attempt 1 starts a new business cycle fresh. rerun-failed-jobs keeps
    # the same cycle and therefore must resume durable NH/KFCC checkpoints.
    retry_mode = "${{ github.run_attempt == 1 && 'fresh' || 'auto' }}"
    assert f"nh_resume_mode: {retry_mode}" in MORNING
    assert f"kfcc_resume_mode: {retry_mode}" in MORNING

    # The internal morning target runs ordinary sources and KFCC in one canonical
    # writer pass, removing one duplicated restore/build/gate/R2 publication cycle.
    assert "MORNING_CYCLE: ${{ inputs.manual_target == '아침 전체' }}" in CORE
    assert "inputs.manual_target != '아침 전체'" in CORE
    assert "inputs.manual_target == '아침 전체'" in CORE


def test_fast_refresh_is_separate_but_budgeted_as_writer_contention() -> None:
    assert '- cron: "0 1 * * 1-5"' in FAST  # 10:00 KST
    assert '- cron: "0 6 * * 1-5"' in FAST  # 15:00 KST
    assert '- cron: "0 9 * * 1-5"' not in FAST  # retired 18:00 KST refresh
    # Parent is deliberately not reserved on the same 15:00 minute.
    assert '- cron: "0 6 * * 0-4"' not in MORNING


def test_canonical_writer_safety_is_preserved() -> None:
    # Child workflows still serialize every authoritative DB/R2/rate-data write.
    for workflow in (CORE, NH, FUNDING, FAST):
        assert "group: rate-data-writer" in workflow
        assert "queue: max" in workflow
        assert "cancel-in-progress: false" in workflow

    # The parent has a separate control-plane lock and does not replace the writer lock.
    assert "group: morning-sla-cycle" in MORNING
    assert "group: rate-data-writer" not in MORNING
    assert "cancel-in-progress: false" in MORNING


def _modeled_finish(delay_minutes: int, writer_contention_minutes: int = 50) -> int:
    """Return conservative finish minute on reservation-day 00:00 KST axis."""

    reservation = 14 * 60 + 50
    not_before = 20 * 60 + 30

    # Conservative recent-production budgets:
    # NH full writer pass 266m, funding 38m, combined general+KFCC 230m.
    # A separate 50m reserve covers the observed delayed 15:00 fast writer
    # (recent production runs occupied the writer for about 45-47 minutes).
    chain_minutes = 266 + 38 + 230
    actual_start = max(not_before, reservation + delay_minutes)
    return actual_start + writer_contention_minutes + chain_minutes


def test_reverse_scheduled_cycle_meets_0730_for_recent_observed_delay() -> None:
    normal_deadline = 24 * 60 + 7 * 60 + 30
    hard_deadline = 24 * 60 + 8 * 60

    on_time_finish = _modeled_finish(0)
    recent_max_finish = _modeled_finish(6 * 60 + 41)

    # Prompt reservation waits until 20:30. Even with the 50m writer reserve it
    # keeps more than one hour before the 07:30 normal target.
    assert normal_deadline - on_time_finish >= 60
    # 14:50 + observed 6h41 = 21:31; +50m writer reserve +8h54 chain = 07:15.
    assert recent_max_finish == 24 * 60 + 7 * 60 + 15
    assert recent_max_finish <= normal_deadline
    assert recent_max_finish <= hard_deadline


def test_historical_ten_hour_github_delay_is_explicitly_not_guaranteed() -> None:
    hard_deadline = 24 * 60 + 8 * 60
    historical_extreme_finish = _modeled_finish(10 * 60)

    # A GitHub-only schedule cannot guarantee the hard SLA under the historical
    # ~10h trigger delay. The ops document must keep this residual risk visible;
    # an independent external watchdog is a separate follow-up control plane.
    assert historical_extreme_finish > hard_deadline
