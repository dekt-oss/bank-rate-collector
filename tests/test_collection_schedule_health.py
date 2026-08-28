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


def test_missing_today_schedule_is_diagnostic_warning_after_trigger_grace() -> None:
    # schedule SLA 자체는 warning이다. 상단 current-state 신호는 아래 별도 테스트에서
    # 현재 수집 유무를 합쳐 red/yellow로 결정한다.
    result = _schedule([], "2026-08-11T15:50:00Z")
    assert result["cycle_date_kst"] == "2026-08-12"
    assert result["expected_count"] == 2
    assert result["observed_count"] == 0
    assert result["missing_count"] == 2
    assert result["max_trigger_delay_minutes"] is None
    assert result["status"] == "warning"


def test_missing_schedule_is_diagnostic_breach_after_eight_am_hard_deadline() -> None:
    result = _schedule([], "2026-08-11T23:05:00Z")  # 08:05 KST
    assert result["cycle_date_kst"] == "2026-08-12"
    assert result["expected_count"] == 3
    assert result["missing_count"] == 3
    assert result["max_trigger_delay_minutes"] is None
    assert result["status"] == "breached"


def test_before_monday_first_trigger_uses_previous_business_cycle() -> None:
    # 월요일 00:10 KST에는 아직 월요일 core 00:17도 예정 전이다.
    # 이 시점에 월요일을 누락으로 만들지 않고 직전 금요일 완료 cycle을 본다.
    friday_runs = [
        _run("2026-08-06T15:17:30Z"),  # 8/7 00:17:30 KST
        _run("2026-08-06T15:37:20Z"),  # 8/7 00:37:20 KST
        _run("2026-08-06T19:17:40Z"),  # 8/7 04:17:40 KST
    ]
    result = _schedule(friday_runs, "2026-08-09T15:10:00Z")  # 8/10 월 00:10 KST
    assert result["cycle_date_kst"] == "2026-08-07"
    assert result["expected_count"] == 3
    assert result["missing_count"] == 0
    assert result["status"] == "normal"


def test_on_time_schedule_stays_normal() -> None:
    runs = [
        _run("2026-08-11T15:17:30Z"),  # 00:17:30 KST
        _run("2026-08-11T15:37:20Z"),  # 00:37:20 KST
        _run("2026-08-11T19:17:40Z"),  # 04:17:40 KST
    ]
    result = _schedule(runs, "2026-08-11T20:00:00Z")  # 05:00 KST
    assert result["expected_count"] == 3
    assert result["observed_count"] == 3
    assert result["missing_count"] == 0
    assert result["max_trigger_delay_minutes"] == 0
    assert result["status"] == "normal"


def test_late_schedule_keeps_diagnostic_warning_even_when_all_runs_exist() -> None:
    runs = [
        _run("2026-08-11T15:45:00Z"),  # core +28m
        _run("2026-08-11T16:00:00Z"),  # NH +23m
        _run("2026-08-11T19:30:00Z"),  # KFCC +13m
    ]
    result = _schedule(runs, "2026-08-11T20:00:00Z")
    assert result["missing_count"] == 0
    assert result["max_trigger_delay_minutes"] == 28
    assert result["status"] == "warning"


def test_schedule_warning_worsens_otherwise_normal_cycle_sla() -> None:
    script = f"""
      import {{ cycleSla }} from {json.dumps(HEALTH_API)};
      const anchor = {{ created_at: '2026-08-12T00:17:00+09:00' }};
      const source = {{ status: 'healthy', failed_sources: [], missing_sources: [] }};
      const schedule = {{
        status: 'warning', expected_count: 3, observed_count: 3,
        missing_count: 0, max_trigger_delay_minutes: 28,
      }};
      console.log(JSON.stringify(cycleSla(
        anchor,
        '2026-08-11T22:20:00Z',
        new Date('2026-08-11T22:20:00Z'),
        source,
        schedule,
      )));
    """
    result = _node(script)
    assert result["timing_status"] == "normal"
    assert result["schedule_status"] == "warning"
    assert result["status"] == "warning"
    assert result["schedule_max_delay_minutes"] == 28


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
            latest_publish_completed_at="2026-08-12T00:10:00Z",
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
