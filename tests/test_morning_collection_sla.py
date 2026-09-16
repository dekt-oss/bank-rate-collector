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
    assert '- cron: "0 6 * * 0-4"' in MORNING  # 15:00 KST reservation
    assert "20:30 KST" in MORNING
    assert "15 * 60 <= minute_of_day < 20 * 60 + 30" in MORNING
    assert "19_800" in MORNING  # maximum nominal 15:00 -> 20:30 hold

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
    assert "nh_resume_mode: fresh" in MORNING
    assert "kfcc_resume_mode: fresh" in MORNING

    # The internal morning target runs ordinary sources and KFCC in one canonical
    # writer pass, removing one duplicated restore/build/gate/R2 publication cycle.
    assert "MORNING_CYCLE: ${{ inputs.manual_target == '아침 전체' }}" in CORE
    assert "inputs.manual_target != '아침 전체'" in CORE
    assert "inputs.manual_target == '아침 전체'" in CORE


def test_evening_fast_refresh_does_not_compete_with_nightly_sla_lane() -> None:
    assert '- cron: "0 1 * * 1-5"' in FAST  # 10:00 KST
    assert '- cron: "0 6 * * 1-5"' in FAST  # 15:00 KST
    assert '- cron: "0 9 * * 1-5"' not in FAST  # retired 18:00 KST refresh


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


def _modeled_finish(delay_minutes: int) -> int:
    """Return finish minute on an axis starting reservation-day 00:00 KST."""

    reservation = 15 * 60
    not_before = 20 * 60 + 30

    # Conservative model from the recent successful production cycle:
    # NH full writer pass ~265m -> 266m rounded up.
    # funding full writer pass ~37m -> 38m rounded up.
    # KFCC ~201m + general/core ~75m share one ~50m publication tail in the
    # combined morning target, so 230m leaves margin above the de-duplicated path.
    chain_minutes = 266 + 38 + 230
    actual_start = max(not_before, reservation + delay_minutes)
    return actual_start + chain_minutes


def test_reverse_scheduled_cycle_meets_0730_for_recent_observed_delay() -> None:
    normal_deadline = 24 * 60 + 7 * 60 + 30
    hard_deadline = 24 * 60 + 8 * 60

    on_time_finish = _modeled_finish(0)
    recent_max_finish = _modeled_finish(6 * 60 + 41)

    # Prompt reservation waits until 20:30 and still leaves >2h before 07:30.
    assert normal_deadline - on_time_finish >= 2 * 60
    # Recent observed maximum scheduler delay (~6h41) starts around 21:41 and
    # remains inside the normal 07:30 SLA with the conservative combined model.
    assert recent_max_finish <= normal_deadline
    assert recent_max_finish <= hard_deadline


def test_historical_ten_hour_github_delay_is_explicitly_not_guaranteed() -> None:
    hard_deadline = 24 * 60 + 8 * 60
    historical_extreme_finish = _modeled_finish(10 * 60)

    # A GitHub-only schedule cannot guarantee the hard SLA under the historical
    # ~10h trigger delay. The ops document must keep this residual risk visible;
    # an independent external watchdog is a separate follow-up control plane.
    assert historical_extreme_finish > hard_deadline
