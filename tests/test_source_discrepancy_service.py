from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from rate_monitor.services.source_discrepancy_service import (
    build_source_discrepancy_report,
    write_source_discrepancy_report,
)


def _db(tmp_path: Path) -> Path:
    db = tmp_path / "discrepancy.sqlite3"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE collection_runs (
          id TEXT PRIMARY KEY,
          source_id TEXT NOT NULL,
          started_at TEXT NOT NULL,
          finished_at TEXT,
          status TEXT NOT NULL
        );
        CREATE TABLE institutions (
          id TEXT PRIMARY KEY,
          canonical_name TEXT NOT NULL,
          sector TEXT NOT NULL
        );
        CREATE TABLE products (
          id TEXT PRIMARY KEY,
          institution_id TEXT NOT NULL,
          name TEXT NOT NULL,
          product_type TEXT NOT NULL
        );
        CREATE TABLE product_variants (
          id TEXT PRIMARY KEY,
          product_id TEXT NOT NULL,
          term_months INTEGER,
          join_channel TEXT,
          interest_method TEXT
        );
        CREATE TABLE raw_artifacts (
          id TEXT PRIMARY KEY,
          relative_path TEXT NOT NULL,
          sha256 TEXT NOT NULL
        );
        CREATE TABLE rate_observations (
          id TEXT PRIMARY KEY,
          variant_id TEXT NOT NULL,
          run_id TEXT NOT NULL,
          last_run_id TEXT NOT NULL,
          raw_artifact_id TEXT NOT NULL,
          base_rate TEXT,
          max_rate TEXT,
          source_effective_at TEXT,
          last_seen_at TEXT,
          base_source_locator TEXT NOT NULL,
          option_source_locator TEXT,
          source_record_hash TEXT NOT NULL,
          validation_status TEXT NOT NULL,
          valid_to TEXT
        );
        """
    )
    conn.executemany(
        "INSERT INTO collection_runs VALUES (?, ?, ?, ?, ?)",
        [
            ("fsb-old", "fsb", "2026-08-12T00:00:00", "2026-08-12T00:01:00", "success"),
            ("fsb-new", "fsb", "2026-08-13T00:00:00", "2026-08-13T00:01:00", "success"),
            ("fin-new", "finlife_savings_bank", "2026-08-13T00:10:00", "2026-08-13T00:11:00", "success"),
        ],
    )
    conn.executemany(
        "INSERT INTO institutions VALUES (?, ?, 'savings_bank')",
        [
            ("i-fsb", "대백"),
            ("i-fin", "대백저축은행"),
        ],
    )
    conn.executemany(
        "INSERT INTO products VALUES (?, ?, ?, 'term_deposit')",
        [
            ("p-fsb", "i-fsb", "애플 정기예금"),
            ("p-fin", "i-fin", "애플정기예금"),
            ("p-fsb-other", "i-fsb", "정기예금(창구)"),
            ("p-fin-other", "i-fin", "인터넷정기예금"),
        ],
    )
    conn.executemany(
        "INSERT INTO product_variants VALUES (?, ?, 12, ?, ?)",
        [
            ("v-fsb", "p-fsb", "internet", "simple"),
            ("v-fin", "p-fin", "internet", "simple"),
            ("v-fsb-other", "p-fsb-other", "branch", "simple"),
            ("v-fin-other", "p-fin-other", "internet", "simple"),
        ],
    )
    conn.executemany(
        "INSERT INTO raw_artifacts VALUES (?, ?, ?)",
        [
            ("raw-fsb", "raw/fsb/apple.json", "a" * 64),
            ("raw-fin", "raw/fin/apple.json", "b" * 64),
            ("raw-fsb-other", "raw/fsb/other.json", "c" * 64),
            ("raw-fin-other", "raw/fin/other.json", "d" * 64),
        ],
    )
    conn.executemany(
        """
        INSERT INTO rate_observations
          (id, variant_id, run_id, last_run_id, raw_artifact_id,
           base_rate, max_rate, source_effective_at, last_seen_at,
           base_source_locator, option_source_locator, source_record_hash,
           validation_status, valid_to)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'valid', NULL)
        """,
        [
            (
                "o-fsb",
                "v-fsb",
                "fsb-old",
                "fsb-new",
                "raw-fsb",
                "4.10",
                "4.10",
                "2026-08-12",
                "2026-08-13T00:01:00",
                "fsb:apple",
                "fsb:apple:12m",
                "hash-fsb",
            ),
            (
                "o-fin",
                "v-fin",
                "fin-new",
                "fin-new",
                "raw-fin",
                "3.80",
                "3.80",
                "2026-08-13",
                "2026-08-13T00:11:00",
                "fin:apple",
                "fin:apple:12m",
                "hash-fin",
            ),
            (
                "o-fsb-other",
                "v-fsb-other",
                "fsb-new",
                "fsb-new",
                "raw-fsb-other",
                "3.70",
                "3.70",
                "2026-08-13",
                "2026-08-13T00:01:00",
                "fsb:other",
                None,
                "hash-fsb-other",
            ),
            (
                "o-fin-other",
                "v-fin-other",
                "fin-new",
                "fin-new",
                "raw-fin-other",
                "3.70",
                "3.70",
                "2026-08-13",
                "2026-08-13T00:11:00",
                "fin:other",
                None,
                "hash-fin-other",
            ),
        ],
    )
    conn.commit()
    conn.close()
    return db


def test_exact_product_match_surfaces_rate_mismatch_with_provenance(tmp_path: Path) -> None:
    report = build_source_discrepancy_report(_db(tmp_path))

    assert report["scope"]["canonical_mutated"] is False
    assert report["summary"]["exact_matches"] == 1
    assert report["summary"]["rate_mismatch_date_diff"] == 1
    assert report["summary"]["mismatch_or_incomplete"] == 1

    match = report["matches"][0]
    assert match["status"] == "rate_mismatch_date_diff"
    assert match["delta_max_rate_primary_minus_secondary"] == "0.30"
    assert match["primary"]["max_rate"] == "4.10"
    assert match["secondary"]["max_rate"] == "3.80"
    assert match["primary"]["raw_artifact_path"] == "raw/fsb/apple.json"
    assert match["primary"]["raw_artifact_sha256"] == "a" * 64
    assert match["primary"]["base_source_locator"] == "fsb:apple"
    assert match["secondary"]["option_source_locator"] == "fin:apple:12m"


def test_different_product_names_are_not_guessed_as_same_product(tmp_path: Path) -> None:
    report = build_source_discrepancy_report(_db(tmp_path))

    uncertain = [item for item in report["source_only"] if item["status"] == "unmatched_product"]
    assert len(uncertain) == 2
    assert report["summary"]["unmatched_product"] == 2
    assert {item["side"] for item in uncertain} == {"primary", "secondary"}
    assert any("인터넷정기예금" in item["candidate_products"] for item in uncertain)
    assert any("정기예금(창구)" in item["candidate_products"] for item in uncertain)


def test_official_bank_evidence_is_compared_without_mutating_db(tmp_path: Path) -> None:
    db = _db(tmp_path)
    evidence = tmp_path / "official.json"
    evidence.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "institution": "대백저축은행",
                        "product": "애플정기예금",
                        "product_type": "term_deposit",
                        "term_months": 12,
                        "base_rate": "3.80",
                        "max_rate": "3.80",
                        "effective_at": "2026-08-13",
                        "captured_at": "2026-08-13T14:00:00+09:00",
                        "url": "https://example.invalid/debec/apple",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    out = tmp_path / "report.json"
    report = write_source_discrepancy_report(db, out, official_evidence_path=evidence)

    comparison = report["official_evidence"][0]
    assert comparison["sources"]["primary"]["rate_agrees"] is False
    assert comparison["sources"]["primary"]["delta_vs_official"] == "0.30"
    assert comparison["sources"]["secondary"]["rate_agrees"] is True
    assert comparison["official"]["url"] == "https://example.invalid/debec/apple"
    assert out.exists()

    conn = sqlite3.connect(db)
    try:
        assert conn.execute("SELECT COUNT(*) FROM rate_observations").fetchone()[0] == 4
    finally:
        conn.close()
