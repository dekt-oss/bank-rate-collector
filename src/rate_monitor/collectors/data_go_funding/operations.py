"""Operational plans for institution-funding collection.

The source APIs expose historical reporting months through ``basYm``.  This
module separates one-time historical backfill from the recurring revision
watch so scheduled collection does not re-fetch the whole history every day.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

from rate_monitor.collectors.data_go_funding.collector import CONTRACTS
from rate_monitor.collectors.data_go_funding.resilient import (
    ResilientSourceResult,
    collect_source_resilient,
    required_failures,
)
from rate_monitor.db.institution_funding_models import InstitutionFundingObservation
from rate_monitor.db.session import create_db_engine, make_session_factory, session_scope

# Recurring revision-watch window.  This intentionally covers about one year
# of source reporting periods without re-downloading the entire history.
INCREMENTAL_PERIODS = {
    "savings_bank": 4,  # quarterly: 1 year
    "cu": 4,  # quarterly: 1 year
    "nh_local": 2,  # half-yearly: 1 year
}

# Initial historical backfill target.  Six years is enough to support YoY,
# multi-year trend and 12/24/36m response analysis while keeping the first
# authenticated run bounded.  If the source exposes more history, a later
# explicit deep-backfill can extend this without changing the data contract.
BACKFILL_PERIODS = {
    "savings_bank": 24,  # quarterly: 6 years
    "cu": 24,  # quarterly: 6 years
    "nh_local": 12,  # half-yearly: 6 years
}


def periods_for_mode(mode: str, sector: str, custom_periods: int = 12) -> int:
    """Return the number of source reporting periods to query."""
    if mode == "incremental":
        return INCREMENTAL_PERIODS[sector]
    if mode == "backfill":
        return BACKFILL_PERIODS[sector]
    if mode == "custom":
        if custom_periods < 1:
            raise ValueError("custom_periods는 1 이상이어야 한다")
        return custom_periods
    raise ValueError(f"지원하지 않는 collection mode: {mode}")


def collect_operational(
    *,
    db_path: Path,
    raw_root: Path,
    mode: str,
    custom_periods: int = 12,
    require_credit_union: bool = False,
) -> list[ResilientSourceResult]:
    """Collect all institution-funding sources using an operational plan."""
    results: list[ResilientSourceResult] = []
    for contract in CONTRACTS:
        required = contract.sector != "cu" or require_credit_union
        results.append(
            collect_source_resilient(
                contract,
                db_path=db_path,
                raw_root=raw_root,
                periods=periods_for_mode(mode, contract.sector, custom_periods),
                required=required,
            )
        )
    return results


def coverage_summary(db_path: Path) -> dict[str, Any]:
    """Summarize persisted active historical coverage by source."""
    engine = create_db_engine(db_path)
    factory = make_session_factory(engine)
    with session_scope(factory) as session:
        rows = session.execute(
            select(
                InstitutionFundingObservation.source_id,
                func.min(InstitutionFundingObservation.source_effective_month),
                func.max(InstitutionFundingObservation.source_effective_month),
                func.count(func.distinct(InstitutionFundingObservation.source_effective_month)),
                func.count(func.distinct(InstitutionFundingObservation.source_institution_key)),
                func.count(),
            )
            .where(InstitutionFundingObservation.valid_to.is_(None))
            .group_by(InstitutionFundingObservation.source_id)
            .order_by(InstitutionFundingObservation.source_id)
        ).all()

    return {
        "sources": [
            {
                "source_id": row[0],
                "earliest_month": row[1],
                "latest_month": row[2],
                "reporting_months": int(row[3] or 0),
                "institutions": int(row[4] or 0),
                "active_observations": int(row[5] or 0),
            }
            for row in rows
        ]
    }


def operational_payload(
    *,
    mode: str,
    results: list[ResilientSourceResult],
    db_path: Path,
) -> dict[str, Any]:
    """Build evidence payload for Actions artifacts and runtime review."""
    failures = required_failures(results)
    return {
        "mode": mode,
        "plan": {
            "incremental_periods": INCREMENTAL_PERIODS,
            "backfill_periods": BACKFILL_PERIODS,
        },
        "results": [asdict(result) for result in results],
        "required_failures": [result.source_id for result in failures],
        "coverage": coverage_summary(db_path),
    }
