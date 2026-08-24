from __future__ import annotations

import sqlite3
from pathlib import Path

from rate_monitor.services.source_discrepancy_ambiguity_census import (
    annotate_payment_method_ambiguity_census,
)


def _db(tmp_path: Path) -> Path:
    path = tmp_path / "census.sqlite3"
    conn = sqlite3.connect(path)
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
        [("p-run", "fsb"), ("s-run", "finlife_savings_bank")],
    )
    conn.execute(
        "INSERT INTO institutions VALUES ('i', '테스트저축은행', 'savings_bank')"
    )
    conn.execute(
        "INSERT INTO products VALUES ('p', 'i', '정기적금', 'installment_savings')"
    )
    conn.execute(
        "INSERT INTO product_variants VALUES "
        "('v', 'p', 12, 'branch', 'compound', NULL)"
    )
    conn.execute(
        "INSERT INTO rate_observations VALUES "
        "('o', 'v', 'p-run', '3.00', '3.00', '2026-08-20', 'valid', NULL)"
    )
    conn.commit()
    conn.close()
    return path


def _ambiguity(*, counterpart: bool, interest_method: str = "simple") -> dict[str, object]:
    item: dict[str, object] = {
        "status": "ambiguous_variant_dimension",
        "dimension": "payment_method",
        "side": "secondary",
        "institution": "테스트저축은행",
        "product": "정기적금",
        "product_type": "installment_savings",
        "term_months": 12,
        "join_channel": "branch",
        "interest_method": interest_method,
        "candidate_payment_methods": ["f", "s"],
        "candidate_variants": [
            {
                "payment_method": "S",
                "base_rate": "3.00",
                "max_rate": "3.00",
                "source_effective_at": "2026-08-20",
            },
            {
                "payment_method": "F",
                "base_rate": "4.00",
                "max_rate": "4.00",
                "source_effective_at": "2026-08-20",
            },
        ],
        "counterpart_side": "primary",
    }
    item["counterpart"] = (
        {
            "source_id": "fsb",
            "max_rate": "3.00",
            "payment_method": None,
        }
        if counterpart
        else None
    )
    return item


def _report() -> dict[str, object]:
    return {
        "scope": {
            "primary_source": "fsb",
            "secondary_source": "finlife_savings_bank",
            "canonical_mutated": False,
        },
        "source_runs": {
            "fsb": {"id": "p-run", "source_id": "fsb"},
            "finlife_savings_bank": {
                "id": "s-run",
                "source_id": "finlife_savings_bank",
            },
        },
        "summary": {},
        "triage": {
            "summary": {"queue_size": 2, "P0": 0, "P1": 1, "P2": 0, "P3": 1}
        },
        "dimension_ambiguities": [
            _ambiguity(counterpart=True),
            _ambiguity(counterpart=False),
        ],
    }


def test_census_exposes_blocked_delta_and_queue_masking(tmp_path: Path) -> None:
    report = annotate_payment_method_ambiguity_census(_report(), db_path=_db(tmp_path))

    census = report["ambiguity_census"]
    summary = census["summary"]
    assert summary["ambiguity_blocked_count"] == 2
    assert summary["candidate_count_distribution"] == {"2": 2}
    assert summary["payment_method_combinations"] == {"f+s": 2}
    assert summary["product_types"] == {"installment_savings": 2}
    assert summary["counterpart_coverage"] == {"missing": 1, "present": 1}
    assert summary["blocked_risk_bands"] == {"ge_1.00pp": 1, "unknown": 1}

    masking = census["queue_masking_indicator"]
    assert masking["comparable_mismatch_count"] == 2
    assert masking["ambiguity_blocked_count"] == 2
    assert masking["blocked_ge_0_20pp_count"] == 1
    assert masking["p0_count"] == 0

    with_counterpart = next(
        item for item in census["items"] if item["blocked_delta"]["counterpart_present"]
    )
    assert with_counterpart["blocked_delta"]["max_absolute_delta"] == "1.00"
    assert with_counterpart["blocked_delta"]["blocked_risk_band"] == "ge_1.00pp"

    assert report["scope"]["ambiguity_census_mutates_canonical"] is False
    assert report["scope"]["ambiguity_census_selects_authority"] is False
    assert report["scope"]["ambiguity_census_promotes_7d_identity"] is False


def test_missing_counterpart_gets_structural_reason_from_latest_rows(tmp_path: Path) -> None:
    report = annotate_payment_method_ambiguity_census(_report(), db_path=_db(tmp_path))

    missing = next(
        item for item in report["ambiguity_census"]["items"]
        if not item["blocked_delta"]["counterpart_present"]
    )
    analysis = missing["counterpart_absence_analysis"]

    assert analysis["category"] == "same_product_term_variant_mismatch"
    assert analysis["counterpart_source_id"] == "fsb"
    assert analysis["same_product_term_count"] == 1
    assert analysis["exact_6d_row_count"] == 0
    assert analysis["candidate_variants"][0]["interest_method"] == "compound"
