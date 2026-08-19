"""Vercel release quota and live rate-data payload must stay separate."""

import json
from pathlib import Path

from scripts.prepare_vercel_release import enable_release

ROOT = Path(__file__).resolve().parents[1]


def _vercel() -> dict:
    return json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))


def test_repository_config_disables_all_automatic_git_deployments() -> None:
    config = _vercel()
    assert config["git"]["deploymentEnabled"] is False
    # Keep the older branch check as a second line of defense. It must never be
    # widened to feature/main branches.
    assert '"$VERCEL_GIT_COMMIT_REF" != "rate-data"' in config["ignoreCommand"]


def test_production_routes_read_current_rate_data_payload() -> None:
    config = _vercel()
    rewrites = {item["source"]: item["destination"] for item in config["rewrites"]}

    assert rewrites["/"] == "/api/live-page?page=index"
    assert rewrites["/index.html"] == "/api/live-page?page=index"
    assert rewrites["/strategy.html"] == "/api/live-page?page=strategy"
    assert rewrites["/data/:path*"] == (
        "https://raw.githubusercontent.com/dekt-oss/bank-rate-collector/"
        "rate-data/site-public/data/:path*"
    )
    assert rewrites["/site-manifest.json"] == (
        "https://raw.githubusercontent.com/dekt-oss/bank-rate-collector/"
        "rate-data/site-public/site-manifest.json"
    )


def test_release_config_allows_only_rate_data(tmp_path: Path) -> None:
    staged = tmp_path / "vercel.json"
    staged.write_text(json.dumps(_vercel()), encoding="utf-8")

    enable_release(staged)

    config = json.loads(staged.read_text(encoding="utf-8"))
    rules = config["git"]["deploymentEnabled"]
    assert rules == {"*": False, "rate-data": True}


def test_only_publish_only_core_run_enables_release_config() -> None:
    core = (ROOT / ".github/workflows/collect.yml").read_text(encoding="utf-8")
    fast = (ROOT / ".github/workflows/collect-savings-fast.yml").read_text(encoding="utf-8")
    nh = (ROOT / ".github/workflows/nh-attempt.yml").read_text(encoding="utf-8")

    assert 'if [ "${PUBLISH_ONLY}" = "true" ]; then' in core
    assert "scripts/prepare_vercel_release.py stage/vercel.json" in core
    assert "scripts/prepare_vercel_release.py" not in fast
    assert "scripts/prepare_vercel_release.py" not in nh

    # All three writers still publish the same canonical rate-data payload. The
    # staged config, not a second branch, decides whether that push is a release.
    for text in (core, fast, nh):
        assert "HEAD:rate-data" in text
        assert "cp vercel.json stage/vercel.json" in text


def test_live_page_function_is_fixed_to_known_pages_and_rate_data() -> None:
    text = (ROOT / "web/api/live-page.js").read_text(encoding="utf-8")
    assert 'const LIVE_BRANCH = "rate-data";' in text
    assert 'index: "index.html"' in text
    assert 'strategy: "strategy.html"' in text
    assert 'res.setHeader("content-type", "text/html; charset=utf-8")' in text
    assert 'res.setHeader("cache-control", "no-store, max-age=0")' in text
    assert "req.query && req.query.page" in text
    assert "rawUrl(req" not in text
