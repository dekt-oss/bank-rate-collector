from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "savings_bank_identity_census.py"
SPEC = importlib.util.spec_from_file_location("savings_bank_identity_census", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _database(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE institutions (
            id TEXT PRIMARY KEY,
            sector TEXT,
            canonical_name TEXT
        );
        CREATE TABLE source_entity_links (
            source_id TEXT,
            entity_type TEXT,
            source_entity_key TEXT,
            entity_id TEXT,
            source_name TEXT,
            source_payload_json TEXT,
            match_method TEXT,
            confidence REAL,
            valid_to TEXT
        );
        CREATE TABLE institution_funding_observations (
            source_id TEXT,
            sector TEXT,
            source_institution_key TEXT,
            source_institution_name TEXT,
            source_crno TEXT,
            institution_id TEXT,
            identity_status TEXT,
            source_effective_month TEXT,
            valid_to TEXT
        );
        """
    )
    conn.executemany(
        "INSERT INTO institutions(id, sector, canonical_name) VALUES (?, ?, ?)",
        [
            ("i-mapped", "savings_bank", "매핑저축은행"),
            ("i-code", "savings_bank", "코드저축은행"),
            ("i-crno", "savings_bank", "법인저축은행"),
            ("i-name", "savings_bank", "이름저축은행"),
            ("i-stale", "savings_bank", "기존저축은행"),
        ],
    )
    conn.executemany(
        """
        INSERT INTO institution_funding_observations(
            source_id, sector, source_institution_key, source_institution_name,
            source_crno, institution_id, identity_status, source_effective_month, valid_to
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
        """,
        [
            (
                MODULE.SOURCE_ID,
                MODULE.SECTOR,
                "0010000",
                "매핑저축은행",
                "C0",
                "i-mapped",
                "mapped_exact_fss_code",
                "2026-06",
            ),
            (
                MODULE.SOURCE_ID,
                MODULE.SECTOR,
                "0010001",
                "코드저축은행",
                "C1",
                None,
                "unmapped_no_exact_cross_source_code",
                "2026-06",
            ),
            (
                MODULE.SOURCE_ID,
                MODULE.SECTOR,
                "0010002",
                "법인저축은행",
                "C2",
                None,
                "unmapped_no_exact_cross_source_code",
                "2026-06",
            ),
            (
                MODULE.SOURCE_ID,
                MODULE.SECTOR,
                "0010003",
                "이름저축은행",
                "C3",
                None,
                "unmapped_no_exact_cross_source_code",
                "2026-06",
            ),
            (
                MODULE.SOURCE_ID,
                MODULE.SECTOR,
                "0010004",
                "기존저축은행",
                "C4",
                None,
                "unmapped_no_exact_cross_source_code",
                "2026-06",
            ),
        ],
    )
    conn.executemany(
        """
        INSERT INTO source_entity_links(
            source_id, entity_type, source_entity_key, entity_id, source_name,
            source_payload_json, match_method, confidence, valid_to
        ) VALUES (?, 'institution', ?, ?, ?, ?, ?, 1.0, NULL)
        """,
        [
            (
                "fsb",
                "savings_bank:0010001",
                "i-code",
                "코드저축은행",
                '{"fncoCd":"0010001"}',
                "exact_fss_code",
            ),
            (
                "other",
                "savings_bank:DIFFERENT2",
                "i-crno",
                "법인저축은행",
                '{"crno":"C2"}',
                "exact_crno",
            ),
            (
                "other",
                "savings_bank:DIFFERENT3",
                "i-name",
                "이름저축은행",
                '{}',
                "exact_name",
            ),
            (
                MODULE.SOURCE_ID,
                "savings_bank:0010004",
                "i-stale",
                "기존저축은행",
                '{"crno":"C4"}',
                "exact_fss_code_and_name",
            ),
        ],
    )
    conn.commit()
    conn.close()


def test_census_separates_exact_identifier_evidence_from_name_only_hints(tmp_path: Path) -> None:
    db_path = tmp_path / "census.sqlite3"
    _database(db_path)

    census = MODULE.build_census(db_path)

    assert census["latest_source_effective_month"] == "2026-06"
    assert census["source_population"] == 5
    assert census["observation_mapped_count"] == 1
    assert census["observation_unmapped_count"] == 4
    assert census["write_back_performed"] is False
    assert census["classification_counts"] == {
        "candidate_exact_crno_unique": 1,
        "candidate_exact_cross_source_code_and_name": 1,
        "stale_observation_link_present": 1,
        "unresolved_name_only_hint": 1,
    }

    rows = {row["source_fncoCd"]: row for row in census["rows"]}
    assert rows["0010001"]["candidate_institution_id"] == "i-code"
    assert rows["0010002"]["candidate_institution_id"] == "i-crno"
    assert rows["0010003"]["candidate_institution_id"] is None
    assert rows["0010003"]["classification"] == "unresolved_name_only_hint"
    assert rows["0010004"]["candidate_institution_id"] == "i-stale"


def test_census_does_not_mutate_links_or_observations(tmp_path: Path) -> None:
    db_path = tmp_path / "census.sqlite3"
    _database(db_path)

    before = sqlite3.connect(db_path)
    before_counts = (
        before.execute("SELECT COUNT(*) FROM source_entity_links").fetchone()[0],
        before.execute("SELECT COUNT(*) FROM institution_funding_observations").fetchone()[0],
    )
    before.close()

    MODULE.build_census(db_path)

    after = sqlite3.connect(db_path)
    after_counts = (
        after.execute("SELECT COUNT(*) FROM source_entity_links").fetchone()[0],
        after.execute("SELECT COUNT(*) FROM institution_funding_observations").fetchone()[0],
    )
    after.close()
    assert after_counts == before_counts


def test_markdown_calls_candidates_candidates_not_automatic_mappings(tmp_path: Path) -> None:
    db_path = tmp_path / "census.sqlite3"
    _database(db_path)

    text = MODULE.render_markdown(MODULE.build_census(db_path))

    assert "remediation candidates" in text
    assert "not automatic writes" in text
    assert "unresolved_name_only_hint" in text
    assert "write_back_performed: false" in text
