"""Stage C1 시장이력 파생계약 테스트."""

import sqlite3
from pathlib import Path

from rate_monitor.services.market_intelligence_service import build_market_intelligence


def _create_schema(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE sources (
            id TEXT PRIMARY KEY,
            sector TEXT NOT NULL
        );
        CREATE TABLE collection_runs (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT
        );
        CREATE TABLE institutions (
            id TEXT PRIMARY KEY,
            sector TEXT NOT NULL,
            canonical_name TEXT NOT NULL,
            normalized_name TEXT
        );
        CREATE TABLE products (
            id TEXT PRIMARY KEY,
            institution_id TEXT NOT NULL,
            product_type TEXT NOT NULL,
            name TEXT NOT NULL
        );
        CREATE TABLE product_variants (
            id TEXT PRIMARY KEY,
            product_id TEXT NOT NULL,
            term_months INTEGER
        );
        CREATE TABLE rate_observations (
            id TEXT PRIMARY KEY,
            variant_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            valid_from TEXT NOT NULL,
            valid_to TEXT,
            max_rate REAL,
            validation_status TEXT NOT NULL
        );
        """
    )
    return conn


def _insert_product(
    conn: sqlite3.Connection,
    *,
    institution_id: str,
    institution: str,
    product_id: str,
    sector: str = "savings_bank",
    term: int = 12,
) -> str:
    variant_id = f"v-{product_id}"
    conn.execute(
        "INSERT OR IGNORE INTO institutions VALUES (?, ?, ?, ?)",
        (institution_id, sector, institution, institution),
    )
    conn.execute(
        "INSERT INTO products VALUES (?, ?, 'term_deposit', ?)",
        (product_id, institution_id, f"상품-{product_id}"),
    )
    conn.execute(
        "INSERT INTO product_variants VALUES (?, ?, ?)",
        (variant_id, product_id, term),
    )
    return variant_id


def _scope(result: dict, sector: str, term: int, window: int) -> dict:
    return next(
        item
        for item in result["scopes"]
        if item["sector"] == sector
        and item["term_months"] == term
        and item["window_days"] == window
    )


def test_supported_scope_uses_stable_product_snapshot_changes(tmp_path: Path) -> None:
    conn = _create_schema(tmp_path / "market.sqlite3")
    try:
        conn.execute("INSERT INTO sources VALUES ('fsb', 'savings_bank')")
        for run_id, when in (
            ("r0", "2026-07-15T00:00:00"),
            ("r1", "2026-08-11T00:00:00"),
            ("r2", "2026-08-18T00:00:00"),
        ):
            conn.execute(
                "INSERT INTO collection_runs VALUES (?, 'fsb', 'success', ?, ?)",
                (run_id, when, when),
            )

        v1 = _insert_product(
            conn,
            institution_id="i1",
            institution="경쟁A저축은행",
            product_id="p1",
        )
        v2 = _insert_product(
            conn,
            institution_id="i2",
            institution="경쟁B저축은행",
            product_id="p2",
        )
        v3 = _insert_product(
            conn,
            institution_id="i3",
            institution="고려저축은행",
            product_id="p3",
        )

        conn.executemany(
            "INSERT INTO rate_observations VALUES (?, ?, ?, ?, ?, ?, 'valid')",
            [
                ("o1", v1, "r0", "2026-07-01T00:00:00", "2026-08-15T00:00:00", 3.00),
                ("o2", v1, "r2", "2026-08-15T00:00:00", None, 3.20),
                ("o3", v2, "r0", "2026-07-01T00:00:00", None, 3.40),
                ("o4", v3, "r0", "2026-07-01T00:00:00", "2026-08-16T00:00:00", 3.30),
                ("o5", v3, "r2", "2026-08-16T00:00:00", None, 3.36),
            ],
        )
        conn.commit()

        result = build_market_intelligence(conn)
        seven = _scope(result, "savings_bank", 12, 7)
        thirty = _scope(result, "savings_bank", 12, 30)

        assert result["version"] == "market-intelligence-v1"
        assert seven["status"] == "supported"
        assert thirty["status"] == "supported"
        assert seven["comparable_product_count"] == 3
        assert seven["up_count"] == 2
        assert seven["down_count"] == 0
        assert seven["unchanged_count"] == 1
        assert seven["breadth_score"] == 0.6667
        assert seven["median_change_bp"] == 6.0
        assert seven["upper_decile_change_bp"] == 0.0
        assert seven["direction"] == "rising"
        assert seven["top_decile_churn_rate"] == 0.0
        assert seven["our_company"] == {
            "start_rate": 3.3,
            "end_rate": 3.36,
            "rate_change_bp": 6.0,
            "spread_vs_median_start_bp": 0.0,
            "spread_vs_median_end_bp": 0.0,
            "spread_change_bp": 0.0,
        }
        assert thirty["observed_days"] == 34.0
        assert thirty["coverage_ratio"] > 1.0
    finally:
        conn.close()


def test_history_gate_does_not_label_two_days_as_seven_day_change(tmp_path: Path) -> None:
    conn = _create_schema(tmp_path / "short.sqlite3")
    try:
        conn.execute("INSERT INTO sources VALUES ('fsb', 'savings_bank')")
        for run_id, when in (
            ("r0", "2026-08-16T00:00:00"),
            ("r1", "2026-08-18T00:00:00"),
        ):
            conn.execute(
                "INSERT INTO collection_runs VALUES (?, 'fsb', 'success', ?, ?)",
                (run_id, when, when),
            )
        variant = _insert_product(
            conn,
            institution_id="i1",
            institution="테스트저축은행",
            product_id="p1",
        )
        conn.execute(
            """
            INSERT INTO rate_observations
            VALUES ('o1', ?, 'r0', '2026-08-01T00:00:00', NULL, 3.20, 'valid')
            """,
            (variant,),
        )
        conn.commit()

        result = build_market_intelligence(conn)
        seven = _scope(result, "savings_bank", 12, 7)

        assert seven["status"] == "insufficient_history"
        assert seven["median_change_bp"] is None
        assert seven["breadth_score"] is None
        assert seven["direction"] == "insufficient"
    finally:
        conn.close()


def test_nh_local_history_fails_closed_until_strategy_rate_basis_is_reconstructed(
    tmp_path: Path,
) -> None:
    conn = _create_schema(tmp_path / "nh.sqlite3")
    try:
        conn.execute("INSERT INTO sources VALUES ('nh_local', 'nh_local')")
        conn.execute(
            """
            INSERT INTO collection_runs
            VALUES (
                'r0', 'nh_local', 'success',
                '2026-07-01T00:00:00', '2026-07-01T00:00:00'
            )
            """
        )
        conn.execute(
            """
            INSERT INTO collection_runs
            VALUES (
                'r1', 'nh_local', 'success',
                '2026-08-18T00:00:00', '2026-08-18T00:00:00'
            )
            """
        )
        variant = _insert_product(
            conn,
            institution_id="n1",
            institution="테스트농협",
            product_id="np1",
            sector="nh_local",
        )
        conn.execute(
            """
            INSERT INTO rate_observations
            VALUES ('no1', ?, 'r0', '2026-07-01T00:00:00', NULL, 3.50, 'valid')
            """,
            (variant,),
        )
        conn.commit()

        result = build_market_intelligence(conn)
        nh = _scope(result, "nh_local", 12, 30)

        assert nh["status"] == "unsupported_rate_contract"
        assert nh["median_change_bp"] is None
        assert "e-joy base+add" in nh["reason"]
    finally:
        conn.close()


def test_missing_modern_history_schema_returns_explicit_unavailable_state(
    tmp_path: Path,
) -> None:
    conn = sqlite3.connect(tmp_path / "old.sqlite3")
    try:
        conn.execute("CREATE TABLE institutions (id TEXT PRIMARY KEY)")
        result = build_market_intelligence(conn)
    finally:
        conn.close()

    assert result == {
        "version": "market-intelligence-v1",
        "status": "schema_unavailable",
        "history_gate": {"minimum_window_coverage_ratio": 0.8},
        "scopes": [],
        "supported_scope_count": 0,
    }
