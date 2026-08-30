import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WRITERS = (
    ROOT / ".github/workflows/collect.yml",
    ROOT / ".github/workflows/collect-savings-fast.yml",
    ROOT / ".github/workflows/nh-attempt.yml",
)


def test_all_rate_data_writers_publish_site_auth_runtime():
    for path in WRITERS:
        text = path.read_text(encoding="utf-8")
        assert "cp web/runtime/middleware.js stage/middleware.js" in text, path
        assert "cp web/runtime/auth-core.mjs stage/auth-core.mjs" in text, path
        assert "cp web/runtime/package.json stage/package.json" in text, path
        assert "stage/middleware.js stage/auth-core.mjs stage/package.json" in text, path
        assert "middleware.js auth-core.mjs package.json" in text, path


def test_vercel_runtime_installs_pinned_middleware_dependency():
    config = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
    assert config["outputDirectory"] == "site-public"
    assert config["installCommand"] == (
        "npm install --omit=dev --ignore-scripts --no-audit --no-fund"
    )

    package = json.loads((ROOT / "web/runtime/package.json").read_text(encoding="utf-8"))
    assert package["dependencies"]["@vercel/functions"] == "3.9.5"
