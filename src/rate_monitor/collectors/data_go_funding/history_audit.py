"""Continuity audit for persisted institution-funding history."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from rate_monitor.collectors.data_go_funding.collector import CONTRACTS
from rate_monitor.collectors.data_go_funding.history import historical_months, shift_month


def _compact(month: str) -> str:
    return month.replace("-", "")


def _display(month: str) -> str:
    key = _compact(month)
    return f"{key[:4]}-{key[4:]}"


def build_history_audit(
    db_path: Path,
    *,
    windows: tuple[int, ...] = (24, 36),
) -> dict[str, Any]:
    """Audit expected reporting-month continuity without inventing missing values."""
    if any(window < 1 for window in windows):
        raise ValueError("audit window는 1개월 이상이어야 한다")

    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='institution_funding_observations'"
        ).fetchone()
        if exists is None:
            return {
                "available": False,
                "reason": "institution_funding_observations table missing",
                "sources": {},
            }

        sources: dict[str, Any] = {}
        for contract in CONTRACTS:
            rows = connection.execute(
                "SELECT source_effective_month, COUNT(*) AS active_rows, "
                "COUNT(DISTINCT source_institution_key) AS institutions "
                "FROM institution_funding_observations "
                "WHERE source_id=? AND valid_to IS NULL "
                "GROUP BY source_effective_month ORDER BY source_effective_month",
                (contract.source_id,),
            ).fetchall()
            months = [row["source_effective_month"] for row in rows]
            duplicate_active_keys = connection.execute(
                "SELECT COUNT(*) FROM ("
                "SELECT source_institution_key, metric_code, source_effective_month "
                "FROM institution_funding_observations "
                "WHERE source_id=? AND valid_to IS NULL "
                "GROUP BY source_institution_key, metric_code, source_effective_month "
                "HAVING COUNT(*) > 1)",
                (contract.source_id,),
            ).fetchone()[0]
            revision_rows = connection.execute(
                "SELECT COUNT(*) FROM institution_funding_observations "
                "WHERE source_id=? AND revision > 1",
                (contract.source_id,),
            ).fetchone()[0]
            identity_rows = connection.execute(
                "SELECT identity_status, COUNT(*) AS n "
                "FROM institution_funding_observations "
                "WHERE source_id=? AND valid_to IS NULL "
                "GROUP BY identity_status ORDER BY identity_status",
                (contract.source_id,),
            ).fetchall()

            payload: dict[str, Any] = {
                "sector": contract.sector,
                "cadence_months": list(contract.cadence_months),
                "available": bool(rows),
                "earliest_month": months[0] if months else None,
                "latest_month": months[-1] if months else None,
                "observed_reporting_months": len(months),
                "active_rows": sum(int(row["active_rows"]) for row in rows),
                "latest_institutions": int(rows[-1]["institutions"]) if rows else 0,
                "duplicate_active_keys": int(duplicate_active_keys),
                "revision_rows": int(revision_rows),
                "identity_status_counts": {
                    row["identity_status"]: int(row["n"]) for row in identity_rows
                },
                "continuity": {},
            }
            if months:
                latest = _compact(months[-1])
                observed = {_compact(month) for month in months}
                for window in windows:
                    start = shift_month(latest, -(window - 1))
                    expected = historical_months(contract, start, latest)
                    payload["continuity"][f"{window}m"] = {
                        "start_month": _display(start),
                        "end_month": _display(latest),
                        "expected_reporting_months": len(expected),
                        "observed_reporting_months": sum(
                            month in observed for month in expected
                        ),
                        "missing_months": [
                            _display(month) for month in expected if month not in observed
                        ],
                    }
            sources[contract.source_id] = payload

        return {
            "available": True,
            "windows_months": list(windows),
            "sources": sources,
        }
    finally:
        connection.close()
