import json
from pathlib import Path

from scripts.prepare_vercel_release import enable_release

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
    assert config["git"]["deploymentEnabled"] == {"*": False, "rate-data": True}
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


def test_publish_only_release_helper_is_idempotent_with_static_branch_gate(
    tmp_path: Path,
) -> None:
    staged = tmp_path / "vercel.json"
    staged.write_text(json.dumps(_vercel()), encoding="utf-8")

    enable_release(staged)

    config = json.loads(staged.read_text(encoding="utf-8"))
    assert config["git"]["deploymentEnabled"] == {"*": False, "rate-data": True}
    assert "rewrites" not in config
