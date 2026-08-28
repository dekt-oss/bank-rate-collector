"""P1-A schema gate가 extension 모델을 놓치지 않는지 검증한다."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
GATE = REPO_ROOT / "scripts" / "verify_gate.py"


def test_schema_gate_accepts_registered_institution_funding_table(tmp_path: Path) -> None:
    """PR #223의 funding table이 "알 수 없는 extra table"로 오판되지 않는다."""
    import rate_monitor.db.institution_funding_models  # noqa: F401
    from rate_monitor.db.models import Base
    from rate_monitor.db.session import create_db_engine

    db = tmp_path / "publish.sqlite3"
    engine = create_db_engine(db)
    Base.metadata.create_all(engine)
    engine.dispose()

    assert "institution_funding_observations" in Base.metadata.tables
    expected_count = len(Base.metadata.tables)

    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"sqlite_sha256": "not-relevant", "row_counts": {}}),
        encoding="utf-8",
    )
    summary = tmp_path / "summary.json"
    summary.write_text(json.dumps({"totals": {}}), encoding="utf-8")
    site = tmp_path / "index.html"
    site.write_text(
        '<script id="rate-monitor-data" type="application/json">'
        '{"totals": {}}</script>',
        encoding="utf-8",
    )
    raw_root = tmp_path / "raw"
    raw_root.mkdir()

    done = subprocess.run(
        [
            sys.executable,
            str(GATE),
            "--db",
            str(db),
            "--manifest",
            str(manifest),
            "--summary",
            str(summary),
            "--site",
            str(site),
            "--raw-root",
            str(raw_root),
            "--no-collection",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    schema_lines = [
        line for line in done.stdout.splitlines() if "SQLite 표가 모델과 같은가" in line
    ]
    assert schema_lines == [
        f"  [PASS] SQLite 표가 모델과 같은가 — {expected_count}종, 모델과 일치"
    ]
    assert "[FAIL] SQLite 표가 모델과 같은가" not in done.stdout
