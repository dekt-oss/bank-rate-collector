"""Stage E0-4 외부 수신시장 context read model."""

from __future__ import annotations

import sqlite3
from datetime import datetime

from rate_monitor.services.strategy_external_context_service import (
    build_strategy_external_context,
)


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE market_indicators (
            indicator_code TEXT NOT NULL,
            indicator_name TEXT NOT NULL,
            source_id TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            source_effective_at TEXT,
            value TEXT NOT NULL,
            unit TEXT NOT NULL,
            source_locator TEXT,
            validation_status TEXT NOT NULL DEFAULT 'valid'
        )
        """
    )
    return conn


def _insert(
    conn: sqlite3.Connection,
    code: str,
    effective: str,
    value: str,
    unit: str,
    *,
    source_id: str = "bok_ecos_macro",
) -> None:
    conn.execute(
        """
        INSERT INTO market_indicators (
            indicator_code, indicator_name, source_id, observed_at,
            source_effective_at, value, unit, source_locator, validation_status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'valid')
        """,
        (
            code,
            code,
            source_id,
            datetime(2026, 8, 18, 3, 0).isoformat(sep=" "),
            effective,
            value,
            unit,
            f"source/{code}/{effective}",
        ),
    )


def _insert_bank_rates(conn: sqlite3.Connection) -> None:
    _insert(conn, "bok_bank_pure_savings_deposit_rate", "2026-06-30", "3.0200", "percent")
    _insert(conn, "bok_bank_savings_deposit_rate", "2026-06-30", "3.0800", "percent")
    _insert(conn, "bok_bank_term_deposit_1y_rate", "2026-06-30", "3.2600", "percent")


def _insert_balances(conn: sqlite3.Connection) -> None:
    values = {
        "bok_savings_bank_deposit_balance": ("100.4487", "100.3558"),
        "bok_credit_union_deposit_balance": ("141.2654", "140.3664"),
        "bok_broad_mutual_finance_deposit_balance": ("522.1082", "519.4273"),
        "bok_kfcc_deposit_balance": ("243.7910", "243.2478"),
    }
    for code, (may, june) in values.items():
        _insert(conn, code, "2026-05-31", may, "trillion_krw")
        _insert(conn, code, "2026-06-30", june, "trillion_krw")


def test_verified_may_to_june_balances_derive_exact_mom_context() -> None:
    conn = _conn()
    _insert_bank_rates(conn)
    _insert_balances(conn)

    result = build_strategy_external_context(conn)

    assert result["status"] == "ready"
    assert result["primary_bank_rate_feature"] == "bok_bank_pure_savings_deposit_rate"
    assert result["bank_rates"]["primary_realized_deposit_rate"]["value"] == 3.02
    assert result["bank_rates"]["term_deposit_1y_rate"]["value"] == 3.26

    savings = result["sector_balances"]["savings_bank"]
    assert savings["status"] == "ready"
    assert savings["balance_trillion_krw"] == 100.3558
    assert savings["mom_change_trillion_krw"] == -0.0929
    assert savings["mom_change_pct"] == -0.0925
    assert savings["data_month"] == "2026-06"
    assert savings["previous_data_month"] == "2026-05"

    assert result["sector_balances"]["credit_union"]["mom_change_pct"] == -0.6364
    assert result["sector_balances"]["broad_mutual_finance"]["mom_change_pct"] == -0.5135
    assert result["sector_balances"]["kfcc"]["mom_change_pct"] == -0.2228


def test_broad_mutual_finance_is_explicitly_not_nh_local() -> None:
    conn = _conn()
    _insert_balances(conn)

    result = build_strategy_external_context(conn)
    broad = result["sector_balances"]["broad_mutual_finance"]

    assert broad["label"] == "광의 상호금융"
    assert broad["mapping_role"] == "broad_market_control_not_nh_local_1to1"
    assert "nh_local과 1:1 동일 업권이 아니다" in result["broad_mutual_finance_note"]


def test_non_consecutive_months_never_become_mom() -> None:
    conn = _conn()
    _insert(
        conn,
        "bok_savings_bank_deposit_balance",
        "2026-04-30",
        "100.6607",
        "trillion_krw",
    )
    _insert(
        conn,
        "bok_savings_bank_deposit_balance",
        "2026-06-30",
        "100.3558",
        "trillion_krw",
    )

    result = build_strategy_external_context(conn)
    savings = result["sector_balances"]["savings_bank"]

    assert savings["status"] == "non_consecutive_months"
    assert savings["mom_change_trillion_krw"] is None
    assert savings["mom_change_pct"] is None
    assert savings["previous_data_month"] == "2026-04"


def test_one_balance_point_is_visible_but_mom_is_insufficient_history() -> None:
    conn = _conn()
    _insert(
        conn,
        "bok_kfcc_deposit_balance",
        "2026-06-30",
        "243.2478",
        "trillion_krw",
    )

    result = build_strategy_external_context(conn)
    kfcc = result["sector_balances"]["kfcc"]

    assert kfcc["status"] == "insufficient_history"
    assert kfcc["balance_trillion_krw"] == 243.2478
    assert kfcc["mom_change_pct"] is None


def test_wrong_source_and_invalid_rows_are_not_used() -> None:
    conn = _conn()
    _insert(
        conn,
        "bok_bank_pure_savings_deposit_rate",
        "2026-06-30",
        "9.9900",
        "percent",
        source_id="other_source",
    )
    conn.execute(
        """
        INSERT INTO market_indicators VALUES
        ('bok_bank_pure_savings_deposit_rate', 'x', 'bok_ecos_macro',
         '2026-08-18 03:00:00', '2026-06-30', '9.8800', 'percent',
         'bad', 'error')
        """
    )

    result = build_strategy_external_context(conn)

    assert result["bank_rates"]["primary_realized_deposit_rate"]["status"] == "no_data"


def test_missing_table_fails_closed() -> None:
    conn = sqlite3.connect(":memory:")

    result = build_strategy_external_context(conn)

    assert result["status"] == "schema_unavailable"
    assert result["bank_rates"] == {}
    assert result["sector_balances"] == {}


def test_empty_table_is_no_data_not_zero() -> None:
    conn = _conn()

    result = build_strategy_external_context(conn)

    assert result["status"] == "no_data"
    assert result["sector_balances"]["savings_bank"]["balance_trillion_krw"] is None
    assert result["bank_rates"]["primary_realized_deposit_rate"]["value"] is None
