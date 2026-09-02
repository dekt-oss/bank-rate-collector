import sqlite3
from pathlib import Path

from rate_monitor.services.fsb_availability_service import availability_match_key
from rate_monitor.services.relative_pricing_availability_resolver import (
    RESOLUTION_RESOLVED,
    RelativePricingAvailabilityResolution,
)
from rate_monitor.services.relative_pricing_rate_candidates import (
    build_current_relative_pricing_rate_candidates,
)


def _availability() -> RelativePricingAvailabilityResolution:
    key = availability_match_key("YN_Busan")
    return RelativePricingAvailabilityResolution(
        status=RESOLUTION_RESOLVED,
        reason=None,
        anchor_institution_id="our",
        availability_match_key=key,
        active_match_keys=(key,),
        cohort_institution_ids=("our",),
        as_of=None,
    )


def _db(path: Path, *, source_effective_at: str | None, as_of: str | None) -> None:
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
        conn.execute(
            "INSERT INTO institutions(id, sector, active) VALUES ('our', 'savings_bank', 1)"
        )
        conn.execute(
            """
            INSERT INTO products(id, institution_id, product_type, active, is_special_sale)
            VALUES ('p', 'our', 'term_deposit', 1, 0)
            """
        )
        conn.execute(
            """
            INSERT INTO product_variants(id, product_id, term_months, join_channel)
            VALUES ('v', 'p', 12, 'online')
            """
        )
        conn.execute("INSERT INTO collection_runs(id, source_id) VALUES ('r', 'fsb')")
        conn.execute(
            """
            INSERT INTO rate_observations(
                id, variant_id, run_id, max_rate, source_effective_at,
                as_of, valid_to, validation_status
            ) VALUES ('o', 'v', 'r', 3.5, ?, ?, NULL, 'valid')
            """,
            (source_effective_at, as_of),
        )
        conn.commit()
    finally:
        conn.close()


def test_malformed_primary_rate_date_becomes_temporal_gap_not_fallback(tmp_path: Path) -> None:
    db_path = tmp_path / "rates.db"
    _db(db_path, source_effective_at="not-a-date", as_of="2026-09-01")

    result = build_current_relative_pricing_rate_candidates(
        db_path,
        availability=_availability(),
    )

    assert len(result.candidates) == 1
    assert result.candidates[0].rate_as_of is None


def test_malformed_fallback_rate_date_becomes_temporal_gap(tmp_path: Path) -> None:
    db_path = tmp_path / "rates.db"
    _db(db_path, source_effective_at=None, as_of="bad-date")

    result = build_current_relative_pricing_rate_candidates(
        db_path,
        availability=_availability(),
    )

    assert len(result.candidates) == 1
    assert result.candidates[0].rate_as_of is None
