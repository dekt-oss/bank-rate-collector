"""Stage E0-4 — Strategy 외부 수신시장 context read model.

`bok_ecos_macro`가 저장한 월별 level을 read-only로 해석한다. signed MoM 변화율은
현재 `market_indicators.value` 저장계약에 맞지 않으므로 DB에 별도 저장하지 않고
여기서 연속 두 월의 level로 파생한다.

중요한 의미 경계:
- 예금은행 `순수저축성예금`을 Stage E v1의 primary realized deposit-rate feature로 쓴다.
- 1년 정기예금은 12M 보조 anchor다.
- BOK `상호금융`은 농협·수협·산림조합 단위조합을 포함하므로 `nh_local`과
  1:1 동일 업권으로 표현하지 않는다.
"""

from __future__ import annotations

import calendar
import sqlite3
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from rate_monitor.domain.timeutil import kst_iso

SOURCE_ID = "bok_ecos_macro"
PRIMARY_BANK_RATE = "bok_bank_pure_savings_deposit_rate"
HEADLINE_BANK_RATE = "bok_bank_savings_deposit_rate"
BANK_12M_ANCHOR = "bok_bank_term_deposit_1y_rate"

BANK_RATE_SPECS = (
    ("primary_realized_deposit_rate", PRIMARY_BANK_RATE, "순수저축성예금"),
    ("headline_savings_deposit_rate", HEADLINE_BANK_RATE, "저축성수신"),
    ("term_deposit_1y_rate", BANK_12M_ANCHOR, "1년 정기예금"),
)

BALANCE_SPECS = (
    (
        "savings_bank",
        "bok_savings_bank_deposit_balance",
        "상호저축은행",
        "direct_sector_control",
    ),
    (
        "credit_union",
        "bok_credit_union_deposit_balance",
        "신용협동조합",
        "direct_sector_control",
    ),
    (
        "broad_mutual_finance",
        "bok_broad_mutual_finance_deposit_balance",
        "광의 상호금융",
        "broad_market_control_not_nh_local_1to1",
    ),
    (
        "kfcc",
        "bok_kfcc_deposit_balance",
        "새마을금고",
        "direct_sector_control",
    ),
)


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
            (table,),
        ).fetchone()
        is not None
    )


def _rows(
    conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()
) -> list[dict[str, Any]]:
    cursor = conn.execute(sql, params)
    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def _as_date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _as_decimal(value: object) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _next_month_end(value: date) -> date:
    if value.month == 12:
        year, month = value.year + 1, 1
    else:
        year, month = value.year, value.month + 1
    return date(year, month, calendar.monthrange(year, month)[1])


def _month_key(value: date | None) -> str | None:
    return value.strftime("%Y-%m") if value else None


def _latest_rows(
    conn: sqlite3.Connection, indicator_code: str, limit: int
) -> list[dict[str, Any]]:
    return _rows(
        conn,
        """
        SELECT indicator_code, indicator_name, value, unit,
               source_effective_at, observed_at, source_locator
        FROM market_indicators
        WHERE source_id = ?
          AND indicator_code = ?
          AND validation_status = 'valid'
          AND source_effective_at IS NOT NULL
        ORDER BY source_effective_at DESC, observed_at DESC
        LIMIT ?
        """,
        (SOURCE_ID, indicator_code, limit),
    )


def _bank_rate_context(
    conn: sqlite3.Connection, output_key: str, indicator_code: str, label: str
) -> dict[str, Any]:
    rows = _latest_rows(conn, indicator_code, 1)
    if not rows:
        return {
            "key": output_key,
            "indicator_code": indicator_code,
            "label": label,
            "status": "no_data",
            "value": None,
        }
    row = rows[0]
    effective = _as_date(row["source_effective_at"])
    value = _as_decimal(row["value"])
    if row.get("unit") != "percent" or effective is None or value is None:
        return {
            "key": output_key,
            "indicator_code": indicator_code,
            "label": label,
            "status": "source_contract_mismatch",
            "value": None,
        }
    return {
        "key": output_key,
        "indicator_code": indicator_code,
        "label": label,
        "status": "ready",
        "value": float(value),
        "unit": "percent",
        "source_effective_at": effective.isoformat(),
        "data_month": _month_key(effective),
        "checked_at": kst_iso(row.get("observed_at")),
        "source_locator": row.get("source_locator"),
    }


