"""Operational plans for institution-funding collection.

The source APIs expose historical reporting months through ``basYm``. This
module separates one-time historical backfill from the recurring revision
watch so scheduled collection does not re-fetch the whole history every day.

A bounded transport preflight runs before a source fan-out. Transient gateway
failures get a small number of fresh-client retries; hard 4xx rejections stop
immediately. This prevents one network wobble from discarding a required
source without recreating the old multi-hour per-month retry storm.
"""

from __future__ import annotations

import os
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import func, select

from rate_monitor.collectors.data_go_funding.aggregate_guard import (
    retire_validated_savings_bank_sector_totals,
)
from rate_monitor.collectors.data_go_funding.collector import (
    CONTRACTS,
    FundingSourceUnavailable,
    SourceContract,
    _service_key,
    candidate_months,
)
from rate_monitor.collectors.data_go_funding.resilient import (
    ResilientSourceResult,
    collect_source_resilient,
    required_failures,
)
from rate_monitor.collectors.data_go_funding.transport import (
    ACCOUNT_FILTERS,
    PAGE_SIZE,
    request_params,
)
from rate_monitor.db.institution_funding_models import InstitutionFundingObservation
from rate_monitor.db.session import create_db_engine, make_session_factory, session_scope

INCREMENTAL_PERIODS = {
    "savings_bank": 4,
    "cu": 4,
    "nh_local": 2,
}

BACKFILL_PERIODS = {
    "savings_bank": 24,
    "cu": 24,
    "nh_local": 12,
}

PREFLIGHT_TIMEOUT_SECONDS = 15.0
PREFLIGHT_ATTEMPTS = 3
PREFLIGHT_RETRY_DELAYS = (1.0, 3.0)


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


def _preflight_timeout() -> float:
    raw = os.environ.get("DATA_GO_FUNDING_PREFLIGHT_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return PREFLIGHT_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError("DATA_GO_FUNDING_PREFLIGHT_TIMEOUT_SECONDS는 숫자여야 한다") from exc
    if value < 5 or value > 30:
        raise ValueError("DATA_GO_FUNDING_PREFLIGHT_TIMEOUT_SECONDS는 5~30초여야 한다")
    return value


def _transport_preflight(contract: SourceContract) -> tuple[bool, str]:
    """Make bounded fresh-client attempts before expanding into many months."""
    if contract.finance_endpoint is None:
        return False, "exact finance endpoint 미확정; fan-out 생략"

    try:
        key = _service_key(contract)
    except FundingSourceUnavailable as exc:
        return False, str(exc)

    bas_ym = candidate_months(contract, 1)[0]
    params = request_params(
        contract,
        key=key,
        bas_ym=bas_ym,
        page_no=1,
        num_rows=1,
    )
    last_error = "unknown"
    for attempt in range(1, PREFLIGHT_ATTEMPTS + 1):
        if attempt > 1:
            time.sleep(PREFLIGHT_RETRY_DELAYS[attempt - 2])
        try:
            with httpx.Client(
                timeout=_preflight_timeout(),
                follow_redirects=True,
                headers={"User-Agent": "bank-rate-collector/1 institution-funding-preflight"},
            ) as client:
                response = client.get(contract.finance_endpoint, params=params)
        except httpx.TimeoutException as exc:
            last_error = f"timeout: {type(exc).__name__}"
            continue
        except httpx.HTTPError as exc:
            last_error = f"error: {type(exc).__name__}"
            continue

        if response.status_code >= 500:
            last_error = f"upstream status={response.status_code}"
            continue
        if response.status_code >= 400:
            return (
                False,
                f"transport preflight rejected status={response.status_code} "
                f"attempt={attempt}/{PREFLIGHT_ATTEMPTS}",
            )
        return (
            True,
            f"transport preflight ok status={response.status_code} basYm={bas_ym} "
            f"attempt={attempt}/{PREFLIGHT_ATTEMPTS}",
        )

    return (
        False,
        f"transport preflight retry exhausted attempts={PREFLIGHT_ATTEMPTS} "
        f"last={last_error}",
    )


def _preflight_result(
    contract: SourceContract,
    *,
    periods: int,
    required: bool,
    message: str,
) -> ResilientSourceResult:
    months = tuple(candidate_months(contract, periods))
    return ResilientSourceResult(
        source_id=contract.source_id,
        sector=contract.sector,
        required=required,
        status="failed" if required else "partial",
        requested_months=months,
        completed_months=(),
        failed_months=months,
        fetched_artifacts=0,
        parsed_points=0,
        stored=0,
        unchanged=0,
        revisions=0,
        mapped=0,
        unmapped=0,
        retry_recovered_months=(),
        message=message,
    )


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
        periods = periods_for_mode(mode, contract.sector, custom_periods)
        print(
            f"funding preflight source={contract.source_id} mode={mode} periods={periods}",
            flush=True,
        )
        reachable, preflight_message = _transport_preflight(contract)
        print(
            f"funding preflight source={contract.source_id} reachable={reachable} "
            f"detail={preflight_message}",
            flush=True,
        )
        if not reachable:
            results.append(
                _preflight_result(
                    contract,
                    periods=periods,
                    required=required,
                    message=preflight_message,
                )
            )
            continue

        result = collect_source_resilient(
            contract,
            db_path=db_path,
            raw_root=raw_root,
            periods=periods,
            required=required,
        )
        if contract.sector == "savings_bank" and result.status == "success":
            guard = retire_validated_savings_bank_sector_totals(db_path)
            print(
                "funding aggregate guard "
                f"source={contract.source_id} checked_months={guard.checked_months} "
                f"retired={guard.retired_observations}",
                flush=True,
            )
        results.append(result)
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
            "transport_preflight_seconds": _preflight_timeout(),
            "transport_preflight_attempts": PREFLIGHT_ATTEMPTS,
            "transport_preflight_retry_delays": PREFLIGHT_RETRY_DELAYS,
            "page_size": PAGE_SIZE,
            "account_filters": ACCOUNT_FILTERS,
        },
        "results": [asdict(result) for result in results],
        "required_failures": [result.source_id for result in failures],
        "coverage": coverage_summary(db_path),
    }
