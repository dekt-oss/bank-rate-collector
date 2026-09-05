#!/usr/bin/env python3
"""Authenticated read-only total-assets evidence probe for Strategy size peers.

The probe never opens or mutates the application database. It reuses the
existing institution-funding Data.go request/pagination contract, finds the
latest available reporting period, validates `A / 자산총계`, and writes a
sanitized JSON artifact.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from rate_monitor.collectors.data_go_funding.collector import (
    CONTRACTS,
    REQUEST_TIMEOUT,
    FundingContractError,
    FundingSourceUnavailable,
    SourceContract,
    _fetch_month,
    _service_key,
    candidate_months,
)
from rate_monitor.collectors.data_go_funding.total_assets_evidence import (
    AGRI_COOP_SOURCE_ID,
    SAVINGS_BANK_SOURCE_ID,
    TotalAssetsEvidenceError,
    parse_total_assets_rows,
    partition_validated_total_assets,
)
from rate_monitor.domain.normalization import normalize_institution_name

OUT = Path("artifacts/size-peer-total-assets-evidence.json")
KORYO_CANONICAL_NAME = "고려저축은행"
PROBE_PERIODS = 8
EXPECTED_AGGREGATE_ROWS = {
    SAVINGS_BANK_SOURCE_ID: 1,
    AGRI_COOP_SOURCE_ID: 17,
}
PROBED_SOURCE_IDS = (SAVINGS_BANK_SOURCE_ID, AGRI_COOP_SOURCE_ID)


def _contract(source_id: str) -> SourceContract:
    matches = [contract for contract in CONTRACTS if contract.source_id == source_id]
    if len(matches) != 1:
        raise RuntimeError(
            f"expected one Data.go source contract: source={source_id} count={len(matches)}"
        )
    contract = matches[0]
    if not contract.finance_endpoint:
        raise RuntimeError(f"finance endpoint is not locked: source={source_id}")
    return contract


def _point_json(point: Any) -> dict[str, Any]:
    return {
        "source_institution_key": point.source_institution_key,
        "source_institution_name": point.source_institution_name,
        "source_crno": point.source_crno,
        "source_effective_month": point.source_effective_month,
        "source_value_text_krw": point.source_value_text,
        "value_million_krw": str(point.value),
        "population_scope": point.population_scope,
    }


def _validated_result(
    *,
    contract: SourceContract,
    bas_ym: str,
    raw_row_count: int,
    points: list[Any],
    attempts: list[dict[str, Any]],
) -> dict[str, Any]:
    partitions = partition_validated_total_assets(points)
    if len(partitions) != 1:
        raise RuntimeError(
            "expected one source/month total-assets partition: "
            f"source={contract.source_id} count={len(partitions)}"
        )
    partition = partitions[0]
    expected_aggregates = EXPECTED_AGGREGATE_ROWS[contract.source_id]
    aggregate_status = (
        "verified"
        if len(partition.aggregate_rows) == expected_aggregates
        else "unexpected_aggregate_count"
    )
    koryo_rows = [
        point
        for point in partition.institution_rows
        if normalize_institution_name(point.source_institution_name)
        == KORYO_CANONICAL_NAME
    ]
    return {
        "source_id": contract.source_id,
        "sector": contract.sector,
        "dataset_id": contract.dataset_id,
        "status": "ready" if aggregate_status == "verified" else "insufficient_data",
        "requested_bas_ym": bas_ym,
        "source_effective_month": partition.source_effective_month,
        "raw_row_count": raw_row_count,
        "total_assets_contract_row_count": len(points),
        "institution_row_count": len(partition.institution_rows),
        "unique_institution_key_count": len(
            {point.source_institution_key for point in partition.institution_rows}
        ),
        "aggregate_row_count": len(partition.aggregate_rows),
        "expected_aggregate_row_count": expected_aggregates,
        "aggregate_status": aggregate_status,
        "institution_total_million_krw": str(partition.institution_total),
        "aggregate_total_million_krw": (
            str(partition.aggregate_total)
            if partition.aggregate_total is not None
            else None
        ),
        "aggregate_rows": [_point_json(point) for point in partition.aggregate_rows],
        "koryo_rows": [_point_json(point) for point in koryo_rows],
        "institution_samples": [
            _point_json(point) for point in partition.institution_rows[:10]
        ],
        "attempts": attempts,
    }


def _probe_source(client: httpx.Client, contract: SourceContract) -> dict[str, Any]:
    endpoint = str(contract.finance_endpoint)
    key = _service_key(contract)
    attempts: list[dict[str, Any]] = []

    for bas_ym in candidate_months(contract, PROBE_PERIODS):
        try:
            rows, artifacts = _fetch_month(
                client,
                contract=contract,
                endpoint=endpoint,
                key=key,
                bas_ym=bas_ym,
            )
        except (httpx.HTTPError, FundingContractError, FundingSourceUnavailable) as exc:
            attempts.append(
                {
                    "bas_ym": bas_ym,
                    "status": "transport_or_response_error",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            continue
        if not rows:
            attempts.append(
                {
                    "bas_ym": bas_ym,
                    "status": "no_rows",
                    "fetched_pages": len(artifacts),
                }
            )
            continue

        try:
            points = parse_total_assets_rows(
                source_id=contract.source_id,
                rows=rows,
                endpoint=endpoint,
            )
            if not points:
                attempts.append(
                    {
                        "bas_ym": bas_ym,
                        "status": "rows_without_total_assets",
                        "raw_row_count": len(rows),
                        "fetched_pages": len(artifacts),
                    }
                )
                continue
            return _validated_result(
                contract=contract,
                bas_ym=bas_ym,
                raw_row_count=len(rows),
                points=points,
                attempts=attempts,
            )
        except TotalAssetsEvidenceError as exc:
            return {
                "source_id": contract.source_id,
                "sector": contract.sector,
                "dataset_id": contract.dataset_id,
                "status": "aggregate_validation_failed",
                "requested_bas_ym": bas_ym,
                "raw_row_count": len(rows),
                "error": str(exc),
                "attempts": attempts,
            }

    return {
        "source_id": contract.source_id,
        "sector": contract.sector,
        "dataset_id": contract.dataset_id,
        "status": "no_supported_period_found",
        "attempts": attempts,
    }


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    with httpx.Client(
        timeout=REQUEST_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": "bank-rate-collector/1 size-peer-total-assets-evidence"},
    ) as client:
        for source_id in PROBED_SOURCE_IDS:
            result = _probe_source(client, _contract(source_id))
            results.append(result)
            print(
                f"{source_id}: status={result['status']} "
                f"month={result.get('source_effective_month')} "
                f"institutions={result.get('institution_row_count')}"
            )

    report = {
        "mode": "authenticated_read_only_no_db_write",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "metric_code": "total_assets",
        "canonical_unit": "million_krw",
        "results": results,
        "not_yet_verified_sources": [
            {
                "sector": "cu",
                "reason": (
                    "current-main Data.go exact finance contract is not production-enabled; "
                    "central disclosure evidence is handled separately"
                ),
            },
            {
                "sector": "kfcc",
                "reason": (
                    "exact official total-assets request/field/institution-key contract "
                    "is not yet verified"
                ),
            },
        ],
    }
    OUT.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    failed = [row["source_id"] for row in results if row["status"] != "ready"]
    if failed:
        print("total-assets evidence gate failed: " + ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
