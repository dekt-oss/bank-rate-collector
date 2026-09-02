import sqlite3
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from rate_monitor.services.fsb_availability_service import availability_match_key
from rate_monitor.services.relative_pricing_availability_resolver import (
    RESOLUTION_RESOLVED,
    RESOLUTION_UNRESOLVED,
    RelativePricingAvailabilityResolution,
)
from rate_monitor.services.relative_pricing_rate_candidates import (
    build_current_relative_pricing_rate_candidates,
)


def _create_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE institutions (
                id TEXT PRIMARY KEY,
                sector TEXT NOT NULL,
                active INTEGER NOT NULL
            );
            CREATE TABLE products (
                id TEXT PRIMARY KEY,
                institution_id TEXT NOT NULL,
                product_type TEXT NOT NULL,
                active INTEGER NOT NULL,
                is_special_sale INTEGER NOT NULL
            );
            CREATE TABLE product_variants (
                id TEXT PRIMARY KEY,
                product_id TEXT NOT NULL,
                term_months INTEGER,
                join_channel TEXT NOT NULL
            );
            CREATE TABLE collection_runs (
                id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL
            );
            CREATE TABLE rate_observations (
                id TEXT PRIMARY KEY,
                variant_id TEXT NOT NULL,
                run_id TEXT NOT NULL,
                max_rate REAL,
                source_effective_at TEXT,
                as_of TEXT,
                valid_to TEXT,
                validation_status TEXT NOT NULL
            );
            """
        )
        conn.commit()
    finally:
        conn.close()


def _resolution(
    *cohort: str,
    status: str = RESOLUTION_RESOLVED,
    match_key: str | None = None,
) -> RelativePricingAvailabilityResolution:
    key = match_key or availability_match_key("YN_Busan")
    return RelativePricingAvailabilityResolution(
        status=status,
        reason=None if status == RESOLUTION_RESOLVED else "unresolved",
        anchor_institution_id="our",
        availability_match_key=key if status == RESOLUTION_RESOLVED else None,
        active_match_keys=(key,) if status == RESOLUTION_RESOLVED else (),
        cohort_institution_ids=tuple(cohort),
        as_of=None,
    )


def _insert_candidate_fixture(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executemany(
            "INSERT INTO institutions(id, sector, active) VALUES (?, ?, ?)",
            [
                ("our", "savings_bank", 1),
                ("peer", "savings_bank", 1),
                ("missing", "savings_bank", 1),
                ("outside", "savings_bank", 1),
                ("inactive-inst", "savings_bank", 0),
                ("wrong-sector", "bank", 1),
            ],
        )
        conn.executemany(
            """
            INSERT INTO products(id, institution_id, product_type, active, is_special_sale)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                ("p-our", "our", "term_deposit", 1, 0),
                ("p-peer", "peer", "term_deposit", 1, 0),
                ("p-special", "peer", "term_deposit", 1, 1),
                ("p-outside", "outside", "term_deposit", 1, 0),
                ("p-inactive-inst", "inactive-inst", "term_deposit", 1, 0),
                ("p-inactive", "peer", "term_deposit", 0, 0),
                ("p-wrong-type", "peer", "installment_savings", 1, 0),
                ("p-wrong-sector", "wrong-sector", "term_deposit", 1, 0),
                ("p-closed", "peer", "term_deposit", 1, 0),
                ("p-error", "peer", "term_deposit", 1, 0),
                ("p-null", "peer", "term_deposit", 1, 0),
                ("p-wrong-term", "peer", "term_deposit", 1, 0),
            ],
        )
        conn.executemany(
            """
            INSERT INTO product_variants(id, product_id, term_months, join_channel)
            VALUES (?, ?, ?, ?)
            """,
            [
                ("v-our", "p-our", 12, "online"),
                ("v-peer", "p-peer", 12, "branch"),
                ("v-special", "p-special", 12, "online"),
                ("v-outside", "p-outside", 12, "online"),
                ("v-inactive-inst", "p-inactive-inst", 12, "online"),
                ("v-inactive", "p-inactive", 12, "online"),
                ("v-wrong-type", "p-wrong-type", 12, "online"),
                ("v-wrong-sector", "p-wrong-sector", 12, "online"),
                ("v-closed", "p-closed", 12, "online"),
                ("v-error", "p-error", 12, "online"),
                ("v-null", "p-null", 12, "online"),
                ("v-wrong-term", "p-wrong-term", 6, "online"),
            ],
        )
        conn.executemany(
            "INSERT INTO collection_runs(id, source_id) VALUES (?, ?)",
            [("r-fsb", "fsb"), ("r-finlife", "finlife_savings_bank")],
        )
        conn.executemany(
            """
            INSERT INTO rate_observations(
                id, variant_id, run_id, max_rate, source_effective_at,
                as_of, valid_to, validation_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("o-our", "v-our", "r-fsb", 3.50, "2026-09-01", "2026-08-31", None, "valid"),
                ("o-peer", "v-peer", "r-finlife", 3.60, None, "2026-08-30", None, "valid"),
                ("o-special", "v-special", "r-fsb", 4.20, "2026-09-02", None, None, "valid"),
                ("o-outside", "v-outside", "r-fsb", 9.99, "2026-09-02", None, None, "valid"),
                (
                    "o-inactive-inst",
                    "v-inactive-inst",
                    "r-fsb",
                    8.00,
                    "2026-09-02",
                    None,
                    None,
                    "valid",
                ),
                ("o-inactive", "v-inactive", "r-fsb", 8.10, "2026-09-02", None, None, "valid"),
                ("o-wrong-type", "v-wrong-type", "r-fsb", 8.20, "2026-09-02", None, None, "valid"),
                (
                    "o-wrong-sector",
                    "v-wrong-sector",
                    "r-fsb",
                    8.30,
                    "2026-09-02",
                    None,
                    None,
                    "valid",
                ),
                ("o-closed", "v-closed", "r-fsb", 8.40, "2026-09-02", None, "2026-09-02", "valid"),
                ("o-error", "v-error", "r-fsb", 8.50, "2026-09-02", None, None, "error"),
                ("o-null", "v-null", "r-fsb", None, "2026-09-02", None, None, "valid"),
                ("o-wrong-term", "v-wrong-term", "r-fsb", 8.60, "2026-09-02", None, None, "valid"),
            ],
        )
        conn.commit()
    finally:
        conn.close()


def test_candidate_adapter_reads_only_current_canonical_cohort_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "rates.db"
    _create_db(db_path)
    _insert_candidate_fixture(db_path)

    result = build_current_relative_pricing_rate_candidates(
        db_path,
        availability=_resolution("our", "peer", "missing"),
    )

    assert result.status == "ready"
    assert result.availability_match_key == availability_match_key("YN_Busan")
    assert result.availability_scope == "FSB 가입가능지역 부산"
    assert result.cohort_institution_ids == ("missing", "our", "peer")
    assert result.candidate_institution_ids == ("our", "peer")
    assert result.missing_rate_institution_ids == ("missing",)

    by_product = {row.product_id: row for row in result.candidates}
    assert set(by_product) == {"p-our", "p-peer", "p-special"}
    assert by_product["p-our"].rate_pct == Decimal("3.5")
    assert by_product["p-our"].rate_as_of == date(2026, 9, 1)
    assert by_product["p-our"].source_id == "fsb"
    assert by_product["p-our"].join_channel == "online"
    assert by_product["p-peer"].rate_as_of == date(2026, 8, 30)
    assert by_product["p-peer"].source_id == "finlife_savings_bank"
    assert by_product["p-peer"].join_channel == "branch"
    assert by_product["p-special"].special_offer_flag is True
    assert all(
        row.availability_match_key == result.availability_match_key
        for row in result.candidates
    )
    assert all(
        row.availability_scope == result.availability_scope for row in result.candidates
    )


def test_candidate_adapter_does_not_promote_special_offer_or_source_precedence_itself(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "rates.db"
    _create_db(db_path)
    _insert_candidate_fixture(db_path)

    result = build_current_relative_pricing_rate_candidates(
        db_path,
        availability=_resolution("our", "peer"),
    )

    peer_rows = [row for row in result.candidates if row.institution_id == "peer"]
    assert {row.product_id for row in peer_rows} == {"p-peer", "p-special"}
    assert {row.source_id for row in peer_rows} == {"fsb", "finlife_savings_bank"}
    assert any(row.special_offer_flag for row in peer_rows)


def test_candidate_adapter_requires_resolved_official_availability(tmp_path: Path) -> None:
    db_path = tmp_path / "rates.db"
    _create_db(db_path)

    with pytest.raises(ValueError, match="resolved official availability"):
        build_current_relative_pricing_rate_candidates(
            db_path,
            availability=_resolution("our", status=RESOLUTION_UNRESOLVED),
        )


def test_candidate_adapter_rejects_unknown_or_malformed_fsb_area(tmp_path: Path) -> None:
    db_path = tmp_path / "rates.db"
    _create_db(db_path)

    with pytest.raises(ValueError, match="unsupported FSB availability"):
        build_current_relative_pricing_rate_candidates(
            db_path,
            availability=_resolution(
                "our",
                match_key="fsb:term_deposit:area:YN_NotReal",
            ),
        )


def test_candidate_adapter_reports_complete_rate_gap_when_cohort_has_no_rates(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "rates.db"
    _create_db(db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.executemany(
            "INSERT INTO institutions(id, sector, active) VALUES (?, 'savings_bank', 1)",
            [("our",), ("peer",)],
        )
        conn.commit()
    finally:
        conn.close()

    result = build_current_relative_pricing_rate_candidates(
        db_path,
        availability=_resolution("our", "peer"),
    )

    assert result.status == "rate_data_unavailable"
    assert result.candidates == ()
    assert result.candidate_institution_ids == ()
    assert result.missing_rate_institution_ids == ("our", "peer")


def test_candidate_adapter_rejects_non_positive_term(tmp_path: Path) -> None:
    db_path = tmp_path / "rates.db"
    _create_db(db_path)

    with pytest.raises(ValueError, match="term_months must be positive"):
        build_current_relative_pricing_rate_candidates(
            db_path,
            availability=_resolution("our"),
            term_months=0,
        )
