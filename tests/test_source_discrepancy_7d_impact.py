from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from scripts.source_discrepancy_7d_impact import build_impact


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    db = tmp_path / "impact.sqlite3"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE collection_runs (id TEXT PRIMARY KEY, source_id TEXT);
        CREATE TABLE institutions (id TEXT PRIMARY KEY, canonical_name TEXT, sector TEXT);
        CREATE TABLE products (
          id TEXT PRIMARY KEY, institution_id TEXT, name TEXT, product_type TEXT
        );
        CREATE TABLE product_variants (
          id TEXT PRIMARY KEY, product_id TEXT, term_months INTEGER,
          join_channel TEXT, interest_method TEXT, payment_method TEXT
        );
        CREATE TABLE rate_observations (
          id TEXT PRIMARY KEY, variant_id TEXT, last_run_id TEXT,
          base_rate TEXT, max_rate TEXT, source_effective_at TEXT,
          validation_status TEXT, valid_to TEXT
        );
        """
    )
    conn.executemany(
        "INSERT INTO collection_runs VALUES (?, ?)",
        [("p", "fsb"), ("s", "finlife_savings_bank")],
    )
    conn.execute(
        "INSERT INTO institutions VALUES ('i', '테스트저축은행', 'savings_bank')"
    )
    conn.executemany(
        "INSERT INTO products VALUES (?, 'i', ?, ?)",
        [
            ("pd", "정기예금", "term_deposit"),
            ("ps", "정기적금", "installment_savings"),
        ],
    )
    conn.executemany(
        "INSERT INTO product_variants VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("p-dep", "pd", 12, "branch", "simple", None),
            ("s-dep", "pd", 12, "branch", "simple", None),
            ("p-sav", "ps", 12, "branch", "simple", None),
            ("s-sav-s", "ps", 12, "branch", "simple", "S"),
            ("s-sav-f", "ps", 12, "branch", "simple", "F"),
        ],
    )
    conn.executemany(
        "INSERT INTO rate_observations VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("o1", "p-dep", "p", "3.0", "3.0", "2026-08-20", "valid", None),
            ("o2", "s-dep", "s", "3.0", "3.0", "2026-08-20", "valid", None),
            ("o3", "p-sav", "p", "3.0", "3.0", "2026-08-20", "valid", None),
            ("o4", "s-sav-s", "s", "3.0", "3.0", "2026-08-20", "valid", None),
            ("o5", "s-sav-f", "s", "4.0", "4.0", "2026-08-20", "valid", None),
        ],
    )
    conn.commit()
    conn.close()

    report = {
        "scope": {
            "primary_source": "fsb",
            "secondary_source": "finlife_savings_bank",
        },
        "source_runs": {
            "fsb": {"id": "p", "source_id": "fsb"},
            "finlife_savings_bank": {"id": "s", "source_id": "finlife_savings_bank"},
        },
        "matches": [
            {
                "status": "agree",
                "match": {"product_type": "term_deposit"},
            }
        ],
        "dimension_ambiguities": [
            {
                "dimension": "payment_method",
                "institution": "테스트저축은행",
                "product": "정기적금",
                "term_months": 12,
                "join_channel": "branch",
                "interest_method": "simple",
                "counterpart": {"payment_method": None},
                "candidate_variants": [
                    {"payment_method": "S", "max_rate": "3.0"},
                    {"payment_method": "F", "max_rate": "4.0"},
                ],
            }
        ],
    }
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    return db, report_path


def test_strict_7d_keeps_deposit_but_drops_unknown_vs_f_s_savings(tmp_path: Path) -> None:
    db, report = _fixture(tmp_path)

    impact = build_impact(db, report)

    assert impact["scope"]["strict_7d_implemented"] is False
    assert impact["scope"]["identity_changed"] is False
    assert impact["scope"]["duplicate_7d_fail_closed"] is True
    assert impact["current_6d"]["total_comparable"] == 1
    assert impact["strict_7d_simulation"]["total_comparable"] == 1
    assert impact["strict_7d_simulation"]["comparable_by_product_type"] == {
        "term_deposit": 1
    }
    assert impact["strict_7d_simulation"]["source_only_key_count_by_product_type"] == {
        "installment_savings": 3
    }

    coverage = impact["payment_method_coverage"]
    fsb_savings = coverage["fsb"]["installment_savings"]
    finlife_savings = coverage["finlife_savings_bank"]["installment_savings"]
    assert fsb_savings["known_payment_method_rows"] == 0
    assert fsb_savings["unknown_payment_method_key6"] == 1
    assert finlife_savings["known_payment_method_rows"] == 2
    assert finlife_savings["known_payment_method_key6"] == 1

    transition = impact["ambiguity_transition"]["counts"]
    assert transition == {"strict7d_turns_into_payment_source_only": 1}


def test_same_7d_conflicting_rates_remains_fail_closed(tmp_path: Path) -> None:
    db, report = _fixture(tmp_path)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO rate_observations VALUES "
        "('o6', 's-dep', 's', '3.5', '3.5', '2026-08-20', 'valid', NULL)"
    )
    conn.commit()
    conn.close()

    impact = build_impact(db, report)

    strict = impact["strict_7d_simulation"]
    assert strict["total_comparable"] == 0
    assert strict["total_structural_duplicate_secondary"] == 1
    assert strict["total_conflicting_duplicate_secondary"] == 1
    example = strict["same_7d_duplicate_examples"][0]
    assert example["key7"][-1] == "unknown"
    assert example["secondary"]["structural_duplicate"] is True
    assert example["secondary"]["conflicting_rates"] is True


def test_same_7d_same_rate_duplicate_is_still_fail_closed(tmp_path: Path) -> None:
    db, report = _fixture(tmp_path)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO rate_observations VALUES "
        "('o6', 's-dep', 's', '3.0', '3.0', '2026-08-20', 'valid', NULL)"
    )
    conn.commit()
    conn.close()

    impact = build_impact(db, report)

    strict = impact["strict_7d_simulation"]
    assert strict["total_comparable"] == 0
    assert strict["total_structural_duplicate_secondary"] == 1
    assert strict["total_conflicting_duplicate_secondary"] == 0
    assert strict["total_same_rate_duplicate_secondary"] == 1
    example = strict["same_7d_duplicate_examples"][0]
    assert example["secondary"]["candidate_count"] == 2
    assert example["secondary"]["duplicate_same_rate"] is True
