from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_SMOKE = ROOT / ".github" / "workflows" / "production-smoke.yml"


def test_production_smoke_uses_exact_middleware_password_namespace() -> None:
    text = PRODUCTION_SMOKE.read_text(encoding="utf-8")

    assert "DASHBOARD_PASSWORD: ${{ secrets.DASHBOARD_PASSWORD }}" in text
    assert "secrets.SITE_ACCESS_PASSWORD || secrets.DASHBOARD_PASSWORD" not in text
    assert "https://bank-rate-collector.vercel.app" in text


def test_production_smoke_does_not_weaken_authenticated_boundary() -> None:
    text = PRODUCTION_SMOKE.read_text(encoding="utf-8")

    assert "scripts/production_smoke.py" in text
    assert "--expected-manifest published/site-public/site-manifest.json" in text
    assert "--attempts 20" in text
    assert "--timeout 20" in text
