from __future__ import annotations

import sqlite3
from pathlib import Path

from rate_monitor.services.size_peer_strategy_payload import build_size_peer_strategy_payload


def _schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE institutions (
            id TEXT PRIMARY KEY,
            sector TEXT NOT NULL,
            canonical_name TEXT NOT NULL,
            active INTEGER NOT NULL
        );
        CREATE TABLE institution_funding_observations (
            institution_id TEXT,
            source_id TEXT NOT NULL,
            source_institution_key TEXT NOT NULL,
            source_crno TEXT,
            sector TEXT NOT NULL,
            metric_code TEXT NOT NULL,
            source_effective_month TEXT NOT NULL,
            value TEXT NOT NULL,
            unit TEXT NOT NULL,
            identity_status TEXT NOT NULL,
            valid_to TEXT
        );
        CREATE TABLE products (
            id TEXT PRIMARY KEY,
            institution_id TEXT NOT NULL,
            product_type TEXT NOT NULL,
            active INTEGER NOT NULL
        );
        CREATE TABLE product_variants (
            id TEXT PRIMARY KEY,
            product_id TEXT NOT NULL,
            outlet_id TEXT,
            term_months INTEGER,
            join_channel TEXT
        );
        CREATE TABLE rate_observations (
            id TEXT PRIMARY KEY,
            variant_id TEXT NOT NULL,
            last_run_id TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            valid_to TEXT,
            validation_status TEXT
        );
        CREATE TABLE collection_runs (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL
        );
        CREATE TABLE outlets (
            id TEXT PRIMARY KEY,
            institution_id TEXT NOT NULL,
            region_sido TEXT,
            region_sigungu TEXT,
            address TEXT,
            active INTEGER NOT NULL
        );
        CREATE TABLE source_entity_links (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            valid_to TEXT
        );
        """
    )


def _funding_pair(
    conn: sqlite3.Connection,
    *,
    institution_id: str,
    sector: str,
    source_id: str,
    key: str,
    month: str,
    funding: str,
    assets: str | None,
) -> None:
    rows = [("deposit_liabilities_total", funding)]
    if assets is not None:
        rows.append(("total_assets", assets))
    for metric, value in rows:
        conn.execute(
            """
            INSERT INTO institution_funding_observations
            (institution_id, source_id, source_institution_key, source_crno, sector,
             metric_code, source_effective_month, value, unit, identity_status, valid_to)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'million_krw', 'mapped_exact_fss_code', NULL)
            """,
            (
                institution_id,
                source_id,
                key,
                f"crno-{institution_id}",
                sector,
                metric,
                month,
                value,
            ),
        )


def _current_product(
    conn: sqlite3.Connection,
    *,
    institution_id: str,
    sector: str,
    source_id: str,
    channel: str,
    last_seen: str,
    outlet_id: str | None = None,
) -> None:
    product_id = f"p-{institution_id}"
    variant_id = f"v-{institution_id}"
    run_id = f"run-{institution_id}"
    conn.execute(
        "INSERT INTO products VALUES (?, ?, 'term_deposit', 1)",
        (product_id, institution_id),
    )
    conn.execute(
        "INSERT INTO product_variants VALUES (?, ?, ?, 12, ?)",
        (variant_id, product_id, outlet_id, channel),
    )
    conn.execute("INSERT INTO collection_runs VALUES (?, ?)", (run_id, source_id))
    conn.execute(
        "INSERT INTO rate_observations VALUES (?, ?, ?, ?, NULL, 'valid')",
        (f"obs-{institution_id}", variant_id, run_id, last_seen),
    )


def _busan_outlet(
    conn: sqlite3.Connection,
    *,
    outlet_id: str,
    institution_id: str,
    district: str,
    fsb_link: bool,
) -> None:
    conn.execute(
        "INSERT INTO outlets VALUES (?, ?, '부산광역시', ?, ?, 1)",
        (outlet_id, institution_id, district, f"부산광역시 {district} 중앙대로 1"),
    )
    if fsb_link:
        conn.execute(
            "INSERT INTO source_entity_links VALUES (?, 'fsb', 'outlet', ?, NULL)",
            (f"link-{outlet_id}", outlet_id),
        )


def _fixture(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        _schema(conn)
        institutions = (
            ("koryo", "savings_bank", "고려저축은행", 1),
            ("save-peer", "savings_bank", "부산저축은행", 1),
            ("nh-mobile", "nh_local", "모바일농협", 1),
            ("nh-any", "nh_local", "ANY농협", 1),
            ("save-incomplete", "savings_bank", "불완전저축은행", 1),
        )
        conn.executemany("INSERT INTO institutions VALUES (?, ?, ?, ?)", institutions)

        _funding_pair(
            conn,
            institution_id="koryo",
            sector="savings_bank",
            source_id="data_go_savings_bank_funding",
            key="koryo-key",
            month="2025-12",
            funding="1804862",
            assets="2059073",
        )
        _funding_pair(
            conn,
            institution_id="save-peer",
            sector="savings_bank",
            source_id="data_go_savings_bank_funding",
            key="save-peer-key",
            month="2025-12",
            funding="1900000",
            assets="2100000",
        )
        _funding_pair(
            conn,
            institution_id="nh-mobile",
            sector="nh_local",
            source_id="data_go_agri_coop_funding",
            key="nh-mobile-key",
            month="2025-12",
            funding="1500000",
            assets="1700000",
        )
        _funding_pair(
            conn,
            institution_id="nh-any",
            sector="nh_local",
            source_id="data_go_agri_coop_funding",
            key="nh-any-key",
            month="2025-12",
            funding="1810000",
            assets="2060000",
        )
        _funding_pair(
            conn,
            institution_id="save-incomplete",
            sector="savings_bank",
            source_id="data_go_savings_bank_funding",
            key="save-incomplete-key",
            month="2025-12",
            funding="1750000",
            assets=None,
        )
        # A newer savings-bank-only pair must not be mixed with the NH 2025-12 vintage.
        _funding_pair(
            conn,
            institution_id="koryo",
            sector="savings_bank",
            source_id="data_go_savings_bank_funding",
            key="koryo-key",
            month="2026-03",
            funding="1850000",
            assets="2100000",
        )

        _busan_outlet(
            conn,
            outlet_id="out-koryo",
            institution_id="koryo",
            district="동구",
            fsb_link=True,
        )
        _busan_outlet(
            conn,
            outlet_id="out-save",
            institution_id="save-peer",
            district="해운대구",
            fsb_link=True,
        )
        _busan_outlet(
            conn,
            outlet_id="out-nh-mobile",
            institution_id="nh-mobile",
            district="부산진구",
            fsb_link=False,
        )
        _busan_outlet(
            conn,
            outlet_id="out-nh-any",
            institution_id="nh-any",
            district="사하구",
            fsb_link=False,
        )

        _current_product(
            conn,
            institution_id="koryo",
            sector="savings_bank",
            source_id="fsb",
            channel="any",
            last_seen="2026-09-05 07:30:00",
        )
        _current_product(
            conn,
            institution_id="save-peer",
            sector="savings_bank",
            source_id="fsb",
            channel="any",
            last_seen="2026-09-05 07:30:00",
        )
        _current_product(
            conn,
            institution_id="nh-mobile",
            sector="nh_local",
            source_id="nh_local",
            channel="mobile",
            last_seen="2026-09-04 08:10:00",
            outlet_id="out-nh-mobile",
        )
        _current_product(
            conn,
            institution_id="nh-any",
            sector="nh_local",
            source_id="nh_local",
            channel="any",
            last_seen="2026-09-04 08:10:00",
            outlet_id="out-nh-any",
        )
        conn.commit()
    finally:
        conn.close()


def test_strategy_size_peer_payload_keeps_two_clocks_and_scenario_universes(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "rates.db"
    _fixture(db_path)

    payload = build_size_peer_strategy_payload(db_path)

    assert payload["status"] == "ready"
    assert payload["policy_id"] == "strategy-size-peer-ranking"
    assert payload["policy_version"] == "1"
    assert payload["financial_as_of"] == "2025-12"
    assert payload["eligibility_as_of"] == "2026-09-04"
    assert payload["eligibility_source_as_of"] == {
        "fsb": "2026-09-05",
        "nh_local": "2026-09-04",
    }
    assert payload["supported_sectors"] == ["savings_bank", "nh_local"]
    assert payload["unsupported_sectors"] == ["cu", "kfcc"]
    assert payload["anchor"] == {
        "institution_id": "koryo",
        "institution": "고려저축은행",
        "sector": "savings_bank",
        "deposit_liabilities_total": "1804862.0000",
        "total_assets": "2059073.0000",
    }
    assert payload["financial_candidate_count"] == 4

    remote = payload["modes"]["remote"]
    assert remote["status"] == "ready"
    assert remote["eligible_count"] == 3
    assert remote["ranked_count"] == 2
    assert [row["institution_id"] for row in remote["display_rows"]] == [
        "save-peer",
        "nh-mobile",
    ]
    assert "nh-any" not in {row["institution_id"] for row in remote["display_rows"]}

    branch = payload["modes"]["branch_busan"]
    assert branch["status"] == "ready"
    assert branch["eligible_count"] == 4
    assert branch["ranked_count"] == 3
    assert branch["display_rows"][0]["institution_id"] == "nh-any"
    assert {row["institution_id"] for row in branch["display_rows"]} == {
        "save-peer",
        "nh-mobile",
        "nh-any",
    }

    first = branch["display_rows"][0]
    assert float(first["worst_axis_gap"]) >= 0
    assert first["worst_axis_gap_ratio_pct"] >= 0
    assert first["financial_as_of"] == "2025-12"


def test_strategy_size_peer_payload_fails_closed_without_anchor_pair(tmp_path: Path) -> None:
    db_path = tmp_path / "rates.db"
    _fixture(db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            DELETE FROM institution_funding_observations
            WHERE institution_id = 'koryo'
              AND metric_code = 'total_assets'
              AND source_effective_month = '2025-12'
            """
        )
        conn.commit()
    finally:
        conn.close()

    payload = build_size_peer_strategy_payload(db_path)

    assert payload["status"] == "unavailable"
    assert payload["reason"] == "anchor_financial_pair_missing"
    assert payload["modes"]["remote"]["display_rows"] == []
    assert payload["modes"]["branch_busan"]["display_rows"] == []
