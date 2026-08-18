"""Stage E0-5 — Deposit Pricing Engine 외부 feature bundle.

이미 수집 중인 한국은행 기준금리(`bok_ecos`)와 E0-3에서 추가한 수신시장
거시지표(`bok_ecos_macro`)를 하나의 read-only feature contract로 묶는다.

새 원천을 수집하지 않는다. 특히 은행채·CD·COFIX는 v1 feature에서 제외한다.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from rate_monitor.domain.timeutil import kst_iso
from rate_monitor.services.strategy_external_context_service import (
    build_strategy_external_context,
)

POLICY_SOURCE_ID = "bok_ecos"
POLICY_RATE_CODE = "bok_base_rate"
EXCLUDED_V1_FEATURES = ("bank_bond_rate", "cd_rate", "cofix")


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
            (table,),
        ).fetchone()
        is not None
    )


def _as_decimal(value: object) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _as_date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value or "").strip())
    except ValueError:
        return None


def _policy_rate(conn: sqlite3.Connection) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT indicator_code, indicator_name, value, unit,
               source_effective_at, observed_at, source_locator
        FROM market_indicators
        WHERE source_id = ?
          AND indicator_code = ?
          AND validation_status = 'valid'
          AND source_effective_at IS NOT NULL
        ORDER BY source_effective_at DESC, observed_at DESC
        LIMIT 1
        """,
        (POLICY_SOURCE_ID, POLICY_RATE_CODE),
    ).fetchone()
    if row is None:
        return {
            "indicator_code": POLICY_RATE_CODE,
            "status": "no_data",
            "value": None,
        }

    value = _as_decimal(row[2])
    effective = _as_date(row[4])
    if row[3] != "percent" or value is None or effective is None:
        return {
            "indicator_code": POLICY_RATE_CODE,
            "status": "source_contract_mismatch",
            "value": None,
        }
    return {
        "indicator_code": POLICY_RATE_CODE,
        "label": row[1],
        "status": "ready",
        "value": float(value),
        "unit": "percent",
        "source_effective_at": effective.isoformat(),
        "checked_at": kst_iso(row[5]),
        "source_locator": row[6],
    }


def build_deposit_pricing_external_features(
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Stage E v1이 사용할 외부 macro feature bundle을 만든다."""
    if not _table_exists(conn, "market_indicators"):
        return {
            "version": "deposit-pricing-external-features-v1",
            "status": "schema_unavailable",
            "policy_rate": {"status": "schema_unavailable", "value": None},
            "deposit_market": {
                "version": "strategy-external-context-v1",
                "status": "schema_unavailable",
                "bank_rates": {},
                "sector_balances": {},
            },
            "excluded_v1_features": list(EXCLUDED_V1_FEATURES),
        }

    policy = _policy_rate(conn)
    deposit_market = build_strategy_external_context(conn)
    statuses = (policy["status"], deposit_market["status"])
    if statuses == ("ready", "ready"):
        status = "ready"
    elif statuses == ("no_data", "no_data"):
        status = "no_data"
    else:
        status = "partial"

    return {
        "version": "deposit-pricing-external-features-v1",
        "status": status,
        "policy_rate": policy,
        "deposit_market": deposit_market,
        "feature_roles": {
            "policy_rate": "monetary_policy_regime_control",
            "primary_bank_realized_rate": "bank_deposit_market_price_control",
            "bank_12m_anchor": "twelve_month_competition_anchor",
            "sector_balance_mom": "sector_liquidity_flow_control",
        },
        "excluded_v1_features": list(EXCLUDED_V1_FEATURES),
    }
