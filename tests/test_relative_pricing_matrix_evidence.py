import sqlite3
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from rate_monitor.services.rate_funding_matrix_service import RATE_REPRESENTATIVE
from rate_monitor.services.relative_pricing_matrix_evidence import (
    build_current_matrix_representative_evidence,
)


def _create_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
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
                term_months INTEGER
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
        conn.executemany(
            "INSERT INTO collection_runs(id, source_id) VALUES (?, ?)",
            [("r-fsb", "fsb"), ("r-retreat", "finlife_savings_bank")],
        )
        conn.commit()
    finally:
        conn.close()


def _add_rate(
    conn: sqlite3.Connection,
    *,
    institution_id: str,
    product_id: str,
    rate: float,
    source_id: str = "r-fsb",
    effective: str | None = "2026-09-01",
    as_of: str | None = None,
    active: int = 1,
    special: int = 0,
    term: int = 12,
) -> None:
    variant_id = "v-" + product_id
    observation_id = "o-" + product_id
    conn.execute(
        """
        INSERT INTO products(id, institution_id, product_type, active, is_special_sale)
        VALUES (?, ?, 'term_deposit', ?, ?)
        """,
        (product_id, institution_id, active, special),
    )
    conn.execute(
        "INSERT INTO product_variants(id, product_id, term_months) VALUES (?, ?, ?)",
        (variant_id, product_id, term),
    )
    conn.execute(
        """
        INSERT INTO rate_observations(
            id, variant_id, run_id, max_rate, source_effective_at,
            as_of, valid_to, validation_status
        ) VALUES (?, ?, ?, ?, ?, ?, NULL, 'valid')
        """,
        (observation_id, variant_id, source_id, rate, effective, as_of),
    )


def test_matrix_evidence_uses_exact_matrix_source_retreat_and_max_policy(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "matrix.db"
    _create_db(db_path)
    conn = sqlite3.connect(db_path)
    try:
        _add_rate(conn, institution_id="our", product_id="p-primary-low", rate=3.50)
        _add_rate(conn, institution_id="our", product_id="p-primary-high", rate=3.70)
        _add_rate(
            conn,
            institution_id="our",
            product_id="p-retreating-higher",
            rate=4.50,
            source_id="r-retreat",
        )
        conn.commit()
    finally:
        conn.close()

    evidence = build_current_matrix_representative_evidence(
        db_path,
        institution_ids={"our"},
    )["our"]

    assert evidence.rate_pct == Decimal("3.7")
    assert evidence.policy_id == RATE_REPRESENTATIVE
    assert evidence.rate_as_of == date(2026, 9, 1)
    assert evidence.rate_as_of_status == "resolved"
    assert evidence.selected_product_ids == ("p-primary-high",)
    assert evidence.selected_source_ids == ("fsb",)
    assert evidence.pricing_core_difference_reason is None


def test_matrix_evidence_explains_matrix_only_special_offer_rate(tmp_path: Path) -> None:
    db_path = tmp_path / "matrix.db"
    _create_db(db_path)
    conn = sqlite3.connect(db_path)
    try:
        _add_rate(conn, institution_id="peer", product_id="p-normal", rate=3.60)
        _add_rate(
            conn,
            institution_id="peer",
            product_id="p-special",
            rate=4.20,
            special=1,
        )
        conn.commit()
    finally:
        conn.close()

    evidence = build_current_matrix_representative_evidence(
        db_path,
        institution_ids=["peer"],
    )["peer"]

    assert evidence.rate_pct == Decimal("4.2")
    assert evidence.pricing_core_difference_reason == (
        "matrix_selection_outside_pricing_core:special_offer"
    )


def test_matrix_evidence_explains_inactive_product_only_when_all_selected_rows_excluded(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "matrix.db"
    _create_db(db_path)
    conn = sqlite3.connect(db_path)
    try:
        _add_rate(conn, institution_id="peer", product_id="p-normal", rate=3.40)
        _add_rate(
            conn,
            institution_id="peer",
            product_id="p-inactive",
            rate=4.30,
            active=0,
        )
        conn.commit()
    finally:
        conn.close()

    evidence = build_current_matrix_representative_evidence(
        db_path,
        institution_ids=["peer"],
    )["peer"]

    assert evidence.rate_pct == Decimal("4.3")
    assert evidence.pricing_core_difference_reason == (
        "matrix_selection_outside_pricing_core:inactive_product"
    )


def test_matrix_evidence_refuses_to_choose_date_across_equal_rate_ties(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "matrix.db"
    _create_db(db_path)
    conn = sqlite3.connect(db_path)
    try:
        _add_rate(
            conn,
            institution_id="tie",
            product_id="p-a",
            rate=3.80,
            effective="2026-09-01",
        )
        _add_rate(
            conn,
            institution_id="tie",
            product_id="p-b",
            rate=3.80,
            effective="2026-09-02",
        )
        conn.commit()
    finally:
        conn.close()

    evidence = build_current_matrix_representative_evidence(
        db_path,
        institution_ids=["tie"],
    )["tie"]

    assert evidence.rate_pct == Decimal("3.8")
    assert evidence.rate_as_of is None
    assert evidence.rate_as_of_status == "ambiguous"
    assert evidence.selected_product_ids == ("p-a", "p-b")
    assert evidence.pricing_core_difference_reason is None


def test_matrix_evidence_uses_as_of_only_when_source_effective_date_missing(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "matrix.db"
    _create_db(db_path)
    conn = sqlite3.connect(db_path)
    try:
        _add_rate(
            conn,
            institution_id="peer",
            product_id="p-a",
            rate=3.60,
            effective=None,
            as_of="2026-08-31",
        )
        conn.commit()
    finally:
        conn.close()

    evidence = build_current_matrix_representative_evidence(
        db_path,
        institution_ids=["peer"],
    )["peer"]

    assert evidence.rate_as_of == date(2026, 8, 31)
    assert evidence.rate_as_of_status == "resolved"


def test_matrix_evidence_empty_population_and_term_validation(tmp_path: Path) -> None:
    db_path = tmp_path / "matrix.db"
    _create_db(db_path)

    assert build_current_matrix_representative_evidence(
        db_path,
        institution_ids=[],
    ) == {}
    with pytest.raises(ValueError, match="term_months must be positive"):
        build_current_matrix_representative_evidence(
            db_path,
            institution_ids=["peer"],
            term_months=0,
        )