def _balance_context(
    conn: sqlite3.Connection,
    key: str,
    indicator_code: str,
    label: str,
    mapping_role: str,
) -> dict[str, Any]:
    rows = _latest_rows(conn, indicator_code, 2)
    base: dict[str, Any] = {
        "key": key,
        "indicator_code": indicator_code,
        "label": label,
        "mapping_role": mapping_role,
        "unit": "trillion_krw",
        "status": "no_data",
        "balance_trillion_krw": None,
        "mom_change_trillion_krw": None,
        "mom_change_pct": None,
    }
    if not rows:
        return base

    current = rows[0]
    current_date = _as_date(current["source_effective_at"])
    current_value = _as_decimal(current["value"])
    if current.get("unit") != "trillion_krw" or current_date is None or current_value is None:
        return {**base, "status": "source_contract_mismatch"}

    result = {
        **base,
        "status": "insufficient_history",
        "balance_trillion_krw": float(current_value),
        "source_effective_at": current_date.isoformat(),
        "data_month": _month_key(current_date),
        "checked_at": kst_iso(current.get("observed_at")),
        "source_locator": current.get("source_locator"),
    }
    if len(rows) < 2:
        return result

    previous = rows[1]
    previous_date = _as_date(previous["source_effective_at"])
    previous_value = _as_decimal(previous["value"])
    if previous.get("unit") != "trillion_krw" or previous_date is None or previous_value is None:
        return {**result, "status": "source_contract_mismatch"}

    result["previous_balance_trillion_krw"] = float(previous_value)
    result["previous_source_effective_at"] = previous_date.isoformat()
    result["previous_data_month"] = _month_key(previous_date)
    if _next_month_end(previous_date) != current_date:
        return {**result, "status": "non_consecutive_months"}
    if previous_value <= 0:
        return {**result, "status": "invalid_previous_balance"}

    delta = current_value - previous_value
    pct = delta / previous_value * Decimal("100")
    return {
        **result,
        "status": "ready",
        "mom_change_trillion_krw": float(delta.quantize(Decimal("0.0001"))),
        "mom_change_pct": float(pct.quantize(Decimal("0.0001"))),
    }


def build_strategy_external_context(conn: sqlite3.Connection) -> dict[str, Any]:
    """월별 BOK 수신시장 context를 fail-closed read model로 만든다."""
    if not _table_exists(conn, "market_indicators"):
        return {
            "version": "strategy-external-context-v1",
            "status": "schema_unavailable",
            "bank_rates": {},
            "sector_balances": {},
        }

    bank_rates = {
        output_key: _bank_rate_context(conn, output_key, indicator_code, label)
        for output_key, indicator_code, label in BANK_RATE_SPECS
    }
    sector_balances = {
        key: _balance_context(conn, key, indicator_code, label, mapping_role)
        for key, indicator_code, label, mapping_role in BALANCE_SPECS
    }
    statuses = [item["status"] for item in bank_rates.values()] + [
        item["status"] for item in sector_balances.values()
    ]
    if all(status == "no_data" for status in statuses):
        status = "no_data"
    elif all(status == "ready" for status in statuses):
        status = "ready"
    else:
        status = "partial"

    return {
        "version": "strategy-external-context-v1",
        "status": status,
        "source_id": SOURCE_ID,
        "primary_bank_rate_feature": PRIMARY_BANK_RATE,
        "bank_12m_anchor": BANK_12M_ANCHOR,
        "sector_flow_derivation": "consecutive_month_end_balance_levels",
        "broad_mutual_finance_note": (
            "BOK 상호금융은 농협·수협·산림조합 단위조합을 포함하며 "
            "nh_local과 1:1 동일 업권이 아니다."
        ),
        "bank_rates": bank_rates,
        "sector_balances": sector_balances,
    }
