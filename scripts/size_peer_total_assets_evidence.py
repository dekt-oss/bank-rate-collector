#!/usr/bin/env python3
"""Authenticated read-only total-assets evidence probe for Strategy size peers.

The probe never opens or mutates the application database. It reads the existing
Data.go finance endpoints with repository secrets, finds the latest available
reporting period, parses the locked `A / 자산총계` contract, validates aggregate
hierarchy, and writes a sanitized JSON artifact.
"""

from __future__ import annotations

import json
import os
import urllib.parse
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx

from rate_monitor.collectors.data_go_funding.total_assets_evidence import (
    AGRI_COOP_SOURCE_ID,
    SAVINGS_BANK_SOURCE_ID,
    TotalAssetsEvidenceError,
    parse_total_assets_rows,
    partition_validated_total_assets,
)
from rate_monitor.domain.normalization import normalize_institution_name

OUT = Path("artifacts/size-peer-total-assets-evidence.json")
DATA_GO_BASE = "https://apis.data.go.kr/1160100/service"
PAGE_SIZE = 9999
MAX_PAGES = 20
TIMEOUT = 30.0
KORYO_CANONICAL_NAME = "고려저축은행"

SOURCES = {
    SAVINGS_BANK_SOURCE_ID: {
        "sector": "savings_bank",
        "key_env": "DATA_GO_KR_SERVICE_KEY_SB",
        "endpoint": (
            f"{DATA_GO_BASE}/GetMutuSaviBankInfoService/getMutuSaviBankFinaInfo"
        ),
        "cadence_months": (3, 6, 9, 12),
        "expected_aggregate_rows": 1,
    },
    AGRI_COOP_SOURCE_ID: {
        "sector": "nh_local",
        "key_env": "DATA_GO_KR_SERVICE_KEY_NH",
        "endpoint": f"{DATA_GO_BASE}/GetAgriCoopInfoService/getAgriCoopFinaInfo",
        "cadence_months": (6, 12),
        "expected_aggregate_rows": 17,
    },
}


def _service_key(env_name: str) -> str:
    raw = os.environ.get(env_name, "").strip()
    if not raw:
        raw = os.environ.get("DATA_GO_KR_SERVICE_KEY", "").strip()
    if not raw:
        raise RuntimeError(f"missing credential: {env_name}")
    return urllib.parse.unquote(raw)


def _candidate_months(cadence_months: tuple[int, ...], periods: int = 8) -> list[str]:
    today = datetime.now(UTC).date()
    result: list[str] = []
    year = today.year
    while len(result) < periods:
        for month in sorted(cadence_months, reverse=True):
            if year == today.year and month > today.month:
                continue
            result.append(f"{year:04d}{month:02d}")
            if len(result) == periods:
                return result
        year -= 1
    return result


