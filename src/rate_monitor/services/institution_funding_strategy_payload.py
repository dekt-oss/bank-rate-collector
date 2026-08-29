"""Strategy L3 payload for institution funding relative metrics."""

from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from typing import Any

from rate_monitor.services.institution_funding_read_model_db import (
    build_institution_funding_read_model_from_db,
)


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def build_institution_funding_strategy_payload(
    db_path: Path,
    *,
    sector: str,
    analysis_month: str,
    eligible_institutions: int | None = None,
) -> dict[str, Any]:
    """Build a JSON-safe L3 payload without inventing unavailable coverage data."""
    rows = build_institution_funding_read_model_from_db(
        db_path,
        sector=sector,
        analysis_month=analysis_month,
    )
    observed = len(rows)
    coverage_ratio = (
        Decimal(observed) / Decimal(eligible_institutions)
        if eligible_institutions and eligible_institutions > 0
        else None
    )
    growth_6m_available = sum(row.change_6m_pct is not None for row in rows)
    growth_12m_available = sum(row.change_12m_pct is not None for row in rows)

    return _json_value(
        {
            "sector": sector,
            "analysis_month": analysis_month,
            "coverage": {
                "eligible_institutions": eligible_institutions,
                "observed_institutions": observed,
                "coverage_ratio": coverage_ratio,
                "status": "measured" if coverage_ratio is not None else "denominator_unknown",
            },
            "availability": {
                "growth_6m_institutions": growth_6m_available,
                "growth_12m_institutions": growth_12m_available,
            },
            "rows": [asdict(row) for row in rows],
        }
    )
