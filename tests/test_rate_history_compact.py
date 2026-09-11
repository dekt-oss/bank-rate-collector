import sqlite3
from pathlib import Path

import pytest
from scripts.rate_history_compact import compact_rate_history


def _build_db(path: Path, *, with_fk_reference: bool = False) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            PRAGMA foreign_keys=ON;
            CREATE TABLE collection_runs (
              id TEXT PRIMARY KEY,
              source_id TEXT NOT NULL
            );
            CREATE TABLE rate_observations (
              id TEXT PRIMARY KEY,
              variant_id TEXT NOT NULL,
              run_id TEXT NOT NULL,
              last_run_id TEXT NOT NULL,
              raw_artifact_id TEXT NOT NULL,
              as_of TEXT,
              observed_at TEXT NOT NULL,
              first_seen_at TEXT NOT NULL,
              last_seen_at TEXT NOT NULL,
              seen_count INTEGER NOT NULL,
              valid_from TEXT NOT NULL,
              valid_to TEXT,
              base_rate TEXT,
              max_rate TEXT,
              raw_preference_text TEXT NOT NULL,
              content_hash TEXT NOT NULL,
              source_effective_at TEXT
            );
            CREATE UNIQUE INDEX uq_rate_observations_current
              ON rate_observations(variant_id)
              WHERE valid_to IS NULL;
            CREATE TABLE manual_overrides (
              id TEXT PRIMARY KEY,
              target_type TEXT NOT NULL,
              target_id TEXT
            );
            """
        )
        conn.executemany(
            "INSERT INTO collection_runs(id, source_id) VALUES (?, 'nh_local')",
            [("r1",), ("r2",), ("r3",), ("r4",)],
        )
        conn.executemany(
            """
            INSERT INTO rate_observations(
              id, variant_id, run_id, last_run_id, raw_artifact_id,
              as_of, observed_at, first_seen_at, last_seen_at, seen_count,
              valid_from, valid_to, base_rate, max_rate, raw_preference_text,
              content_hash, source_effective_at
            ) VALUES (?, 'v1', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, '', ?, ?)
            """,
            [
                (
                    "o1",
                    "r1",
                    "r1",
                    "a1",
                    "2026-09-01",
                    "2026-09-01",
                    "2026-09-01",
                    "2026-09-01",
                    1,
                    "2026-09-01",
                    "2026-09-02",
                    "003.1000",
                    "legacy-1",
                    "2026-09-01",
                ),
                (
                    "o2",
                    "r2",
                    "r2",
                    "a2",
                    "2026-09-02",
                    "2026-09-02",
                    "2026-09-02",
                    "2026-09-02",
                    2,
                    "2026-09-02",
                    "2026-09-03",
                    "003.1000",
                    "legacy-2",
                    "2026-09-02",
                ),
                (
                    "o3",
                    "r3",
                    "r3",
                    "a3",
                    "2026-09-03",
                    "2026-09-03",
                    "2026-09-03",
                    "2026-09-03",
                    1,
                    "2026-09-03",
                    "2026-09-04",
                    "003.2000",
                    "legacy-3",
                    "2026-09-03",
                ),
                (
                    "o4",
                    "r4",
                    "r4",
                    "a4",
                    "2026-09-04",
                    "2026-09-04",
                    "2026-09-04",
                    "2026-09-05",
                    3,
                    "2026-09-04",
                    None,
                    "003.2000",
                    "legacy-4",
                    "2026-09-04",
                ),
            ],
        )
        if with_fk_reference:
            conn.executescript(
                """
                CREATE TABLE preference_conditions (
                  id TEXT PRIMARY KEY,
                  observation_id TEXT NOT NULL
                    REFERENCES rate_observations(id)
                );
                INSERT INTO preference_conditions(id, observation_id)
                VALUES ('p1', 'o2');
                """
            )
        conn.commit()
    finally:
        conn.close()


def _rows(path: Path) -> list[tuple]:
    conn = sqlite3.connect(path)
    try:
        return conn.execute(
            """
            SELECT id, run_id, last_run_id, first_seen_at, last_seen_at,
                   seen_count, valid_from, valid_to, base_rate, source_effective_at
            FROM rate_observations
            ORDER BY valid_from, id
            """
        ).fetchall()
    finally:
        conn.close()


def test_dry_run_reports_candidates_without_mutating_database(tmp_path: Path) -> None:
    db = tmp_path / "rates.sqlite3"
    _build_db(db)
    before = db.read_bytes()

    report = compact_rate_history(db)

    assert report["mode"] == "dry-run"
    assert report["candidate_rows"] == 2
    assert report["candidate_groups"] == 2
    assert report["estimated_rate_observations_after"] == 2
    assert report["candidate_rows_by_source"] == {"nh_local": 2}
    assert db.read_bytes() == before


def test_apply_collapses_only_consecutive_equal_values_and_preserves_current(
    tmp_path: Path,
) -> None:
    db = tmp_path / "rates.sqlite3"
    compacted = tmp_path / "rates-compacted.sqlite3"
    _build_db(db)

    report = compact_rate_history(db, apply=True, vacuum_into=compacted)

    assert report["before_rate_observations"] == 4
    assert report["candidate_rows"] == 2
    assert report["after_rate_observations"] == 2
    assert report["before_current_observations"] == 1
    assert report["after_current_observations"] == 1
    assert report["integrity_check"] == "ok"
    assert report["foreign_key_errors"] == 0

    rows = _rows(compacted)
    assert [row[8] for row in rows] == ["003.1000", "003.2000"]
    # The first semantic segment keeps its first-seen identity but accumulates sightings.
    assert rows[0][0:3] == ("o1", "r1", "r2")
    assert rows[0][4] == "2026-09-02"
    assert rows[0][5] == 3
    assert rows[0][7] == "2026-09-03"
    assert rows[0][9] == "2026-09-02"
    # The current segment remains current and carries the latest provenance/run.
    assert rows[1][0:3] == ("o3", "r3", "r4")
    assert rows[1][4] == "2026-09-05"
    assert rows[1][5] == 4
    assert rows[1][7] is None
    assert rows[1][9] == "2026-09-04"


def test_apply_fails_closed_when_candidate_has_foreign_key_reference(tmp_path: Path) -> None:
    db = tmp_path / "rates.sqlite3"
    compacted = tmp_path / "rates-compacted.sqlite3"
    _build_db(db, with_fk_reference=True)

    dry_run = compact_rate_history(db)
    assert dry_run["reference_blockers"] == [
        {
            "kind": "foreign_key",
            "table": "preference_conditions",
            "column": "observation_id",
            "rows": 1,
        }
    ]

    with pytest.raises(RuntimeError, match="compaction blocked"):
        compact_rate_history(db, apply=True, vacuum_into=compacted)
    assert not compacted.exists()
    assert len(_rows(db)) == 4


def test_apply_fails_closed_on_generic_observation_reference(tmp_path: Path) -> None:
    db = tmp_path / "rates.sqlite3"
    compacted = tmp_path / "rates-compacted.sqlite3"
    _build_db(db)
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "INSERT INTO manual_overrides(id, target_type, target_id) "
            "VALUES ('m1', 'rate_observation', 'o2')"
        )
        conn.commit()
    finally:
        conn.close()

    report = compact_rate_history(db)
    assert report["reference_blockers"][0]["kind"] == "generic_reference"

    with pytest.raises(RuntimeError, match="compaction blocked"):
        compact_rate_history(db, apply=True, vacuum_into=compacted)
    assert not compacted.exists()


def test_apply_requires_separate_vacuum_artifact(tmp_path: Path) -> None:
    db = tmp_path / "rates.sqlite3"
    _build_db(db)

    with pytest.raises(ValueError, match="requires --vacuum-into"):
        compact_rate_history(db, apply=True)
