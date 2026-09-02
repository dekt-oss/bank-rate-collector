import json
import sqlite3
from decimal import Decimal
from pathlib import Path

from rate_monitor.services.fsb_availability_service import availability_match_key
from rate_monitor.services.relative_pricing_availability_resolver import (
    RESOLUTION_RESOLVED,
    RelativePricingAvailabilityResolution,
)
from rate_monitor.services.relative_pricing_live_service import build_relative_pricing_live


def _create_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE institutions (
                id TEXT PRIMARY KEY,
                canonical_name TEXT NOT NULL,
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
            CREATE TABLE institution_funding_observations (
                id TEXT PRIMARY KEY,
                institution_id TEXT,
                sector TEXT NOT NULL,
                source_effective_month TEXT NOT NULL,
                metric_code TEXT NOT NULL,
                value REAL NOT NULL,
                identity_status TEXT NOT NULL,
                valid_to TEXT
            );
            """
        )
        conn.executemany(
            "INSERT INTO collection_runs(id, source_id) VALUES (?, ?)",
            [("r-fsb", "fsb"), ("r-retreat", "finlife_savings_bank")],
        )
        conn.executemany(
            "INSERT INTO institutions(id, canonical_name, sector, active) VALUES (?, ?, ?, 1)",
            [
                ("our", "고려저축은행", "savings_bank"),
                ("peer", "비교저축은행", "savings_bank"),
            ],
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
    effective: str,
    special: int = 0,
    active: int = 1,
    source_run: str = "r-fsb",
) -> None:
    variant_id = "v-" + product_id
    conn.execute(
        """
        INSERT INTO products(id, institution_id, product_type, active, is_special_sale)
        VALUES (?, ?, 'term_deposit', ?, ?)
        """,
        (product_id, institution_id, active, special),
    )
    conn.execute(
        """
        INSERT INTO product_variants(id, product_id, term_months, join_channel)
        VALUES (?, ?, 12, 'online')
        """,
        (variant_id, product_id),
    )
    conn.execute(
        """
        INSERT INTO rate_observations(
            id, variant_id, run_id, max_rate, source_effective_at,
            as_of, valid_to, validation_status
        ) VALUES (?, ?, ?, ?, ?, NULL, NULL, 'valid')
        """,
        ("o-" + product_id, variant_id, source_run, rate, effective),
    )


def _availability() -> RelativePricingAvailabilityResolution:
    key = availability_match_key("YN_Busan")
    return RelativePricingAvailabilityResolution(
        status=RESOLUTION_RESOLVED,
        reason=None,
        anchor_institution_id="our",
        availability_match_key=key,
        active_match_keys=(key,),
        cohort_institution_ids=("our", "peer"),
        as_of="2026-09-02 00:00:00",
    )


def _seed_normal_rates(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        _add_rate(
            conn,
            institution_id="our",
            product_id="p-our",
            rate=3.50,
            effective="2026-09-01",
        )
        _add_rate(
            conn,
            institution_id="peer",
            product_id="p-peer",
            rate=3.60,
            effective="2026-09-01",
        )
        conn.commit()
    finally:
        conn.close()


def test_live_builder_produces_ready_factual_payload_without_funding(tmp_path: Path) -> None:
    db_path = tmp_path / "relative.db"
    _create_db(db_path)
    _seed_normal_rates(db_path)

    result = build_relative_pricing_live(db_path, availability=_availability())

    assert result.payload["status"] == "ready"
    assert result.payload["reason"] is None
    assert result.payload["scope"]["availability_match_key"] == availability_match_key(
        "YN_Busan"
    )
    assert result.payload["pricing_peer_position"]["pricing_peer_count"] == 1
    assert result.payload["pricing_peer_position"]["funding_join_count"] == 0
    assert result.payload["pricing_peer_position"]["funding_unjoined_count"] == 1
    assert result.payload["peers"][0]["institution_id"] == "peer"
    assert result.payload["peers"][0]["funding_status"] == "unavailable"
    assert result.payload["representative_rate_reconciliation"]["status"] == "matched"
    assert result.diagnostics()["candidate_institution_ids"] == ["our", "peer"]
    assert result.diagnostics()["funding_analysis_month"] is None

    encoded = json.dumps(result.payload, ensure_ascii=False)
    assert "predicted_inflow" not in encoded
    assert "recommended_rate" not in encoded
    assert "target_balance" not in encoded


def test_live_builder_accepts_explained_matrix_special_offer_difference(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "relative.db"
    _create_db(db_path)
    _seed_normal_rates(db_path)
    conn = sqlite3.connect(db_path)
    try:
        _add_rate(
            conn,
            institution_id="peer",
            product_id="p-peer-special",
            rate=4.20,
            effective="2026-09-01",
            special=1,
        )
        conn.commit()
    finally:
        conn.close()

    result = build_relative_pricing_live(db_path, availability=_availability())

    assert result.payload["status"] == "ready"
    peer_recon = result.payload["representative_rate_reconciliations"]["peer"]
    assert peer_recon["status"] == "explained"
    assert Decimal(peer_recon["pricing_rate_pct"]) == Decimal("3.6")
    assert Decimal(peer_recon["matrix_rate_pct"]) == Decimal("4.2")
    assert Decimal(peer_recon["gap_bp"]) == Decimal("-60")
    assert peer_recon["difference_reason"] == (
        "matrix_selection_outside_pricing_core:special_offer"
    )
    assert Decimal(result.payload["peers"][0]["rate_pct"]) == Decimal("3.6")


def test_live_builder_fails_closed_on_matrix_temporal_mismatch(tmp_path: Path) -> None:
    db_path = tmp_path / "relative.db"
    _create_db(db_path)
    _seed_normal_rates(db_path)
    conn = sqlite3.connect(db_path)
    try:
        _add_rate(
            conn,
            institution_id="peer",
            product_id="p-peer-special",
            rate=4.20,
            effective="2026-09-02",
            special=1,
        )
        conn.commit()
    finally:
        conn.close()

    result = build_relative_pricing_live(db_path, availability=_availability())

    assert result.payload["status"] == "insufficient_data"
    assert result.payload["reason"] == "matrix_representative_rate_temporal_mismatch"
    peer_recon = result.payload["representative_rate_reconciliations"]["peer"]
    assert peer_recon["status"] == "temporal_mismatch"
    assert result.payload["pricing_peer_position"] is None


def test_live_builder_enriches_peer_with_exact_month_funding_when_available(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "relative.db"
    _create_db(db_path)
    _seed_normal_rates(db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.executemany(
            """
            INSERT INTO institution_funding_observations(
                id, institution_id, sector, source_effective_month,
                metric_code, value, identity_status, valid_to
            ) VALUES (?, ?, 'savings_bank', '2026-03',
                      'deposit_liabilities_total', ?, 'mapped_exact_fss_code', NULL)
            """,
            [
                ("f-our", "our", 120000.0),
                ("f-peer", "peer", 150000.0),
            ],
        )
        conn.commit()
    finally:
        conn.close()

    positions = {"sectors": {"savings_bank": {"analysis_month": "2026-03"}}}
    result = build_relative_pricing_live(
        db_path,
        availability=_availability(),
        funding_positions=positions,
    )

    assert result.payload["status"] == "ready"
    assert result.payload["pricing_peer_position"]["funding_analysis_month"] == "2026-03"
    assert result.payload["pricing_peer_position"]["funding_join_count"] == 1
    assert result.payload["pricing_peer_position"]["funding_unjoined_count"] == 0
    peer = result.payload["peers"][0]
    assert peer["funding_balance_million_krw"] == "150000.0"
    assert peer["funding_as_of"] == "2026-03"
    assert peer["funding_status"] == "known"
