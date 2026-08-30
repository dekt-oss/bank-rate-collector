from pathlib import Path


def test_production_smoke_workflow_checks_anonymous_auth_boundary() -> None:
    workflow = Path('.github/workflows/production-smoke.yml').read_text(encoding='utf-8')
    assert 'Verify anonymous site access is blocked' in workflow
    assert 'anonymous root must redirect to login' in workflow
    assert 'anonymous /api/health must be blocked' in workflow
    assert 'root_status=$ROOT_STATUS' in workflow
    assert 'health_status=$HEALTH_STATUS' in workflow
