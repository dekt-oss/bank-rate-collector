"""Stage E0-5 Deposit Pricing external feature bundle."""

from __future__ import annotations

import sqlite3

import rate_monitor.services.deposit_pricing_external_feature_service as service


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


def _policy_row(
    conn: sqlite3.Connection,
    *,
    source_id: str = "bok_ecos",
    value: str = "2.5000",
    unit: str = "percent",
    status: str = "valid",
) -> None:
    conn.execute(
        """
        INSERT INTO market_indicators VALUES
        ('bok_base_rate', '한국은행 기준금리', ?, '2026-08-18 03:00:00',
         '2026-07-10', ?, ?, '722Y001/0101000/20260710', ?)
        """,
        (source_id, value, unit, status),
    )


def test_existing_bok_base_rate_is_reused_without_new_source(monkeypatch) -> None:
    conn = _conn()
    _policy_row(conn)
    monkeypatch.setattr(
        service,
        "build_strategy_external_context",
        lambda conn: {"version": "strategy-external-context-v1", "status": "ready"},
    )

    result = service.build_deposit_pricing_external_features(conn)

    assert result["status"] == "ready"
    assert result["policy_rate"]["indicator_code"] == "bok_base_rate"
    assert result["policy_rate"]["value"] == 2.5
    assert result["policy_rate"]["source_effective_at"] == "2026-07-10"
    assert service.POLICY_SOURCE_ID == "bok_ecos"


def test_other_source_cannot_impersonate_policy_rate(monkeypatch) -> None:
    conn = _conn()
    _policy_row(conn, source_id="bok_ecos_macro", value="9.9999")
    monkeypatch.setattr(
        service,
        "build_strategy_external_context",
        lambda conn: {"version": "strategy-external-context-v1", "status": "ready"},
    )

    result = service.build_deposit_pricing_external_features(conn)

    assert result["status"] == "partial"
    assert result["policy_rate"] == {
        "indicator_code": "bok_base_rate",
        "status": "no_data",
        "value": None,
    }


def test_policy_source_contract_mismatch_fails_closed(monkeypatch) -> None:
    conn = _conn()
    _policy_row(conn, unit="trillion_krw")
    monkeypatch.setattr(
        service,
        "build_strategy_external_context",
        lambda conn: {"version": "strategy-external-context-v1", "status": "ready"},
    )

    result = service.build_deposit_pricing_external_features(conn)

    assert result["status"] == "partial"
    assert result["policy_rate"]["status"] == "source_contract_mismatch"
    assert result["policy_rate"]["value"] is None


def test_v1_excludes_wholesale_funding_variables_by_contract(monkeypatch) -> None:
    conn = _conn()
    _policy_row(conn)
    monkeypatch.setattr(
        service,
        "build_strategy_external_context",
        lambda conn: {"version": "strategy-external-context-v1", "status": "ready"},
    )

    result = service.build_deposit_pricing_external_features(conn)

    assert result["excluded_v1_features"] == ["bank_bond_rate", "cd_rate", "cofix"]
    assert result["feature_roles"] == {
        "policy_rate": "monetary_policy_regime_control",
        "primary_bank_realized_rate": "bank_deposit_market_price_control",
        "bank_12m_anchor": "twelve_month_competition_anchor",
        "sector_balance_mom": "sector_liquidity_flow_control",
    }


def test_missing_schema_is_explicit_and_never_becomes_zero() -> None:
    conn = sqlite3.connect(":memory:")

    result = service.build_deposit_pricing_external_features(conn)

    assert result["status"] == "schema_unavailable"
    assert result["policy_rate"]["value"] is None
    assert result["deposit_market"]["status"] == "schema_unavailable"
