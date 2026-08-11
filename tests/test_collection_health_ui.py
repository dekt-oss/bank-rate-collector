"""관리자 수집 상태 UI와 read-only API의 배포 계약."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = (ROOT / "web/templates/site.html").read_text(encoding="utf-8")
API = (ROOT / "web/api/health.js").read_text(encoding="utf-8")
SITE_SERVICE = (ROOT / "src/rate_monitor/services/site_service.py").read_text(encoding="utf-8")


def test_health_payload_is_inlined_and_ui_has_a_manual_refresh() -> None:
    assert '"collection_health"' in SITE_SERVICE
    assert 'id="health-open"' in SITE
    assert 'id="health-panel"' in SITE
    assert 'id="health-refresh"' in SITE
    assert 'const HEALTH_ENDPOINT = "api/health"' in SITE


def test_traffic_light_has_text_as_well_as_color() -> None:
    for signal in ("green", "yellow", "red", "blue", "gray"):
        assert f".health-dot.{signal}" in SITE
    for label in ("정상", "확인 필요", "실패·지연", "진행 중", "대상 아님"):
        assert label in SITE
    assert 'id="health-head-dot"' in SITE
    assert 'id="health-head-label"' in SITE
    assert '$("health-head-dot").className' in SITE


def test_health_api_is_read_only_and_sanitized() -> None:
    assert 'req.method !== "GET"' in API
    assert "GITHUB_DISPATCH_TOKEN" in API
    assert "workflow_runs" in API and "/jobs?per_page=20" in API
    assert "source_steps" in API and "pipeline_steps" in API
    assert "logs_url" not in API
    assert "authorization" in API  # server-side request only
    assert "token," not in API.split("return json(res, 200", 1)[-1]


def test_health_api_never_requires_or_returns_the_collect_password() -> None:
    assert "DASHBOARD_PASSWORD" not in API
    assert "password" not in API.lower()


def test_live_pipeline_includes_the_publish_gates() -> None:
    """수집만 성공하고 gate가 실패한 작업을 전체 정상으로 보이면 안 된다."""
    assert '"Verify P1-A gate": "p1a_gate"' in API
    assert '"Size gate": "size_gate"' in API
    assert '"Volume gate": "volume_gate"' in API
    assert '"Publish to rate-data branch": "publish"' in API


def test_live_health_exposes_eight_am_cycle_sla() -> None:
    assert "export const cycleSla" in API
    assert "normal_target_at: normalTargetAt" in API
    assert "sla_deadline_at: deadlineAt" in API
    assert "latest_publish_completed_at: publishCompletedAt || null" in API
    assert "runs?event=schedule&per_page=20" in API
    assert "finisher?.pipelineSteps.publish" in API
    assert "08:00 SLA" in SITE
    assert 'body.sla ? "<br>" + slaLine(body.sla)' in SITE


def test_cycle_sla_does_not_hide_failed_sources() -> None:
    assert "cycleSourceState" in API
    assert 'status = "failed"' in API
    assert 'status = "degraded"' in API
    assert "failed_sources" in API
    assert "missing_sources" in API
    assert "일부 원천 실패" in SITE
    assert 'status = "unknown"' in API
    assert "판정 불가" in SITE
