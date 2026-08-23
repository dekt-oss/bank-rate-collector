from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from rate_monitor.services.official_evidence_policy import annotate_official_evidence_policy
from rate_monitor.services.source_discrepancy_service import build_source_discrepancy_report


def _db(
    tmp_path: Path,
    *,
    primary_channel: str = "branch",
    secondary_channel: str = "branch",
    include_second_variant: bool = False,
) -> Path:
    db = tmp_path / "variant-discrepancy.sqlite3"
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
            ("fsb-run", "fsb", "2026-08-23T00:00:00", "2026-08-23T00:01:00", "success"),
            (
                "fin-run",
                "finlife_savings_bank",
                "2026-08-23T00:10:00",
                "2026-08-23T00:11:00",
                "success",
            ),
        ],
    )
    conn.executemany(
        "INSERT INTO institutions VALUES (?, ?, 'savings_bank')",
        [("i-fsb", "테스트"), ("i-fin", "테스트저축은행")],
    )
    conn.executemany(
        "INSERT INTO products VALUES (?, ?, '테스트예금', 'term_deposit')",
        [("p-fsb", "i-fsb"), ("p-fin", "i-fin")],
    )

    variants = [
        ("v-fsb-1", "p-fsb", 12, primary_channel, "simple"),
        ("v-fin-1", "p-fin", 12, secondary_channel, "simple"),
    ]
    observations = [
        (
            "o-fsb-1",
            "v-fsb-1",
            "fsb-run",
            "fsb-run",
            "raw-fsb-1",
            "4.10",
            "4.10",
            "2026-08-22",
            "2026-08-23T00:01:00",
            "fsb:test:1",
            None,
            "hash-fsb-1",
        ),
        (
            "o-fin-1",
            "v-fin-1",
            "fin-run",
            "fin-run",
            "raw-fin-1",
            "4.10",
            "4.10",
            "2026-08-22",
            "2026-08-23T00:11:00",
            "fin:test:1",
            None,
            "hash-fin-1",
        ),
    ]
    artifacts = [
        ("raw-fsb-1", "raw/fsb/1.json", "a" * 64),
        ("raw-fin-1", "raw/fin/1.json", "b" * 64),
    ]

    if include_second_variant:
        variants.extend(
            [
                ("v-fsb-2", "p-fsb", 12, "internet", "compound"),
                ("v-fin-2", "p-fin", 12, "internet", "compound"),
            ]
        )
        observations.extend(
            [
                (
                    "o-fsb-2",
                    "v-fsb-2",
                    "fsb-run",
                    "fsb-run",
                    "raw-fsb-2",
                    "4.00",
                    "4.00",
                    "2026-08-22",
                    "2026-08-23T00:01:00",
                    "fsb:test:2",
                    None,
                    "hash-fsb-2",
                ),
                (
                    "o-fin-2",
                    "v-fin-2",
                    "fin-run",
                    "fin-run",
                    "raw-fin-2",
                    "4.00",
                    "4.00",
                    "2026-08-22",
                    "2026-08-23T00:11:00",
                    "fin:test:2",
                    None,
                    "hash-fin-2",
                ),
            ]
        )
        artifacts.extend(
            [
                ("raw-fsb-2", "raw/fsb/2.json", "c" * 64),
                ("raw-fin-2", "raw/fin/2.json", "d" * 64),
            ]
        )

    conn.executemany("INSERT INTO product_variants VALUES (?, ?, ?, ?, ?)", variants)
    conn.executemany("INSERT INTO raw_artifacts VALUES (?, ?, ?)", artifacts)
    conn.executemany(
        """
        INSERT INTO rate_observations
          (id, variant_id, run_id, last_run_id, raw_artifact_id,
           base_rate, max_rate, source_effective_at, last_seen_at,
           base_source_locator, option_source_locator, source_record_hash,
           validation_status, valid_to)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'valid', NULL)
        """,
        observations,
    )
    conn.commit()
    conn.close()
    return db


