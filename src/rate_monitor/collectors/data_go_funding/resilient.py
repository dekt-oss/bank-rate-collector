"""Data.go 기관별 수신잔액의 source/month checkpoint 수집 orchestration.

기존 collector의 파싱·identity·revision 계약은 재사용하되, 네트워크 요청 하나가
실패했다고 앞서 성공한 기준월의 raw evidence와 DB observation까지 잃지 않도록
기준월별 transaction으로 commit한다.

부분 commit은 곧 authoritative publish를 뜻하지 않는다. CLI는 필수 source에
미완료 기준월이 남으면 non-zero로 종료하며 R2 writer는 그대로 fail-closed다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from rate_monitor.collectors.data_go_funding.collector import (
    CONTRACTS,
    REQUEST_TIMEOUT,
    AccountSchema,
    FundingContractError,
    FundingSourceUnavailable,
    FundingTransportError,
    SourceContract,
    _discover_credit_union_endpoint,
    _ensure_source,
    _finish_run,
    _infer_credit_union_schema,
    _now,
    _service_key,
    _upsert_point,
    candidate_months,
    parse_points,
)
from rate_monitor.collectors.data_go_funding.transport import fetch_month as _fetch_month
from rate_monitor.db import models as m
from rate_monitor.db.session import create_db_engine, make_session_factory, session_scope
from rate_monitor.services.collection_service import save_raw_artifacts

RETRY_ROUNDS = 1


@dataclass(frozen=True)
class ResilientSourceResult:
    source_id: str
    sector: str
    required: bool
    status: str
    requested_months: tuple[str, ...]
    completed_months: tuple[str, ...]
    failed_months: tuple[str, ...]
    fetched_artifacts: int
    parsed_points: int
    stored: int
    unchanged: int
    revisions: int
    mapped: int
    unmapped: int
    retry_recovered_months: tuple[str, ...]
    message: str


@dataclass
class _Counters:
    fetched_artifacts: int = 0
    parsed_points: int = 0
    stored: int = 0
    unchanged: int = 0
    revisions: int = 0
    mapped: int = 0


def _client_timeout() -> float:
    raw = os.environ.get("DATA_GO_FUNDING_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return REQUEST_TIMEOUT
    try:
        value = float(raw)
    except ValueError as exc:
        raise FundingContractError(
            "DATA_GO_FUNDING_TIMEOUT_SECONDS는 숫자여야 한다"
        ) from exc
    if value < 5:
        raise FundingContractError(
            "DATA_GO_FUNDING_TIMEOUT_SECONDS는 5초 이상이어야 한다"
        )
    return value


def _validate_requested_month(rows: list[dict[str, Any]], bas_ym: str) -> None:
    """서버가 basYm filter를 무시하는 경우를 저장 전에 차단한다."""
    if not rows:
        return
    reported = {
        str(row.get("basYm") or "").strip()
        for row in rows
        if str(row.get("basYm") or "").strip()
    }
    if not reported:
        raise FundingContractError(
            f"Data.go 응답 row에 basYm이 없다: requested={bas_ym}"
        )
    if reported != {bas_ym}:
        sample = ",".join(sorted(reported)[:5])
        raise FundingContractError(
            "Data.go basYm 필터 계약 불일치: "
            f"requested={bas_ym} reported={sample}"
        )


def _new_run(
    factory: Any,
    contract: SourceContract,
    months: tuple[str, ...],
) -> str:
    now = _now()
    with session_scope(factory) as session:
        _ensure_source(session, contract, now)
        run = m.CollectionRun(
            source_id=contract.source_id,
            mode="api",
            started_at=now,
            status="running",
            query_context_json={
                "dataset_id": contract.dataset_id,
                "metric": "deposit_liabilities_total",
                "requested_months": list(months),
                "checkpoint_unit": "source_month",
                "retry_rounds": RETRY_ROUNDS,
            },
        )
        session.add(run)
        session.flush()
        return run.id


def _persist_month(
    *,
    factory: Any,
    run_id: str,
    contract: SourceContract,
    raw_root: Path,
    endpoint: str,
    bas_ym: str,
    rows: list[dict[str, Any]],
    artifacts: list[Any],
    schemas: tuple[AccountSchema, ...],
    counters: _Counters,
) -> None:
    _validate_requested_month(rows, bas_ym)
    points = (
        parse_points(
            contract,
            rows,
            endpoint=endpoint,
            account_schemas=schemas,
        )
        if rows
        else []
    )
    now = _now()
    with session_scope(factory) as session:
        run = session.get(m.CollectionRun, run_id)
        if run is None:
            raise FundingContractError(f"collection run이 없다: {run_id}")
        records = save_raw_artifacts(session, run, artifacts, raw_root, now)
        if points and not records:
            raise FundingContractError(
                f"{contract.source_id}/{bas_ym}: raw artifact provenance가 없다"
            )
        raw_id = records[0].id if records else None
        for point in points:
            if raw_id is None:
                raise FundingContractError(
                    f"{contract.source_id}/{bas_ym}: raw artifact id가 없다"
                )
            action, is_mapped = _upsert_point(
                session,
                point,
                raw_artifact_id=raw_id,
                now=now,
            )
            counters.mapped += int(is_mapped)
            if action == "stored":
                counters.stored += 1
            elif action == "revision":
                counters.revisions += 1
            else:
                counters.unchanged += 1

    counters.fetched_artifacts += len(artifacts)
    counters.parsed_points += len(points)


def _attempt_month(
    *,
    client: httpx.Client,
    factory: Any,
    run_id: str,
    contract: SourceContract,
    raw_root: Path,
    endpoint: str,
    key: str,
    bas_ym: str,
    schemas: tuple[AccountSchema, ...],
    counters: _Counters,
) -> tuple[tuple[AccountSchema, ...], str | None]:
    try:
        rows, artifacts = _fetch_month(
            client,
            contract=contract,
            endpoint=endpoint,
            key=key,
            bas_ym=bas_ym,
        )
        active_schemas = schemas
        if contract.sector == "cu" and rows and not active_schemas:
            active_schemas = _infer_credit_union_schema(rows)
        _persist_month(
            factory=factory,
            run_id=run_id,
            contract=contract,
            raw_root=raw_root,
            endpoint=endpoint,
            bas_ym=bas_ym,
            rows=rows,
            artifacts=artifacts,
            schemas=active_schemas,
            counters=counters,
        )
        return active_schemas, None
    except FundingTransportError as exc:
        return schemas, str(exc)


def collect_source_resilient(
    contract: SourceContract,
    *,
    db_path: Path,
    raw_root: Path,
    periods: int,
    required: bool,
) -> ResilientSourceResult:
    months = tuple(candidate_months(contract, periods))
    engine = create_db_engine(db_path)
    factory = make_session_factory(engine)
    run_id = _new_run(factory, contract, months)
    counters = _Counters()
    completed: list[str] = []
    retry_recovered: list[str] = []
    failures: dict[str, str] = {}
    endpoint = contract.finance_endpoint
    schemas = contract.account_schemas

    try:
        key = _service_key(contract)
        timeout = _client_timeout()
        with httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "bank-rate-collector/1 institution-funding"},
        ) as client:
            if endpoint is None:
                endpoint = _discover_credit_union_endpoint(client, key, months[0])

            for bas_ym in months:
                schemas, error = _attempt_month(
                    client=client,
                    factory=factory,
                    run_id=run_id,
                    contract=contract,
                    raw_root=raw_root,
                    endpoint=endpoint,
                    key=key,
                    bas_ym=bas_ym,
                    schemas=schemas,
                    counters=counters,
                )
                if error is None:
                    completed.append(bas_ym)
                else:
                    failures[bas_ym] = error

        for _round in range(RETRY_ROUNDS):
            if not failures:
                break
            pending = list(failures)
            with httpx.Client(
                timeout=timeout,
                follow_redirects=True,
                headers={"User-Agent": "bank-rate-collector/1 institution-funding"},
            ) as client:
                for bas_ym in pending:
                    schemas, error = _attempt_month(
                        client=client,
                        factory=factory,
                        run_id=run_id,
                        contract=contract,
                        raw_root=raw_root,
                        endpoint=endpoint,
                        key=key,
                        bas_ym=bas_ym,
                        schemas=schemas,
                        counters=counters,
                    )
                    if error is None:
                        completed.append(bas_ym)
                        retry_recovered.append(bas_ym)
                        failures.pop(bas_ym, None)
                    else:
                        failures[bas_ym] = error

        if failures:
            status = "partial"
            message = (
                f"source/month checkpoint partial: completed={len(completed)}/"
                f"{len(months)} failed={','.join(sorted(failures))}"
            )
        else:
            status = "success" if counters.parsed_points else "no_change"
            message = (
                f"source/month checkpoint complete: months={len(months)}; "
                f"artifacts={counters.fetched_artifacts}; "
                f"points={counters.parsed_points}; stored={counters.stored}; "
                f"revisions={counters.revisions}; unchanged={counters.unchanged}; "
                f"retry_recovered={len(retry_recovered)}"
            )
    except FundingSourceUnavailable as exc:
        status = "partial" if not required else "failed"
        failures = {month: str(exc) for month in months if month not in completed}
        message = str(exc)
    except FundingContractError as exc:
        status = "failed"
        failures = {
            month: str(exc)
            for month in months
            if month not in completed
        }
        message = str(exc)
    except Exception as exc:
        status = "failed"
        failures = {
            month: f"{type(exc).__name__}: {exc}"
            for month in months
            if month not in completed
        }
        message = f"{type(exc).__name__}: {exc}"

    _finish_run(
        factory,
        run_id,
        status,
        message,
        counters.fetched_artifacts,
        counters.parsed_points,
    )
    completed_set = set(completed)
    completed_sorted = tuple(month for month in months if month in completed_set)
    failed_sorted = tuple(month for month in months if month in failures)
    return ResilientSourceResult(
        source_id=contract.source_id,
        sector=contract.sector,
        required=required,
        status=status,
        requested_months=months,
        completed_months=completed_sorted,
        failed_months=failed_sorted,
        fetched_artifacts=counters.fetched_artifacts,
        parsed_points=counters.parsed_points,
        stored=counters.stored,
        unchanged=counters.unchanged,
        revisions=counters.revisions,
        mapped=counters.mapped,
        unmapped=max(0, counters.parsed_points - counters.mapped),
        retry_recovered_months=tuple(retry_recovered),
        message=message,
    )


def collect_all_resilient(
    *,
    db_path: Path,
    raw_root: Path,
    periods: int,
    require_credit_union: bool = False,
) -> list[ResilientSourceResult]:
    results: list[ResilientSourceResult] = []
    for contract in CONTRACTS:
        required = contract.sector != "cu" or require_credit_union
        results.append(
            collect_source_resilient(
                contract,
                db_path=db_path,
                raw_root=raw_root,
                periods=periods,
                required=required,
            )
        )
    return results


def required_failures(
    results: list[ResilientSourceResult],
) -> list[ResilientSourceResult]:
    return [
        result
        for result in results
        if result.required
        and (
            result.status not in {"success", "no_change"}
            or result.failed_months
            or result.completed_months != result.requested_months
        )
    ]
