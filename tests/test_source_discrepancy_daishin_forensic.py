from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from scripts.source_discrepancy_daishin_forensic import _extract_locator, build_report


def _write_raw(path: Path, payload: dict[str, object]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    path.write_bytes(encoded)
    return hashlib.sha256(encoded).hexdigest()


def _db(tmp_path: Path) -> tuple[Path, Path]:
    db = tmp_path / "forensic.sqlite3"
    raw_root = tmp_path / "data" / "raw"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE collection_runs (
          id TEXT PRIMARY KEY,
          source_id TEXT NOT NULL,
          started_at TEXT NOT NULL,
          finished_at TEXT,
          status TEXT NOT NULL,
          raw_count INTEGER NOT NULL,
          parsed_count INTEGER NOT NULL,
          valid_count INTEGER NOT NULL,
          warning_count INTEGER NOT NULL,
          error_count INTEGER NOT NULL
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
          interest_method TEXT,
          payment_method TEXT
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
          base_source_locator TEXT,
          option_source_locator TEXT,
          source_record_hash TEXT,
          validation_status TEXT NOT NULL,
          valid_to TEXT
        );
        CREATE TABLE source_entity_links (
          id TEXT PRIMARY KEY,
          source_id TEXT NOT NULL,
          entity_type TEXT NOT NULL,
          source_entity_key TEXT NOT NULL,
          entity_id TEXT NOT NULL,
          source_name TEXT,
          valid_to TEXT
        );
        """
    )
    conn.executemany(
        "INSERT INTO collection_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("fsb-run", "fsb", "2026-08-24T00:00:00", None, "success", 1, 1, 1, 0, 0),
            (
                "fin-run",
                "finlife_savings_bank",
                "2026-08-24T00:01:00",
                None,
                "success",
                1,
                1,
                1,
                0,
                0,
            ),
        ],
    )
    conn.execute(
        "INSERT INTO institutions VALUES ('inst', '대신저축은행', 'savings_bank')"
    )
    conn.executemany(
        "INSERT INTO products VALUES (?, 'inst', '정기적금', 'installment_savings')",
        [("p-fsb",), ("p-fin-simple",), ("p-fin-compound",)],
    )
    conn.executemany(
        "INSERT INTO product_variants VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("v-fsb", "p-fsb", 24, "any", "simple", None),
            ("v-fin-simple", "p-fin-simple", 24, "any", "simple", "S"),
            ("v-fin-compound", "p-fin-compound", 24, "any", "compound", "S"),
        ],
    )

    fin_payload = {
        "result": {
            "baseList": [
                {
                    "fin_co_no": "0010001",
                    "fin_prdt_cd": "CODE-SIMPLE",
                    "kor_co_nm": "대신저축은행",
                    "fin_prdt_nm": "정기적금",
                },
                {
                    "fin_co_no": "0010001",
                    "fin_prdt_cd": "CODE-COMPOUND",
                    "kor_co_nm": "대신저축은행",
                    "fin_prdt_nm": "정기적금",
                },
            ],
            "optionList": [
                {
                    "fin_co_no": "0010001",
                    "fin_prdt_cd": "CODE-SIMPLE",
                    "save_trm": "24",
                    "intr_rate_type": "S",
                    "intr_rate": 4.0,
                    "intr_rate2": 4.0,
                    "rsrv_type": "S",
                },
                {
                    "fin_co_no": "0010001",
                    "fin_prdt_cd": "CODE-COMPOUND",
                    "save_trm": "24",
                    "intr_rate_type": "M",
                    "intr_rate": 3.0,
                    "intr_rate2": 3.0,
                    "rsrv_type": "S",
                },
            ],
        }
    }
    fsb_payload = {"REC": [{"JUNG_24M_DAN": 3.0}]}
    fin_path = raw_root / "fin.json"
    fsb_path = raw_root / "fsb.json"
    fin_sha = _write_raw(fin_path, fin_payload)
    fsb_sha = _write_raw(fsb_path, fsb_payload)
    conn.executemany(
        "INSERT INTO raw_artifacts VALUES (?, ?, ?)",
        [
            ("raw-fsb", str(fsb_path), fsb_sha),
            ("raw-fin", str(fin_path), fin_sha),
        ],
    )
    conn.executemany(
        "INSERT INTO rate_observations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                "o-fsb",
                "v-fsb",
                "fsb-run",
                "fsb-run",
                "raw-fsb",
                "3.00",
                "3.00",
                "2025-11-03",
                "2026-08-24T00:00:00",
                "$.REC[0].JUNG_24M_DAN",
                None,
                "hash-fsb",
                "valid",
                None,
            ),
            (
                "o-fin-simple",
                "v-fin-simple",
                "fin-run",
                "fin-run",
                "raw-fin",
                "4.00",
                "4.00",
                "2026-08-20",
                "2026-08-24T00:01:00",
                "$.result.baseList[0]",
                "$.result.optionList[0]",
                "hash-fin-simple",
                "valid",
                None,
            ),
            (
                "o-fin-compound",
                "v-fin-compound",
                "fin-run",
                "fin-run",
                "raw-fin",
                "3.00",
                "3.00",
                "2026-08-20",
                "2026-08-24T00:01:00",
                "$.result.baseList[1]",
                "$.result.optionList[1]",
                "hash-fin-compound",
                "valid",
                None,
            ),
        ],
    )
    conn.executemany(
        "INSERT INTO source_entity_links VALUES (?, ?, 'product', ?, ?, ?, NULL)",
        [
            ("l-fsb", "fsb", "inst:fsb-product", "p-fsb", "정기적금"),
            (
                "l-fin-simple",
                "finlife_savings_bank",
                "inst:savingProductsSearch:CODE-SIMPLE",
                "p-fin-simple",
                "정기적금",
            ),
            (
                "l-fin-compound",
                "finlife_savings_bank",
                "inst:savingProductsSearch:CODE-COMPOUND",
                "p-fin-compound",
                "정기적금",
            ),
        ],
    )
    conn.commit()
    conn.close()
    return db, raw_root


def test_locator_reads_nested_objects_and_scalar() -> None:
    payload = {"result": {"baseList": [{"code": "A"}]}, "REC": [{"RATE": 3.0}]}

    assert _extract_locator(payload, "$.result.baseList[0]") == {"code": "A"}
    assert _extract_locator(payload, "$.REC[0].RATE") == 3.0
    assert _extract_locator(payload, "$.result.baseList[99]") is None


def test_report_exposes_finlife_source_product_identity_and_raw_provenance(
    tmp_path: Path,
) -> None:
    db, raw_root = _db(tmp_path)

    report = build_report(db, raw_root)

    assert report["scope"]["production_state_mutated"] is False
    assert report["scope"]["authority_selected"] is False
    assert report["summary"]["finlife_source_product_keys"] == [
        "inst:savingProductsSearch:CODE-COMPOUND",
        "inst:savingProductsSearch:CODE-SIMPLE",
    ]
    assert report["summary"]["simple_and_compound_use_same_source_product_key"] is False

    simple = next(
        row
        for row in report["rows"]
        if row["source_id"] == "finlife_savings_bank"
        and row["interest_method"] == "simple"
    )
    compound = next(
        row
        for row in report["rows"]
        if row["source_id"] == "finlife_savings_bank"
        and row["interest_method"] == "compound"
    )

    assert simple["raw"]["sha256_matches_db"] is True
    assert simple["raw"]["base_locator_value"]["fin_prdt_cd"] == "CODE-SIMPLE"
    assert simple["raw"]["option_locator_value"]["intr_rate"] == 4.0
    assert compound["raw"]["base_locator_value"]["fin_prdt_cd"] == "CODE-COMPOUND"
    assert compound["raw"]["option_locator_value"]["intr_rate"] == 3.0