def test_source_matching_preserves_channel_and_interest_method_variants(tmp_path: Path) -> None:
    report = build_source_discrepancy_report(_db(tmp_path, include_second_variant=True))

    assert report["summary"]["exact_matches"] == 2
    keys = {
        (item["match"]["join_channel"], item["match"]["interest_method"])
        for item in report["matches"]
    }
    assert keys == {("branch", "simple"), ("internet", "compound")}
    assert report["scope"]["canonical_mutated"] is False
    assert "+ join_channel + interest_method" in report["scope"]["automatic_match_method"]


def test_different_channels_are_not_collapsed_into_one_product_match(tmp_path: Path) -> None:
    report = build_source_discrepancy_report(
        _db(tmp_path, primary_channel="branch", secondary_channel="internet")
    )

    assert report["summary"]["exact_matches"] == 0
    assert report["summary"]["unmatched_variant"] == 2
    assert {item["record"]["join_channel"] for item in report["source_only"]} == {
        "branch",
        "internet",
    }


def test_source_provenance_exposes_observational_freshness_metadata(tmp_path: Path) -> None:
    report = build_source_discrepancy_report(_db(tmp_path))
    freshness = report["matches"][0]["primary"]["freshness"]

    assert freshness["source_effective_at"] == "2026-08-22"
    assert freshness["last_seen_at"] == "2026-08-23T00:01:00"
    assert freshness["effective_age_days"] is not None
    assert freshness["last_seen_age_days"] is not None
    assert report["scope"]["freshness_metadata_policy"].startswith("observational_only")


def test_official_variant_can_use_only_unique_non_conflicting_wildcard(tmp_path: Path) -> None:
    db = _db(tmp_path, primary_channel="any", secondary_channel="any")
    evidence = tmp_path / "official.json"
    evidence.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "evidence_id": "official-1",
                        "evidence_group": "test:internet:simple:12m",
                        "evidence_kind": "product_disclosure",
                        "evidence_surface": "bank_direct_product_disclosure",
                        "institution": "테스트저축은행",
                        "product": "테스트예금",
                        "product_type": "term_deposit",
                        "term_months": 12,
                        "join_channel": "internet",
                        "interest_method": "simple",
                        "base_rate": "4.10",
                        "max_rate": "4.10",
                        "captured_at": "2026-08-23T16:01:00+09:00",
                        "url": "https://example.invalid/product",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = build_source_discrepancy_report(db, official_evidence_path=evidence)
    item = report["official_evidence"][0]

    assert item["sources"]["primary"]["variant_match"]["mode"] == "unambiguous_wildcard"
    assert item["sources"]["secondary"]["variant_match"]["mode"] == "unambiguous_wildcard"
    assert item["sources"]["primary"]["max_rate_comparison"]["status"] == "agree"


def test_official_policy_preserves_surface_variant_and_freshness(tmp_path: Path) -> None:
    db = _db(tmp_path, primary_channel="any", secondary_channel="any")
    evidence = tmp_path / "official.json"
    evidence.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "evidence_id": "official-1",
                        "evidence_group": "test:any:simple:12m",
                        "evidence_kind": "rate_change_notice",
                        "evidence_surface": "bank_direct_rate_change_notice",
                        "institution": "테스트저축은행",
                        "product": "테스트예금",
                        "product_type": "term_deposit",
                        "term_months": 12,
                        "join_channel": "any",
                        "interest_method": "simple",
                        "base_rate": "4.10",
                        "max_rate": "4.10",
                        "effective_at": "2026-08-22",
                        "captured_at": "2026-08-23T16:01:00+09:00",
                        "url": "https://example.invalid/notice",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = annotate_official_evidence_policy(
        build_source_discrepancy_report(db, official_evidence_path=evidence)
    )
    group = report["official_evidence_groups"][0]
    record = group["records"][0]

    assert group["join_channel"] == "any"
    assert group["interest_method"] == "simple"
    assert record["evidence_surface"] == "bank_direct_rate_change_notice"
    assert record["freshness"]["captured_age_days"] is not None
    assert record["freshness"]["effective_age_days"] is not None
    assert report["scope"]["official_freshness_metadata_policy"] == "observational_only"
