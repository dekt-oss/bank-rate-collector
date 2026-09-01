from __future__ import annotations

import sqlite3
from pathlib import Path

from scripts import savings_bank_identity_census as census


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
    observations = [
        ("0010000", "매핑저축은행", "C0", "i-mapped", "mapped_exact_fss_code"),
        ("0010001", "코드저축은행", "C1", None, "unmapped_no_exact_cross_source_code"),
        ("0010002", "법인저축은행", "C2", None, "unmapped_no_exact_cross_source_code"),
        ("0010003", "이름저축은행", "C3", None, "unmapped_no_exact_cross_source_code"),
        ("0010004", "기존저축은행", "C4", None, "unmapped_no_exact_cross_source_code"),
    ]
    conn.executemany(
        """
        INSERT INTO institution_funding_observations(
            source_id, sector, source_institution_key, source_institution_name,
            source_crno, institution_id, identity_status, source_effective_month, valid_to
        ) VALUES (?, ?, ?, ?, ?, ?, ?, '2026-06', NULL)
        """,
        [
            (census.SOURCE_ID, census.SECTOR, key, name, crno, institution_id, status)
            for key, name, crno, institution_id, status in observations
        ],
    )
    links = [
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
            "{}",
            "exact_name",
        ),
        (
            census.SOURCE_ID,
            "savings_bank:0010004",
            "i-stale",
            "기존저축은행",
            '{"crno":"C4"}',
            "exact_fss_code_and_name",
        ),
    ]
    conn.executemany(
        """
        INSERT INTO source_entity_links(
            source_id, entity_type, source_entity_key, entity_id, source_name,
            source_payload_json, match_method, confidence, valid_to
        ) VALUES (?, 'institution', ?, ?, ?, ?, ?, 1.0, NULL)
        """,
        links,
    )
    conn.commit()
    conn.close()


def test_census_separates_exact_evidence_from_name_hints(tmp_path: Path) -> None:
    db_path = tmp_path / "census.sqlite3"
    _database(db_path)

    result = census.build_census(db_path)

    assert result["latest_source_effective_month"] == "2026-06"
    assert result["source_population"] == 5
    assert result["observation_mapped_count"] == 1
    assert result["observation_unmapped_count"] == 4
    assert result["write_back_performed"] is False
    assert result["classification_counts"] == {
        "candidate_exact_crno_unique": 1,
        "candidate_exact_cross_source_code_and_name": 1,
        "stale_observation_link_present": 1,
        "unresolved_name_only_hint": 1,
    }

    rows = {row["source_fncoCd"]: row for row in result["rows"]}
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

    census.build_census(db_path)

    after = sqlite3.connect(db_path)
    after_counts = (
        after.execute("SELECT COUNT(*) FROM source_entity_links").fetchone()[0],
        after.execute("SELECT COUNT(*) FROM institution_funding_observations").fetchone()[0],
    )
    after.close()
    assert after_counts == before_counts


def test_markdown_never_calls_candidates_automatic_mappings(tmp_path: Path) -> None:
    db_path = tmp_path / "census.sqlite3"
    _database(db_path)

    text = census.render_markdown(census.build_census(db_path))

    assert "remediation candidates" in text
    assert "not automatic writes" in text
    assert "unresolved_name_only_hint" in text
    assert "write_back_performed: false" in text


def test_copycheck_targets_expected_remediation_branch() -> None:
    assert census.FEATURE_BRANCH == "fix/savings-bank-funding-identity-13-20260901"
