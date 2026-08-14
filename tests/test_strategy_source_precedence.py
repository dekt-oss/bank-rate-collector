# ruff: noqa: E501

import sqlite3
from pathlib import Path

from rate_monitor.services.strategy_service import build_strategy_summary


def _make_multi_source_db(path: Path) -> Path:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE sources (id TEXT PRIMARY KEY, sector TEXT NOT NULL);
            CREATE TABLE collection_runs (
                id TEXT PRIMARY KEY, source_id TEXT NOT NULL,
                started_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL
            );
            CREATE TABLE institutions (
                id TEXT PRIMARY KEY, sector TEXT NOT NULL,
                canonical_name TEXT NOT NULL, normalized_name TEXT NOT NULL
            );
            CREATE TABLE products (
                id TEXT PRIMARY KEY, institution_id TEXT NOT NULL,
                product_type TEXT NOT NULL, name TEXT NOT NULL
            );
            CREATE TABLE product_variants (
                id TEXT PRIMARY KEY, product_id TEXT NOT NULL, term_months INTEGER
            );
            CREATE TABLE rate_observations (
                id TEXT PRIMARY KEY, variant_id TEXT NOT NULL, run_id TEXT NOT NULL,
                valid_from TEXT NOT NULL, valid_to TEXT, max_rate REAL,
                validation_status TEXT NOT NULL
            );

            INSERT INTO sources VALUES ('fsb', 'savings_bank');
            INSERT INTO sources VALUES ('finlife_savings_bank', 'savings_bank');
            INSERT INTO institutions VALUES ('i-covered', 'savings_bank', '테스트저축은행', '테스트저축은행');
            INSERT INTO institutions VALUES ('i-fallback', 'savings_bank', '보완저축은행', '보완저축은행');
            INSERT INTO products VALUES ('p-fsb', 'i-covered', 'term_deposit', '대표예금');
            INSERT INTO products VALUES ('p-fin', 'i-covered', 'term_deposit', '대표예금 FIN');
            INSERT INTO products VALUES ('p-only', 'i-fallback', 'term_deposit', '보완예금');
            INSERT INTO product_variants VALUES ('v-fsb', 'p-fsb', 12);
            INSERT INTO product_variants VALUES ('v-fin', 'p-fin', 12);
            INSERT INTO product_variants VALUES ('v-only', 'p-only', 12);
            INSERT INTO collection_runs VALUES ('r-fsb-old', 'fsb', datetime('now', '-2 day'), datetime('now', '-2 day'), 'success');
            INSERT INTO collection_runs VALUES ('r-fin-old', 'finlife_savings_bank', datetime('now', '-2 day', '+1 minute'), datetime('now', '-2 day', '+1 minute'), 'success');
            INSERT INTO collection_runs VALUES ('r-fsb-new', 'fsb', datetime('now', '-1 day'), datetime('now', '-1 day'), 'success');
            INSERT INTO collection_runs VALUES ('r-fin-new', 'finlife_savings_bank', datetime('now', '-1 day', '+1 minute'), datetime('now', '-1 day', '+1 minute'), 'success');
            INSERT INTO rate_observations VALUES ('o-fsb-old', 'v-fsb', 'r-fsb-old', datetime('now', '-2 day'), datetime('now', '-1 day'), 3.00, 'valid');
            INSERT INTO rate_observations VALUES ('o-fsb-new', 'v-fsb', 'r-fsb-new', datetime('now', '-1 day'), NULL, 3.20, 'valid');
            INSERT INTO rate_observations VALUES ('o-fin-old', 'v-fin', 'r-fin-old', datetime('now', '-2 day'), datetime('now', '-1 day'), 4.00, 'valid');
            INSERT INTO rate_observations VALUES ('o-fin-new', 'v-fin', 'r-fin-new', datetime('now', '-1 day'), NULL, 4.50, 'valid');
            INSERT INTO rate_observations VALUES ('o-only-old', 'v-only', 'r-fin-old', datetime('now', '-2 day'), datetime('now', '-1 day'), 3.70, 'valid');
            INSERT INTO rate_observations VALUES ('o-only-new', 'v-only', 'r-fin-new', datetime('now', '-1 day'), NULL, 3.90, 'valid');
            """
        )
        conn.commit()
    finally:
        conn.close()
    return path


def test_strategy_history_uses_public_source_precedence(tmp_path: Path) -> None:
    summary = build_strategy_summary(_make_multi_source_db(tmp_path / "multi.sqlite3"))
    changes = summary["market_changes"]
    assert changes["count"] == 2
    assert changes["up_count"] == 2
    assert changes["down_count"] == 0
    assert {item["institution"] for item in changes["items"]} == {
        "테스트저축은행",
        "보완저축은행",
    }
    assert all(item["max_rate"] != 4.50 for item in changes["items"])
    assert changes["scope"]["source_precedence"] == "presentation.db_only_sources"

    points = summary["rate_trend"]["points"]
    assert len(points) == 2
    assert [point["product_count"] for point in points] == [2, 2]
    assert points[0]["mean_max_rate"] == 3.35
    assert points[0]["market_max_rate"] == 3.70
    assert points[-1]["mean_max_rate"] == 3.55
    assert points[-1]["market_max_rate"] == 3.90
    assert summary["rate_trend"]["scope"]["source_precedence"] == "presentation.db_only_sources"
