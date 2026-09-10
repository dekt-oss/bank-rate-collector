import sqlite3
from pathlib import Path

from scripts.rate_history_audit import audit_rate_history


def _build_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE collection_runs (
              id TEXT PRIMARY KEY,
              source_id TEXT NOT NULL
            );
            CREATE TABLE product_variants (
              id TEXT PRIMARY KEY
            );
            CREATE TABLE rate_observations (
              id TEXT PRIMARY KEY,
              variant_id TEXT NOT NULL,
              run_id TEXT NOT NULL,
              observed_at TEXT NOT NULL,
              valid_from TEXT NOT NULL,
              valid_to TEXT,
              base_rate TEXT,
              max_rate TEXT,
              raw_preference_text TEXT NOT NULL,
              source_effective_at TEXT
            );
            """
        )
        conn.executemany(
            "INSERT INTO collection_runs(id, source_id) VALUES (?, ?)",
            [("r1", "nh_local"), ("r2", "nh_local"), ("r3", "nh_local"), ("r4", "kfcc")],
        )
        conn.execute("INSERT INTO product_variants(id) VALUES ('v1')")
        conn.executemany(
            """
            INSERT INTO rate_observations(
              id, variant_id, run_id, observed_at, valid_from, valid_to,
              base_rate, max_rate, raw_preference_text, source_effective_at
            ) VALUES (?, 'v1', ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("o1", "r1", "2026-09-01", "2026-09-01", "2026-09-02", "3.10", None, "", "2026-09-01"),
                # Same rate/preference and source. Only the effective date moved:
                # this is redundant under the change-only history contract.
                ("o2", "r2", "2026-09-02", "2026-09-02", "2026-09-03", "3.10", None, "", "2026-09-02"),
                # A real rate change must remain history.
                ("o3", "r3", "2026-09-03", "2026-09-03", "2026-09-04", "3.20", None, "", "2026-09-03"),
                # Same numeric value but a different source is not a compaction candidate.
                ("o4", "r4", "2026-09-04", "2026-09-04", None, "3.20", None, "", "2026-09-04"),
            ],
        )
        conn.commit()
    finally:
        conn.close()


def test_audit_identifies_effective_date_only_history_without_cross_source_fold(tmp_path: Path) -> None:
    db = tmp_path / "rates.sqlite3"
    _build_db(db)

    report = audit_rate_history(db)

    assert report["rate_observations"] == 4
    assert report["product_variants"] == 1
    assert report["semantic_redundant_rows"] == 1
    assert report["effective_date_only_rows"] == 1
    assert report["estimated_rows_after_semantic_compaction"] == 3
    assert report["by_source"]["nh_local"]["redundant_consecutive_rows"] == 1
    assert report["by_source"]["kfcc"]["redundant_consecutive_rows"] == 0
