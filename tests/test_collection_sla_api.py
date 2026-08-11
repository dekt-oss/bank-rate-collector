"""08:00 cycle SLA 경계값과 source 실패 결합을 실제 Node helper로 검증한다."""

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HEALTH_API = (ROOT / "web/api/health.js").as_uri()


def _sla(completed: str | None, now: str, source_state: dict | None = None) -> dict:
    completed_js = json.dumps(completed)
    source_state_js = json.dumps(source_state)
    script = f"""
      import {{ cycleSla }} from {json.dumps(HEALTH_API)};
      const run = {{ run_started_at: '2026-08-10T19:17:00Z' }};
      console.log(JSON.stringify(cycleSla(
        run,
        {completed_js},
        new Date({json.dumps(now)}),
        {source_state_js},
      )));
    """
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_publish_before_0730_is_normal() -> None:
    result = _sla("2026-08-10T22:20:00Z", "2026-08-10T22:20:00Z")
    assert result["cycle_date_kst"] == "2026-08-11"
    assert result["status"] == "normal"
    assert result["timing_status"] == "normal"
    assert result["normal_target_at"].endswith("T07:30:00+09:00")
    assert result["sla_deadline_at"].endswith("T08:00:00+09:00")


def test_publish_between_0730_and_0800_is_warning() -> None:
    result = _sla("2026-08-10T22:45:00Z", "2026-08-10T22:45:00Z")
    assert result["status"] == "warning"
    assert result["timing_status"] == "warning"


def test_publish_after_0800_is_breached() -> None:
    result = _sla("2026-08-10T23:05:00Z", "2026-08-10T23:05:00Z")
    assert result["status"] == "breached"
    assert result["timing_status"] == "breached"


def test_unfinished_cycle_moves_pending_warning_breached() -> None:
    assert _sla(None, "2026-08-10T22:00:00Z")["status"] == "pending"
    assert _sla(None, "2026-08-10T22:45:00Z")["status"] == "warning"
    assert _sla(None, "2026-08-10T23:05:00Z")["status"] == "breached"


def test_on_time_publish_with_failed_source_is_degraded_not_normal() -> None:
    source_state = {
        "status": "failed",
        "failed_sources": ["nh_local"],
        "missing_sources": [],
    }
    result = _sla(
        "2026-08-10T22:20:00Z",
        "2026-08-10T22:20:00Z",
        source_state,
    )
    assert result["timing_status"] == "normal"
    assert result["source_status"] == "failed"
    assert result["status"] == "degraded"
    assert result["failed_sources"] == ["nh_local"]


def test_late_publish_stays_breached_even_if_source_also_failed() -> None:
    source_state = {
        "status": "failed",
        "failed_sources": ["nh_local"],
        "missing_sources": [],
    }
    result = _sla(
        "2026-08-10T23:05:00Z",
        "2026-08-10T23:05:00Z",
        source_state,
    )
    assert result["timing_status"] == "breached"
    assert result["source_status"] == "failed"
    assert result["status"] == "breached"
