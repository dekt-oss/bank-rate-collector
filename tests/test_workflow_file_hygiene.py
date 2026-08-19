from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASE_WORKFLOWS = (
    ".github/workflows/collect.yml",
    ".github/workflows/collect-savings-fast.yml",
    ".github/workflows/nh-attempt.yml",
    ".github/workflows/production-smoke.yml",
)


def test_release_workflows_end_with_newline() -> None:
    for relative in RELEASE_WORKFLOWS:
        data = (ROOT / relative).read_bytes()
        assert data.endswith(b"\n"), relative
