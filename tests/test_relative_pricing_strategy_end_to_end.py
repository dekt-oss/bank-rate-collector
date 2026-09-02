import sqlite3
from pathlib import Path

import pytest

from rate_monitor.services import strategy_service
from rate_monitor.services.fsb_availability_service import availability_match_key


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
            CREATE TABLE institution_availability_memberships (
                source_id TEXT NOT NULL,
                institution_id TEXT NOT NULL,
                product_type TEXT NOT NULL,
                area_code TEXT NOT NULL,
                availability_match_key TEXT NOT NULL,
                source_effective_date TEXT NOT NULL,
                valid_from TEXT NOT NULL,
                valid_to TEXT
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
        conn.execute("INSERT INTO collection_runs VALUES ('run-fsb', 'fsb')")
        conn.executemany(
            "INSERT INTO institutions VALUES (?, ?, 'savings_bank', 1)",
            [
                ("our", strategy_service._base.OUR_INSTITUTION_NAME),
                ("peer", "비교저축은행"),
            ],
        )
        key = availability_match_key("YN_Busan")
        conn.executemany(
            """
            INSERT INTO institution_availability_memberships(
                source_id, institution_id, product_type, area_code,
                availability_match_key, source_effective_date, valid_from, valid_to
            ) VALUES ('fsb', ?, 'term_deposit', 'YN_Busan', ?,
                      '2026-09-01', '2026-09-01 00:00:00', NULL)
            """,
            [("our", key), ("peer", key)],
        )
        conn.executemany(
            """
            INSERT INTO products(id, institution_id, product_type, active, is_special_sale)
            VALUES (?, ?, 'term_deposit', 1, 0)
            """,
            [("p-our", "our"), ("p-peer", "peer")],
        )
        conn.executemany(
            """
            INSERT INTO product_variants(id, product_id, term_months, join_channel)
            VALUES (?, ?, 12, 'online')
            """,
            [("v-our", "p-our"), ("v-peer", "p-peer")],
        )
        conn.executemany(
            """
            INSERT INTO rate_observations(
                id, variant_id, run_id, max_rate, source_effective_at,
                as_of, valid_to, validation_status
            ) VALUES (?, ?, 'run-fsb', ?, '2026-09-01', NULL, NULL, 'valid')
            """,
            [("o-our", "v-our", 3.50), ("o-peer", "v-peer", 3.60)],
        )
        conn.commit()
    finally:
        conn.close()


def _stub_non_relative_strategy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(strategy_service._base, "build_strategy_summary", lambda _path: {})
    monkeypatch.setattr(strategy_service, "build_product_history", lambda _path: {})
    monkeypatch.setattr(
        strategy_service,
        "build_savings_trend_display_policy",
        lambda _history: {},
    )
    monkeypatch.setattr(strategy_service, "build_market_funding_strategy", lambda _path: {})
    monkeypatch.setattr(
        strategy_service,
        "build_institution_funding_positions",
        lambda _path: {"available": False, "display_order": [], "sectors": {}},
    )
    monkeypatch.setattr(
        strategy_service,
        "build_rate_funding_matrix",
        lambda _path, funding_positions: {"available": False, "sectors": {}},
    )


def test_strategy_resolver_to_live_relative_pricing_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "strategy.db"
    _create_db(db_path)
    _stub_non_relative_strategy(monkeypatch)

    summary = strategy_service.build_strategy_summary(db_path)

    availability = summary["relative_pricing_availability"]
    assert availability["status"] == "resolved"
    assert availability["availability_match_key"] == availability_match_key("YN_Busan")
    assert availability["cohort_institution_ids"] == ["our", "peer"]

    diagnostics = summary["relative_pricing_rate_candidates"]
    assert diagnostics["status"] == "ready"
    assert diagnostics["candidate_institution_ids"] == ["our", "peer"]
    assert diagnostics["missing_rate_institution_ids"] == []

    relative = summary["relative_pricing"]
    assert relative["status"] == "ready"
    assert relative["pricing_peer_position"]["pricing_peer_count"] == 1
    assert relative["pricing_peer_position"]["funding_unjoined_count"] == 1
    assert relative["peers"][0]["institution_id"] == "peer"
    assert relative["peers"][0]["funding_status"] == "unavailable"
    assert relative["representative_rate_reconciliation"]["status"] == "matched"
