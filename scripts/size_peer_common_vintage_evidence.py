#!/usr/bin/env python3
"""Read-only common-vintage two-axis evidence for Strategy size peers.

The script restores nothing and writes nothing by itself beyond its JSON report.
Its workflow supplies a runner-local production database copy. Official
Data.go.kr finance payloads are fetched read-only for the same reporting month
as production funding observations. No nearest-month alignment is allowed.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from contextlib import closing
from datetime import UTC, datetime
from decimal import Decimal
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
)
from rate_monitor.collectors.data_go_funding.total_assets_evidence import (
    AGRI_COOP_SOURCE_ID,
    SAVINGS_BANK_SOURCE_ID,
    TotalAssetsEvidenceError,
    parse_total_assets_rows,
    partition_validated_total_assets,
)
from rate_monitor.domain.normalization import normalize_institution_name
from rate_monitor.services.institution_funding_read_model_db import (
    FUNDING_METRIC_CODE,
    VERIFIED_IDENTITY_STATUSES,
)
from rate_monitor.services.size_peer_two_axis import (
    AssetsAxisEvidence,
    FundingAxisEvidence,
    SizePeerTwoAxisError,
    build_two_axis_distribution,
    common_reporting_month_candidates,
)

DEFAULT_OUT = Path("artifacts/size-peer-common-vintage-evidence.json")
REQUIRED_SOURCE_IDS = (SAVINGS_BANK_SOURCE_ID, AGRI_COOP_SOURCE_ID)
# Probe the slower / less frequent source first. If NH has no row for a month,
# there is no reason to download the savings-bank payload for that month.
ASSET_PROBE_ORDER = (AGRI_COOP_SOURCE_ID, SAVINGS_BANK_SOURCE_ID)
KORYO_SOURCE_KEY = "0010390"
KORYO_CANONICAL_NAME = "고려저축은행"
MAX_COMMON_MONTH_CANDIDATES = 12


def _open_immutable(db_path: Path) -> sqlite3.Connection:
    uri = db_path.resolve().as_uri() + "?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    return connection


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


def _funding_month_inventory(
    db_path: Path,
) -> tuple[dict[str, tuple[str, ...]], dict[str, list[dict[str, Any]]]]:
    placeholders = ",".join("?" for _ in REQUIRED_SOURCE_IDS)
    with closing(_open_immutable(db_path)) as connection:
        rows = connection.execute(
            f"""
            SELECT source_id,
                   sector,
                   source_effective_month,
                   institution_id,
                   identity_status
            FROM institution_funding_observations
            WHERE valid_to IS NULL
              AND metric_code = ?
              AND source_id IN ({placeholders})
            ORDER BY source_id, source_effective_month, source_institution_key
            """,
            (FUNDING_METRIC_CODE, *REQUIRED_SOURCE_IDS),
        ).fetchall()

    grouped: dict[tuple[str, str, str], dict[str, int]] = {}
    for row in rows:
        key = (
            str(row["source_id"]),
            str(row["sector"]),
            str(row["source_effective_month"]),
        )
        bucket = grouped.setdefault(key, {"rows": 0, "exact_mapped": 0})
        bucket["rows"] += 1
        if (
            row["institution_id"] is not None
            and str(row["identity_status"]) in VERIFIED_IDENTITY_STATUSES
        ):
            bucket["exact_mapped"] += 1

    months_by_source: dict[str, tuple[str, ...]] = {}
    inventory: dict[str, list[dict[str, Any]]] = {}
    for source_id in REQUIRED_SOURCE_IDS:
        source_rows = [
            (key, counts)
            for key, counts in grouped.items()
            if key[0] == source_id
        ]
        months = tuple(sorted({key[2] for key, _counts in source_rows}, reverse=True))
        months_by_source[source_id] = months
        inventory[source_id] = [
            {
                "sector": key[1],
                "source_effective_month": key[2],
                "row_count": counts["rows"],
                "exact_mapped_count": counts["exact_mapped"],
                "not_exact_mapped_count": counts["rows"] - counts["exact_mapped"],
            }
            for key, counts in sorted(
                source_rows,
                key=lambda item: item[0][2],
                reverse=True,
            )
        ]
    return months_by_source, inventory


def _fetch_assets_exact_month(
    client: httpx.Client,
    *,
    source_id: str,
    month: str,
) -> tuple[list[AssetsAxisEvidence] | None, dict[str, Any]]:
    contract = _contract(source_id)
    endpoint = str(contract.finance_endpoint)
    bas_ym = month.replace("-", "")
    rows, artifacts = _fetch_month(
        client,
        contract=contract,
        endpoint=endpoint,
        key=_service_key(contract),
        bas_ym=bas_ym,
    )
    if not rows:
        return None, {
            "source_id": source_id,
            "sector": contract.sector,
            "source_effective_month": month,
            "status": "no_rows",
            "fetched_pages": len(artifacts),
        }

    points = parse_total_assets_rows(
        source_id=source_id,
        rows=rows,
        endpoint=endpoint,
    )
    if not points:
        return None, {
            "source_id": source_id,
            "sector": contract.sector,
            "source_effective_month": month,
            "status": "rows_without_total_assets",
            "raw_row_count": len(rows),
            "fetched_pages": len(artifacts),
        }

    partitions = partition_validated_total_assets(points)
    if len(partitions) != 1:
        raise SizePeerTwoAxisError(
            "expected one asset source/month partition: "
            f"source={source_id} month={month} count={len(partitions)}"
        )
    partition = partitions[0]
    if partition.source_effective_month != month:
        raise SizePeerTwoAxisError(
            "asset source returned a different reporting month: "
            f"source={source_id} requested={month} actual={partition.source_effective_month}"
        )

    evidence = [
        AssetsAxisEvidence(
            source_id=point.source_id,
            sector=point.sector,
            source_institution_key=point.source_institution_key,
            source_institution_name=point.source_institution_name,
            source_crno=point.source_crno,
            source_effective_month=point.source_effective_month,
            value=point.value,
        )
        for point in partition.institution_rows
    ]
    summary = {
        "source_id": source_id,
        "sector": contract.sector,
        "source_effective_month": month,
        "status": "ready",
        "raw_row_count": len(rows),
        "fetched_pages": len(artifacts),
        "asset_contract_row_count": len(points),
        "institution_row_count": len(partition.institution_rows),
        "aggregate_row_count": len(partition.aggregate_rows),
        "institution_total_million_krw": str(partition.institution_total),
        "aggregate_total_million_krw": (
            str(partition.aggregate_total)
            if partition.aggregate_total is not None
            else None
        ),
    }
    return evidence, summary


def _select_common_asset_month(
    months: tuple[str, ...],
) -> tuple[str | None, list[AssetsAxisEvidence], list[dict[str, Any]], list[dict[str, Any]]]:
    attempts: list[dict[str, Any]] = []
    selected_summaries: list[dict[str, Any]] = []

    with httpx.Client(
        timeout=REQUEST_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": "bank-rate-collector/1 size-peer-common-vintage"},
    ) as client:
        for month in months[:MAX_COMMON_MONTH_CANDIDATES]:
            month_assets: list[AssetsAxisEvidence] = []
            month_summaries: list[dict[str, Any]] = []
            unavailable = False

            for source_id in ASSET_PROBE_ORDER:
                try:
                    points, summary = _fetch_assets_exact_month(
                        client,
                        source_id=source_id,
                        month=month,
                    )
                except (
                    httpx.HTTPError,
                    FundingContractError,
                    FundingSourceUnavailable,
                    TotalAssetsEvidenceError,
                    SizePeerTwoAxisError,
                ) as exc:
                    raise RuntimeError(
                        "common-vintage asset source validation failed: "
                        f"source={source_id} month={month} error={type(exc).__name__}"
                    ) from exc

                month_summaries.append(summary)
                if points is None:
                    unavailable = True
                    break
                month_assets.extend(points)

            attempts.append(
                {
                    "source_effective_month": month,
                    "status": "unavailable" if unavailable else "ready",
                    "sources": month_summaries,
                }
            )
            if not unavailable:
                selected_summaries = month_summaries
                return month, month_assets, attempts, selected_summaries

    return None, [], attempts, selected_summaries


def _load_funding_points(
    db_path: Path,
    *,
    month: str,
) -> tuple[list[FundingAxisEvidence], dict[str, dict[str, int]]]:
    placeholders = ",".join("?" for _ in REQUIRED_SOURCE_IDS)
    with closing(_open_immutable(db_path)) as connection:
        rows = connection.execute(
            f"""
            SELECT o.source_id,
                   o.sector,
                   o.source_institution_key,
                   o.source_institution_name,
                   o.source_crno,
                   o.institution_id,
                   o.identity_status,
                   o.source_effective_month,
                   o.value,
                   i.canonical_name
            FROM institution_funding_observations o
            LEFT JOIN institutions i ON i.id = o.institution_id
            WHERE o.valid_to IS NULL
              AND o.metric_code = ?
              AND o.source_effective_month = ?
              AND o.source_id IN ({placeholders})
            ORDER BY o.source_id, o.source_institution_key
            """,
            (FUNDING_METRIC_CODE, month, *REQUIRED_SOURCE_IDS),
        ).fetchall()

    points = [
        FundingAxisEvidence(
            source_id=str(row["source_id"]),
            sector=str(row["sector"]),
            source_institution_key=str(row["source_institution_key"]),
            source_institution_name=str(row["source_institution_name"]),
            source_crno=str(row["source_crno"]) if row["source_crno"] else None,
            institution_id=str(row["institution_id"]) if row["institution_id"] else None,
            canonical_name=str(row["canonical_name"]) if row["canonical_name"] else None,
            identity_status=str(row["identity_status"]),
            source_effective_month=str(row["source_effective_month"]),
            value=Decimal(str(row["value"])),
        )
        for row in rows
    ]

    summary: dict[str, dict[str, int]] = {}
    for source_id in REQUIRED_SOURCE_IDS:
        selected = [point for point in points if point.source_id == source_id]
        exact = [
            point
            for point in selected
            if point.institution_id
            and point.identity_status in VERIFIED_IDENTITY_STATUSES
        ]
        summary[source_id] = {
            "row_count": len(selected),
            "exact_mapped_count": len(exact),
            "not_exact_mapped_count": len(selected) - len(exact),
            "unique_source_key_count": len(
                {point.source_institution_key for point in selected}
            ),
        }
    return points, summary


def _candidate_json(candidate: Any) -> dict[str, Any]:
    return {
        "institution_id": candidate.institution_id,
        "canonical_name": candidate.canonical_name,
        "source_id": candidate.source_id,
        "sector": candidate.sector,
        "source_institution_key": candidate.source_institution_key,
        "source_institution_name": candidate.source_institution_name,
        "source_crno": candidate.source_crno,
        "source_effective_month": candidate.source_effective_month,
        "deposit_liabilities_total_million_krw": str(
            candidate.deposit_liabilities_total
        ),
        "total_assets_million_krw": str(candidate.total_assets),
    }


def _missing_json(item: Any) -> dict[str, Any]:
    return {
        "source_id": item.source_id,
        "sector": item.sector,
        "source_institution_key": item.source_institution_key,
        "source_institution_name": item.source_institution_name,
        "source_effective_month": item.source_effective_month,
        "reason": item.reason,
    }


def _count_by_sector(candidates: list[Any] | tuple[Any, ...]) -> dict[str, int]:
    return dict(sorted(Counter(candidate.sector for candidate in candidates).items()))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    db_path: Path = args.db_path
    out: Path = args.out
    if not db_path.is_file() or db_path.stat().st_size == 0:
        raise SystemExit(f"runner-local production DB is missing: {db_path}")

    months_by_source, funding_inventory = _funding_month_inventory(db_path)
    common_funding_months = common_reporting_month_candidates(
        months_by_source,
        required_source_ids=REQUIRED_SOURCE_IDS,
    )

    selected_month, asset_points, asset_attempts, asset_summaries = (
        _select_common_asset_month(common_funding_months)
    )
    if selected_month is None:
        report = {
            "status": "temporal_alignment_unresolved",
            "mode": "runner_local_production_db_plus_official_source_read_only",
            "generated_at_utc": datetime.now(UTC).isoformat(),
            "funding_month_inventory": funding_inventory,
            "common_funding_month_candidates": list(common_funding_months),
            "asset_month_attempts": asset_attempts,
            "similarity_selection_enabled": False,
            "persistence_enabled": False,
        }
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print("no exact common funding/assets month was verified")
        return 1

    funding_points, funding_selected_summary = _load_funding_points(
        db_path,
        month=selected_month,
    )
    distribution = build_two_axis_distribution(
        funding_points,
        asset_points,
        source_effective_month=selected_month,
    )

    anchor = [
        candidate
        for candidate in distribution.candidates
        if candidate.source_id == SAVINGS_BANK_SOURCE_ID
        and candidate.source_institution_key == KORYO_SOURCE_KEY
    ]
    anchor_ok = (
        len(anchor) == 1
        and normalize_institution_name(anchor[0].canonical_name)
        == KORYO_CANONICAL_NAME
    )

    report = {
        "status": (
            "ready_for_similarity_policy_evidence"
            if distribution.evidence_ready and anchor_ok
            else "insufficient_data"
        ),
        "mode": "runner_local_production_db_plus_official_source_read_only",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "policy_id": distribution.policy_id,
        "policy_version": distribution.policy_version,
        "funding_metric_code": FUNDING_METRIC_CODE,
        "assets_metric_code": "total_assets",
        "canonical_unit": "million_krw",
        "required_source_ids": list(REQUIRED_SOURCE_IDS),
        "funding_month_inventory": funding_inventory,
        "common_funding_month_candidates": list(common_funding_months),
        "selected_common_month": selected_month,
        "asset_month_attempts": asset_attempts,
        "selected_asset_source_summaries": asset_summaries,
        "selected_funding_source_summaries": funding_selected_summary,
        "distribution": {
            "candidate_count": len(distribution.candidates),
            "candidate_count_by_sector": _count_by_sector(distribution.candidates),
            "fatal_conflict_count": distribution.fatal_conflict_count,
            "missing_reason_counts": dict(distribution.missing_reason_counts),
            "candidates": [
                _candidate_json(candidate) for candidate in distribution.candidates
            ],
            "missing": [_missing_json(item) for item in distribution.missing],
        },
        "anchor": _candidate_json(anchor[0]) if anchor_ok else None,
        "anchor_status": "verified" if anchor_ok else "missing_or_identity_mismatch",
        "eligibility_universe_applied": False,
        "similarity_selection_enabled": False,
        "persistence_enabled": False,
        "remaining_gates": [
            "apply REMOTE / BRANCH_BUSAN eligibility evidence to the two-axis population",
            "evaluate transparent two-axis similarity rules on this real distribution",
            "verify CU/KFCC total-assets source contracts before cross-sector inclusion",
        ],
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(
        "common-vintage evidence "
        f"month={selected_month} candidates={len(distribution.candidates)} "
        f"missing={len(distribution.missing)} fatal={distribution.fatal_conflict_count} "
        f"anchor={'ok' if anchor_ok else 'missing'}"
    )
    if not distribution.evidence_ready or not anchor_ok:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
