from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_SMOKE = ROOT / ".github" / "workflows" / "production-smoke.yml"
RATE_HISTORY_MAINTENANCE = (
    ROOT / ".github" / "workflows" / "rate-history-production-maintenance.yml"
)


def test_production_smoke_uses_site_access_credential_with_legacy_fallback() -> None:
    text = PRODUCTION_SMOKE.read_text(encoding="utf-8")

    assert (
        "DASHBOARD_PASSWORD: "
        "${{ secrets.SITE_ACCESS_PASSWORD || secrets.DASHBOARD_PASSWORD }}"
    ) in text
    assert "https://bank-rate-collector.vercel.app" in text


def test_production_smoke_does_not_weaken_authenticated_boundary() -> None:
    text = PRODUCTION_SMOKE.read_text(encoding="utf-8")

    assert "scripts/production_smoke.py" in text
    assert "--expected-manifest published/site-public/site-manifest.json" in text
    assert "--attempts 20" in text
    assert "--timeout 20" in text


def test_rate_history_production_maintenance_is_main_ref_only() -> None:
    text = RATE_HISTORY_MAINTENANCE.read_text(encoding="utf-8")

    assert "- name: Require main ref for destructive maintenance" in text
    assert 'test "${GITHUB_REF}" = "refs/heads/main"' in text
    assert 'test "${GITHUB_SHA}" = "$(git rev-parse HEAD)"' in text
    assert "group: rate-data-writer" in text
    assert "cancel-in-progress: false" in text
