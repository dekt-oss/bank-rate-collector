"""정기 workflow 지연과 현재 수집 상태가 신호등에 정확히 반영되는지 검증한다."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from rate_monitor.services.collection_health_live_presentation import (
    MARKER,
    inject_collection_health_live_signal,
)

ROOT = Path(__file__).resolve().parents[1]
HEALTH_API = (ROOT / "web/api/health.js").as_uri()


def _node(script: str) -> dict:
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def _schedule(runs: list[dict], now: str) -> dict:
    script = f"""
      import {{ scheduleTriggerHealth }} from {json.dumps(HEALTH_API)};
      console.log(JSON.stringify(scheduleTriggerHealth(
        {json.dumps(runs)},
        new Date({json.dumps(now)}),
      )));
    """
    return _node(script)


def _signal(sla: dict, active_collection: dict | None = None) -> dict:
    script = f"""
      import {{ operationalSignal }} from {json.dumps(HEALTH_API)};
      console.log(JSON.stringify(operationalSignal(
        {json.dumps(sla)},
        {json.dumps(active_collection)},
      )));
    """
    return _node(script)


def _run(created_at: str) -> dict:
    return {"created_at": created_at, "run_started_at": created_at}


def _sla(**overrides: object) -> dict:
    value: dict[str, object] = {
        "status": "warning",
        "source_status": "pending",
        "schedule_status": "warning",
        "timing_status": "pending",
        "latest_publish_completed_at": None,
    }
    value.update(overrides)
    return value


def test_missing_parent_before_actual_start_lower_bound_is_pending() -> None:
    # Sunday 20:00 KST. Parent reservation was due at 14:50, but 20:30 is the
    # actual-source not-before boundary, so absence is not yet an operational miss.
    result = _schedule([], "2026-08-09T11:00:00Z")
    assert result["cycle_date_kst"] == "2026-08-10"
    assert result["expected_count"] == 1
    assert result["observed_count"] == 0
    assert result["missing_count"] == 1
    assert result["reservation_at"] == "2026-08-09T14:50:00+09:00"
    assert result["actual_start_not_before_at"] == "2026-08-09T20:30:00+09:00"
    assert result["status"] == "pending"


def test_missing_parent_after_actual_start_lower_bound_is_warning() -> None:
    result = _schedule([], "2026-08-09T11:31:00Z")  # Sunday 20:31 KST
    assert result["cycle_date_kst"] == "2026-08-10"
    assert result["missing_count"] == 1
    assert result["status"] == "warning"


def test_missing_parent_after_eight_am_hard_deadline_is_breached() -> None:
    result = _schedule([], "2026-08-09T23:05:00Z")  # Monday 08:05 KST
    assert result["cycle_date_kst"] == "2026-08-10"
    assert result["missing_count"] == 1
    assert result["status"] == "breached"


def test_parent_created_before_not_before_boundary_is_schedule_normal() -> None:
    runs = [_run("2026-08-09T11:00:00Z")]  # Sunday 20:00 KST
    result = _schedule(runs, "2026-08-09T11:05:00Z")
    assert result["cycle_date_kst"] == "2026-08-10"
    assert result["observed_count"] == 1
    assert result["missing_count"] == 0
    assert result["max_trigger_delay_minutes"] == 310
    assert result["scheduler_budget_minutes"] == 401
    assert result["status"] == "normal"


def test_recent_6h41_scheduler_delay_is_attributed_to_same_cycle_and_warns() -> None:
    runs = [_run("2026-08-09T12:31:00Z")]  # Sunday 21:31 KST = +6h41
    result = _schedule(runs, "2026-08-09T12:35:00Z")
    assert result["cycle_date_kst"] == "2026-08-10"
    assert result["max_trigger_delay_minutes"] == 401
    assert result["status"] == "warning"


def test_delayed_parent_crossing_midnight_stays_in_next_business_cycle() -> None:
    runs = [_run("2026-08-09T16:00:00Z")]  # Monday 01:00 KST, +10h10
    result = _schedule(runs, "2026-08-09T16:05:00Z")
    assert result["cycle_date_kst"] == "2026-08-10"
    assert result["observed_count"] == 1
    assert result["max_trigger_delay_minutes"] == 610
    assert result["status"] == "warning"


def test_grossly_late_run_is_not_misattributed_across_reservation_boundaries() -> None:
    # +18h10 exceeds the bounded attribution window. It must not be invented as
    # proof for Monday's cycle; by 09:05 KST the cycle is already breached.
    runs = [_run("2026-08-10T00:00:00Z")]  # Monday 09:00 KST
    result = _schedule(runs, "2026-08-10T00:05:00Z")
    assert result["cycle_date_kst"] == "2026-08-10"
    assert result["observed_count"] == 0
    assert result["missing_count"] == 1
    assert result["status"] == "breached"


def test_weekend_keeps_friday_cycle_until_sunday_reservation() -> None:
    friday_run = _run("2026-08-13T11:00:00Z")  # Thursday 20:00 KST -> Friday cycle
    saturday = _schedule([friday_run], "2026-08-15T03:00:00Z")  # Saturday noon KST
    sunday_before = _schedule([friday_run], "2026-08-16T05:40:00Z")  # Sun 14:40 KST
    sunday_after = _schedule([friday_run], "2026-08-16T05:55:00Z")  # Sun 14:55 KST

    assert saturday["cycle_date_kst"] == "2026-08-14"
    assert saturday["status"] == "normal"
    assert sunday_before["cycle_date_kst"] == "2026-08-14"
    assert sunday_after["cycle_date_kst"] == "2026-08-17"
    assert sunday_after["status"] == "pending"


def test_schedule_warning_worsens_otherwise_normal_cycle_sla() -> None:
    script = f"""
      import {{ cycleSla }} from {json.dumps(HEALTH_API)};
      const anchor = {{ created_at: '2026-08-10T00:00:00+09:00' }};
      const source = {{ status: 'healthy', failed_sources: [], missing_sources: [] }};
      const schedule = {{
        status: 'warning', expected_count: 1, observed_count: 1,
        missing_count: 0, max_trigger_delay_minutes: 401,
      }};
      console.log(JSON.stringify(cycleSla(
        anchor,
        '2026-08-09T22:20:00Z',
        new Date('2026-08-09T22:20:00Z'),
        source,
        schedule,
      )));
    """
    result = _node(script)
    assert result["timing_status"] == "normal"
    assert result["schedule_status"] == "warning"
    assert result["status"] == "warning"
    assert result["schedule_max_delay_minutes"] == 401


def test_missed_schedule_without_current_collection_is_red() -> None:
    result = _signal(_sla(schedule_status="warning"))
    assert result == {
        "status": "breached",
        "reason": "recovery_required_not_running",
        "active_collection": False,
    }


def test_missed_schedule_with_current_collection_is_yellow() -> None:
    result = _signal(
        _sla(schedule_status="warning"),
        {"status": "in_progress"},
    )
    assert result == {
        "status": "warning",
        "reason": "recovery_running",
        "active_collection": True,
    }


def test_failed_source_without_recovery_is_red() -> None:
    result = _signal(
        _sla(
            status="degraded",
            source_status="failed",
            schedule_status="normal",
        )
    )
    assert result["status"] == "breached"
    assert result["reason"] == "recovery_required_not_running"


def test_failed_source_with_recovery_running_is_yellow() -> None:
    result = _signal(
        _sla(
            status="degraded",
            source_status="failed",
            schedule_status="normal",
        ),
        {"status": "queued"},
    )
    assert result["status"] == "warning"
    assert result["reason"] == "recovery_running"


def test_late_but_completed_healthy_cycle_recovers_to_green() -> None:
    result = _signal(
        _sla(
            status="breached",
            source_status="healthy",
            schedule_status="warning",
            timing_status="breached",
            latest_publish_completed_at="2026-08-10T00:10:00Z",
        )
    )
    assert result["status"] == "normal"
    assert result["reason"] == "cycle_complete"


def test_on_time_unfinished_collection_is_blue_not_yellow() -> None:
    result = _signal(
        _sla(
            status="pending",
            source_status="pending",
            schedule_status="normal",
            timing_status="pending",
        ),
        {"status": "in_progress"},
    )
    assert result["status"] == "pending"
    assert result["reason"] == "on_time_collection_running"


def test_live_signal_script_uses_current_signal_and_static_only_as_fallback() -> None:
    html = (
        '<html><body><button id="health-open">'
        '<span id="health-head-dot" class="health-dot green"></span>'
        '<span id="health-head-label">수집 정상</span></button>'
        '<button id="health-refresh"></button></body></html>'
    )
    rendered = inject_collection_health_live_signal(html)
    assert MARKER in rendered
    assert "apply(body.signal || body.sla)" in rendered
    assert 'yellow: "지연·수집 중"' in rendered
    assert 'red: "미수집·실패"' in rendered
    assert "dot.className = `health-dot ${live}`" in rendered
    assert "restoreBaseline();" in rendered
    assert "ranks" not in rendered
    assert rendered.count(MARKER) == 1
    assert inject_collection_health_live_signal(rendered) == rendered
