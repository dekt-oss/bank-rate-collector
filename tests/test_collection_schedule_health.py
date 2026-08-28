"""정기 workflow trigger 지연이 초록불로 숨지 않는지 검증한다."""

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


def _run(created_at: str) -> dict:
    return {"created_at": created_at, "run_started_at": created_at}


def test_missing_today_schedule_turns_yellow_after_trigger_grace() -> None:
    # 2026-08-12 00:50 KST. core 00:17 / NH 00:37은 이미 예정됐지만
    # GitHub가 오늘 scheduled run을 하나도 만들지 않은 상황이다.
    result = _schedule([], "2026-08-11T15:50:00Z")
    assert result["cycle_date_kst"] == "2026-08-12"
    assert result["expected_count"] == 2
    assert result["observed_count"] == 0
    assert result["missing_count"] == 2
    assert result["status"] == "warning"


def test_missing_schedule_is_red_after_eight_am_hard_deadline() -> None:
    result = _schedule([], "2026-08-11T23:05:00Z")  # 08:05 KST
    assert result["cycle_date_kst"] == "2026-08-12"
    assert result["expected_count"] == 3
    assert result["missing_count"] == 3
    assert result["status"] == "breached"


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


def test_late_schedule_remains_yellow_even_when_all_runs_exist() -> None:
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


def test_live_signal_script_is_injected_once_and_only_worsens_static_signal() -> None:
    html = (
        '<html><body><button id="health-open">'
        '<span id="health-head-dot" class="health-dot green"></span>'
        '<span id="health-head-label">수집 정상</span></button>'
        '<button id="health-refresh"></button></body></html>'
    )
    rendered = inject_collection_health_live_signal(html)
    assert MARKER in rendered
    assert 'sla.status === "breached" || sla.status === "degraded"' in rendered
    assert '(ranks[live] || 0) <= (ranks[existing] || 0)' in rendered
    assert rendered.count(MARKER) == 1
    assert inject_collection_health_live_signal(rendered) == rendered