def _flatten_items(value: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "item":
                if isinstance(child, dict):
                    rows.append(child)
                elif isinstance(child, list):
                    rows.extend(row for row in child if isinstance(row, dict))
            else:
                rows.extend(_flatten_items(child))
    elif isinstance(value, list):
        for child in value:
            rows.extend(_flatten_items(child))
    return rows


def _metadata_values(value: Any, key: str) -> list[Any]:
    found: list[Any] = []
    if isinstance(value, dict):
        for name, child in value.items():
            if name == key and not isinstance(child, (dict, list)):
                found.append(child)
            else:
                found.extend(_metadata_values(child, key))
    elif isinstance(value, list):
        for child in value:
            found.extend(_metadata_values(child, key))
    return found


def _accepted(payload: dict[str, Any]) -> bool:
    codes = {str(value) for value in _metadata_values(payload, "resultCode")}
    messages = " ".join(
        str(value) for value in _metadata_values(payload, "resultMsg")
    ).upper()
    return "00" in codes or "NORMAL SERVICE" in messages


def _total_count(payload: dict[str, Any]) -> int | None:
    values = _metadata_values(payload, "totalCount")
    for value in values:
        try:
            return int(str(value).strip())
        except ValueError:
            continue
    return None


def _request_page(
    client: httpx.Client,
    *,
    endpoint: str,
    key: str,
    bas_ym: str,
    page_no: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    response = client.get(
        endpoint,
        params={
            "serviceKey": key,
            "numOfRows": str(PAGE_SIZE),
            "pageNo": str(page_no),
            "resultType": "json",
            "basYm": bas_ym,
        },
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or not _accepted(payload):
        raise RuntimeError(
            f"Data.go accepted-response contract failed: basYm={bas_ym} page={page_no}"
        )
    return payload, _flatten_items(payload)


def _fetch_period_rows(
    client: httpx.Client,
    *,
    endpoint: str,
    key: str,
    bas_ym: str,
) -> list[dict[str, Any]]:
    first_payload, first_rows = _request_page(
        client,
        endpoint=endpoint,
        key=key,
        bas_ym=bas_ym,
        page_no=1,
    )
    if not first_rows:
        return []

    rows = list(first_rows)
    total_count = _total_count(first_payload)
    if total_count is None:
        return rows

    page_no = 2
    while len(rows) < total_count:
        if page_no > MAX_PAGES:
            raise RuntimeError(
                f"pagination exceeds MAX_PAGES: basYm={bas_ym} totalCount={total_count}"
            )
        _payload, page_rows = _request_page(
            client,
            endpoint=endpoint,
            key=key,
            bas_ym=bas_ym,
            page_no=page_no,
        )
        if not page_rows:
            raise RuntimeError(
                f"pagination ended early: basYm={bas_ym} rows={len(rows)} total={total_count}"
            )
        rows.extend(page_rows)
        page_no += 1
    return rows


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


def _probe_source(
    client: httpx.Client,
    *,
    source_id: str,
    config: dict[str, Any],
) -> dict[str, Any]:
    endpoint = str(config["endpoint"])
    key = _service_key(str(config["key_env"]))
    attempts: list[dict[str, Any]] = []

    for bas_ym in _candidate_months(tuple(config["cadence_months"])):
        try:
            rows = _fetch_period_rows(
                client,
                endpoint=endpoint,
                key=key,
                bas_ym=bas_ym,
            )
        except (httpx.HTTPError, RuntimeError, json.JSONDecodeError) as exc:
            attempts.append(
                {
                    "bas_ym": bas_ym,
                    "status": "transport_or_response_error",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            continue
        if not rows:
            attempts.append({"bas_ym": bas_ym, "status": "no_rows"})
            continue

        try:
            points = parse_total_assets_rows(
                source_id=source_id,
                rows=rows,
                endpoint=endpoint,
            )
            if not points:
                attempts.append(
                    {
                        "bas_ym": bas_ym,
                        "status": "rows_without_total_assets",
                        "raw_row_count": len(rows),
                    }
                )
                continue
            partitions = partition_validated_total_assets(points)
        except TotalAssetsEvidenceError as exc:
            return {
                "source_id": source_id,
                "sector": config["sector"],
                "status": "aggregate_validation_failed",
                "bas_ym": bas_ym,
                "raw_row_count": len(rows),
                "error": str(exc),
                "attempts": attempts,
            }

        if len(partitions) != 1:
            raise RuntimeError(
                f"expected one source/month partition: source={source_id} count={len(partitions)}"
            )
        partition = partitions[0]
        expected_aggregates = int(config["expected_aggregate_rows"])
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
            "source_id": source_id,
            "sector": config["sector"],
            "status": (
                "ready" if aggregate_status == "verified" else "insufficient_data"
            ),
            "source_effective_month": partition.source_effective_month,
            "raw_row_count": len(rows),
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

    return {
        "source_id": source_id,
        "sector": config["sector"],
        "status": "no_supported_period_found",
        "attempts": attempts,
    }


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as client:
        for source_id, config in SOURCES.items():
            result = _probe_source(client, source_id=source_id, config=config)
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
                "reason": "current-main Data.go exact finance contract not production-enabled; central disclosure evidence handled separately",
            },
            {
                "sector": "kfcc",
                "reason": "exact official total-assets request/field/institution-key contract not yet verified",
            },
        ],
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    failed = [row["source_id"] for row in results if row["status"] != "ready"]
    if failed:
        print("total-assets evidence gate failed: " + ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
