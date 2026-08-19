import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WRITERS = (
    ROOT / ".github/workflows/collect.yml",
    ROOT / ".github/workflows/collect-savings-fast.yml",
    ROOT / ".github/workflows/nh-attempt.yml",
)


def _vercel() -> dict:
    return json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))


def test_git_deployments_are_blocked_except_rate_data() -> None:
    config = _vercel()
    assert config["git"]["deploymentEnabled"] == {"**": False, "rate-data": True}
    assert '"$VERCEL_GIT_COMMIT_REF" != "rate-data"' in config["ignoreCommand"]


def test_production_uses_vercel_static_files_without_raw_upstream() -> None:
    config = _vercel()
    assert "rewrites" not in config
    assert "raw.githubusercontent.com" not in json.dumps(config)
    assert not (ROOT / "web/api/live-page.js").exists()


def test_all_rate_data_writers_publish_the_static_site_with_same_vercel_config() -> None:
    for workflow in WRITERS:
        text = workflow.read_text(encoding="utf-8")
        assert "cp vercel.json stage/vercel.json" in text
        assert "HEAD:rate-data" in text
        assert "prepare_vercel_release.py" not in text


def test_static_branch_gate_has_no_release_mutation_helper() -> None:
    assert not (ROOT / "scripts/prepare_vercel_release.py").exists()
