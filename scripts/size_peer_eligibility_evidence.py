#!/usr/bin/env python3
"""Build current REMOTE / BRANCH_BUSAN eligibility evidence for size peers.

The financial axes remain at their exact historical common vintage. This script
only overlays current selected-product availability evidence and measures the
resulting distance population. It never persists or selects production peers.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
from collections import Counter, defaultdict
from contextlib import closing
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx

from rate_monitor.collectors.fsb import parser as fsb_parser
from rate_monitor.collectors.fsb.adapter import (
    BASE_URL,
    CONNECT_TIMEOUT,
    READ_TIMEOUT,
    REQUEST_INTERVAL_SECONDS,
    SCREENS,
    USER_AGENT,
    FsbAdapter,
)
from rate_monitor.domain.timeutil import now_kst
from rate_monitor.services.fsb_availability_service import _fetch_area_rows
from rate_monitor.services.region_service import BUSAN_DISTRICTS
from rate_monitor.services.size_peer_current_eligibility import (
    EligibilityEvidenceFact,
    TwoAxisFinancialCandidate,
    apply_current_eligibility,
    exclusion_reason_counts,
    relative_gap_distribution,
    threshold_counts,
)
from rate_monitor.services.size_peer_universe import SAVINGS_BANK

TERM_MONTHS_DEFAULT = 12
FSB_SOURCE_ID = "fsb"
NH_SOURCE_ID = "nh_local"
NH_SECTOR = "nh_local"
FSB_BUSAN_AREA = "YN_Busan"
THRESHOLDS = tuple(
    Decimal(value)
    for value in ("0.02", "0.05", "0.075", "0.10", "0.15", "0.20")
)


def _open_immutable(db_path: Path) -> sqlite3.Connection:
    uri = db_path.resolve().as_uri() + "?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _load_financial_candidates(
    path: Path,
) -> tuple[str, list[TwoAxisFinancialCandidate], str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("status") != "ready_for_similarity_policy_evidence":
        raise RuntimeError("common-vintage artifact is not ready")
    if payload.get("eligibility_universe_applied") is not False:
        raise RuntimeError("common-vintage artifact already claims eligibility")
    month = str(payload.get("selected_common_month") or "").strip()
    anchor_id = str((payload.get("anchor") or {}).get("institution_id") or "").strip()
    if not month or not anchor_id:
        raise RuntimeError("common-vintage artifact lost month/anchor")

    candidates = [
        TwoAxisFinancialCandidate(
            institution_id=str(row["institution_id"]),
            canonical_name=str(row["canonical_name"]),
            sector=str(row["sector"]),
            source_institution_key=str(row["source_institution_key"]),
            deposit_liabilities_total=Decimal(
                str(row["deposit_liabilities_total_million_krw"])
            ),
            total_assets=Decimal(str(row["total_assets_million_krw"])),
        )
        for row in payload["distribution"]["candidates"]
    ]
    return month, candidates, anchor_id


def _current_active_ids(db_path: Path, candidate_ids: set[str]) -> set[str]:
    if not candidate_ids:
        return set()
    placeholders = ",".join("?" for _ in candidate_ids)
    with closing(_open_immutable(db_path)) as connection:
        rows = connection.execute(
            f"SELECT id FROM institutions WHERE active = 1 AND id IN ({placeholders})",
            tuple(sorted(candidate_ids)),
        ).fetchall()
    return {str(row["id"]) for row in rows}


def _current_rate_rows(
    db_path: Path,
    *,
    source_id: str,
    candidate_ids: set[str],
    term_months: int,
) -> list[sqlite3.Row]:
    if not candidate_ids:
        return []
    placeholders = ",".join("?" for _ in candidate_ids)
    with closing(_open_immutable(db_path)) as connection:
        return connection.execute(
            f"""
            SELECT p.institution_id,
                   pv.join_channel,
                   o.region_sido,
                   o.region_sigungu,
                   o.address,
                   ro.last_seen_at,
                   ro.source_effective_at
            FROM rate_observations ro
            JOIN product_variants pv ON pv.id = ro.variant_id
            JOIN products p ON p.id = pv.product_id
            JOIN collection_runs cr ON cr.id = ro.last_run_id
            LEFT JOIN outlets o ON o.id = pv.outlet_id
            WHERE ro.valid_to IS NULL
              AND ro.validation_status != 'error'
              AND cr.source_id = ?
              AND p.product_type = 'term_deposit'
              AND pv.term_months = ?
              AND p.institution_id IN ({placeholders})
            ORDER BY p.institution_id
            """,
            (source_id, term_months, *sorted(candidate_ids)),
        ).fetchall()


def _rate_row_summary(rows: list[sqlite3.Row]) -> dict[str, Any]:
    last_seen = [str(row["last_seen_at"]) for row in rows if row["last_seen_at"]]
    effective = [
        str(row["source_effective_at"])
        for row in rows
        if row["source_effective_at"]
    ]
    return {
        "row_count": len(rows),
        "institution_count": len({str(row["institution_id"]) for row in rows}),
        "max_last_seen_at": max(last_seen) if last_seen else None,
        "max_source_effective_at": max(effective) if effective else None,
    }


def _nh_current_evidence(
    rows: list[sqlite3.Row],
) -> tuple[dict[str, set[str]], dict[str, set[str]], dict[str, Any]]:
    remote: dict[str, set[str]] = defaultdict(set)
    districts: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        institution_id = str(row["institution_id"])
        channel = str(row["join_channel"] or "").strip()
        if channel in {"internet", "mobile"}:
            remote[institution_id].add(channel)
        sido = str(row["region_sido"] or "").strip()
        sigungu = str(row["region_sigungu"] or "").strip()
        address = str(row["address"] or "").strip()
        if sido == "부산" and sigungu in BUSAN_DISTRICTS and address:
            districts[institution_id].add(sigungu)

    summary = _rate_row_summary(rows)
    summary.update(
        {
            "remote_institution_count": len(remote),
            "busan_branch_institution_count": len(districts),
        }
    )
    return remote, districts, summary


def _fsb_current_outlet_districts(
    db_path: Path,
    *,
    candidate_ids: set[str],
) -> tuple[dict[str, set[str]], dict[str, Any]]:
    if not candidate_ids:
        return {}, {"row_count": 0}
    placeholders = ",".join("?" for _ in candidate_ids)
    with closing(_open_immutable(db_path)) as connection:
        rows = connection.execute(
            f"""
            SELECT o.institution_id,
                   o.region_sigungu,
                   o.address
            FROM outlets o
            JOIN source_entity_links l
              ON l.entity_id = o.id
             AND l.entity_type = 'outlet'
             AND l.source_id = ?
             AND l.valid_to IS NULL
            WHERE o.active = 1
              AND o.institution_id IN ({placeholders})
              AND o.region_sido = '부산'
            ORDER BY o.institution_id, o.region_sigungu, o.id
            """,
            (FSB_SOURCE_ID, *sorted(candidate_ids)),
        ).fetchall()

    districts: dict[str, set[str]] = defaultdict(set)
    invalid_rows = 0
    for row in rows:
        sigungu = str(row["region_sigungu"] or "").strip()
        address = str(row["address"] or "").strip()
        if sigungu in BUSAN_DISTRICTS and address:
            districts[str(row["institution_id"])].add(sigungu)
        else:
            invalid_rows += 1
    return districts, {
        "row_count": len(rows),
        "institution_count": len(districts),
        "invalid_district_or_address_rows": invalid_rows,
    }


async def _fetch_fsb_busan_rows(
    term_months: int,
) -> tuple[list[dict[str, Any]], str]:
    if term_months != TERM_MONTHS_DEFAULT:
        raise RuntimeError(
            "current FSB live eligibility probe is contract-locked to 12 months"
        )
    query_date = now_kst().date()
    screen_path, _data_path = SCREENS["ratedepo"]
    timeout = httpx.Timeout(READ_TIMEOUT, connect=CONNECT_TIMEOUT)
    headers = {"User-Agent": USER_AGENT, "Content-Type": "application/json"}
    adapter = FsbAdapter()
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        headers=headers,
    ) as client:
        page = await client.get(f"{BASE_URL}{screen_path}")
        page.raise_for_status()
        await asyncio.sleep(REQUEST_INTERVAL_SECONDS)
        rows = await _fetch_area_rows(client, adapter, query_date, FSB_BUSAN_AREA)
    selected = [row for row in rows if term_months in fsb_parser.terms_in(row)]
    return selected, query_date.isoformat()


def _fsb_branch_capable_codes(
    rows: list[dict[str, Any]],
) -> tuple[set[str], dict[str, Any]]:
    codes: set[str] = set()
    institutions: set[str] = set()
    unknown_channel_rows = 0
    for row in rows:
        institution = fsb_parser.clean(row.get("FINAN_COMP_CODE"))
        if not institution:
            raise RuntimeError("FSB Busan row lost FINAN_COMP_CODE")
        institutions.add(institution)
        raw_channel = fsb_parser.clean(row.get("JOIN_LOCATION"))
        members = {value.strip() for value in raw_channel.split(",") if value.strip()}
        if not members:
            unknown_channel_rows += 1
            continue
        if "1" in members:
            codes.add(institution)
    return codes, {
        "row_count": len(rows),
        "institution_count": len(institutions),
        "branch_capable_institution_count": len(codes),
        "unknown_channel_rows": unknown_channel_rows,
    }


def _fsb_code_to_current_id(
    db_path: Path,
    *,
    source_keys: set[str],
) -> dict[str, str]:
    if not source_keys:
        return {}
    org_keys = [f"savings_bank:{key}" for key in sorted(source_keys)]
    placeholders = ",".join("?" for _ in org_keys)
    with closing(_open_immutable(db_path)) as connection:
        rows = connection.execute(
            f"""
            SELECT source_entity_key, entity_id
            FROM source_entity_links
            WHERE source_id = ?
              AND entity_type = 'institution'
              AND valid_to IS NULL
              AND source_entity_key IN ({placeholders})
            """,
            (FSB_SOURCE_ID, *org_keys),
        ).fetchall()
    return {
        str(row["source_entity_key"]).split(":", 1)[1]: str(row["entity_id"])
        for row in rows
    }


def _facts(
    candidates: list[TwoAxisFinancialCandidate],
    *,
    nh_remote: dict[str, set[str]],
    nh_districts: dict[str, set[str]],
    savings_districts: dict[str, set[str]],
    fsb_branch_codes: set[str],
    fsb_code_to_id: dict[str, str],
) -> tuple[list[EligibilityEvidenceFact], list[dict[str, str]]]:
    facts: list[EligibilityEvidenceFact] = []
    conflicts: list[dict[str, str]] = []
    for candidate in candidates:
        channels: tuple[str, ...] = ()
        districts: tuple[str, ...] = ()
        channel_source = None
        locality_source = None
        if candidate.sector == NH_SECTOR:
            channels = tuple(sorted(nh_remote.get(candidate.institution_id, set())))
            districts = tuple(sorted(nh_districts.get(candidate.institution_id, set())))
            if channels:
                channel_source = "nh_local_active_term_deposit_rate"
            if districts:
                locality_source = "nh_local_active_busan_outlet_rate"
        elif candidate.sector == SAVINGS_BANK:
            current_id = fsb_code_to_id.get(candidate.source_institution_key)
            if current_id and current_id != candidate.institution_id:
                conflicts.append(
                    {
                        "source_institution_key": candidate.source_institution_key,
                        "historical_institution_id": candidate.institution_id,
                        "current_fsb_institution_id": current_id,
                    }
                )
                continue
            has_branch = candidate.source_institution_key in fsb_branch_codes
            if current_id == candidate.institution_id and has_branch:
                districts = tuple(
                    sorted(savings_districts.get(candidate.institution_id, set()))
                )
                if districts:
                    locality_source = (
                        "fsb_live_busan_branch_channel_plus_official_outlet"
                    )
        facts.append(
            EligibilityEvidenceFact(
                institution_id=candidate.institution_id,
                source_channels=channels,
                busan_districts=districts,
                channel_evidence_source_id=channel_source,
                locality_evidence_source_id=locality_source,
            )
        )
    return facts, conflicts


def _selection_payload(selection: Any) -> dict[str, Any]:
    return {
        "eligible_count": selection.eligible_count,
        "excluded_count": selection.excluded_count,
        "exclusion_reason_counts": exclusion_reason_counts(selection),
        "eligible_ids": list(selection.eligible_ids),
    }


def _gap_payload(rows: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "count": len(rows),
        "threshold_counts": dict(threshold_counts(rows, thresholds=THRESHOLDS)),
        "top20": [
            {
                "institution_id": row.institution_id,
                "canonical_name": row.canonical_name,
                "sector": row.sector,
                "funding_gap": str(row.funding_gap),
                "assets_gap": str(row.assets_gap),
                "worst_axis_gap": str(row.worst_axis_gap),
                "sum_gap": str(row.sum_gap),
            }
            for row in rows[:20]
        ],
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", type=Path, required=True)
    parser.add_argument("--financial-evidence", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--term-months", type=int, default=TERM_MONTHS_DEFAULT)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    financial_as_of, financial_candidates, anchor_id = _load_financial_candidates(
        args.financial_evidence
    )
    candidate_ids = {candidate.institution_id for candidate in financial_candidates}
    active_ids = _current_active_ids(args.db_path, candidate_ids)
    inactive_ids = sorted(candidate_ids - active_ids)
    active_candidates = [
        candidate
        for candidate in financial_candidates
        if candidate.institution_id in active_ids
    ]

    nh_ids = {
        candidate.institution_id
        for candidate in active_candidates
        if candidate.sector == NH_SECTOR
    }
    savings_ids = {
        candidate.institution_id
        for candidate in active_candidates
        if candidate.sector == SAVINGS_BANK
    }
    nh_rows = _current_rate_rows(
        args.db_path,
        source_id=NH_SOURCE_ID,
        candidate_ids=nh_ids,
        term_months=args.term_months,
    )
    fsb_rows_current = _current_rate_rows(
        args.db_path,
        source_id=FSB_SOURCE_ID,
        candidate_ids=savings_ids,
        term_months=args.term_months,
    )
    nh_remote, nh_districts, nh_summary = _nh_current_evidence(nh_rows)
    fsb_current_product_ids = {
        str(row["institution_id"]) for row in fsb_rows_current
    }
    nh_current_product_ids = {str(row["institution_id"]) for row in nh_rows}
    current_product_ids = fsb_current_product_ids | nh_current_product_ids
    product_unavailable_ids = sorted(active_ids - current_product_ids)
    scenario_candidates = [
        candidate
        for candidate in active_candidates
        if candidate.institution_id in current_product_ids
    ]

    savings_scenario_ids = {
        candidate.institution_id
        for candidate in scenario_candidates
        if candidate.sector == SAVINGS_BANK
    }
    savings_districts, savings_outlet_summary = _fsb_current_outlet_districts(
        args.db_path,
        candidate_ids=savings_scenario_ids,
    )
    fsb_live_rows, fsb_query_date = asyncio.run(
        _fetch_fsb_busan_rows(args.term_months)
    )
    fsb_branch_codes, fsb_live_summary = _fsb_branch_capable_codes(fsb_live_rows)
    code_to_id = _fsb_code_to_current_id(
        args.db_path,
        source_keys={
            candidate.source_institution_key
            for candidate in scenario_candidates
            if candidate.sector == SAVINGS_BANK
        },
    )
    facts, identity_conflicts = _facts(
        scenario_candidates,
        nh_remote=nh_remote,
        nh_districts=nh_districts,
        savings_districts=savings_districts,
        fsb_branch_codes=fsb_branch_codes,
        fsb_code_to_id=code_to_id,
    )
    if identity_conflicts:
        raise RuntimeError(
            "current FSB identity conflicts with historical financial candidate: "
            f"count={len(identity_conflicts)}"
        )

    overlay = apply_current_eligibility(
        scenario_candidates,
        facts,
        financial_as_of=financial_as_of,
        eligibility_as_of=fsb_query_date,
        term_months=args.term_months,
    )
    if anchor_id not in overlay.remote.eligible_ids:
        raise RuntimeError("Koryo anchor is not eligible in REMOTE evidence")
    if anchor_id not in overlay.branch_busan.eligible_ids:
        raise RuntimeError("Koryo anchor is not eligible in BRANCH_BUSAN evidence")

    remote_gaps = relative_gap_distribution(
        scenario_candidates,
        eligible_ids=overlay.remote.eligible_ids,
        anchor_id=anchor_id,
    )
    branch_gaps = relative_gap_distribution(
        scenario_candidates,
        eligible_ids=overlay.branch_busan.eligible_ids,
        anchor_id=anchor_id,
    )
    sector_counts = Counter(candidate.sector for candidate in scenario_candidates)
    report = {
        "status": "ready_for_similarity_policy_review",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "financial_as_of": overlay.financial_as_of,
        "eligibility_evaluated_on": overlay.eligibility_as_of,
        "term_months": overlay.term_months,
        "policy_id": overlay.policy_id,
        "policy_version": overlay.policy_version,
        "financial_candidate_count": len(financial_candidates),
        "current_active_financial_candidate_count": len(active_candidates),
        "current_selected_product_candidate_count": len(scenario_candidates),
        "current_selected_product_count_by_sector": dict(sorted(sector_counts.items())),
        "current_inactive_candidate_count": len(inactive_ids),
        "current_inactive_candidate_ids": inactive_ids,
        "current_product_unavailable_count": len(product_unavailable_ids),
        "current_product_unavailable_ids": product_unavailable_ids,
        "evidence_sources": {
            "nh_local_current_rate": nh_summary,
            "fsb_current_rate": _rate_row_summary(fsb_rows_current),
            "fsb_live_busan": {**fsb_live_summary, "query_date": fsb_query_date},
            "fsb_official_outlets": savings_outlet_summary,
        },
        "remote": {
            **_selection_payload(overlay.remote),
            "relative_gap_evidence": _gap_payload(remote_gaps),
        },
        "branch_busan": {
            **_selection_payload(overlay.branch_busan),
            "relative_gap_evidence": _gap_payload(branch_gaps),
        },
        "anchor_id": anchor_id,
        "current_identity_conflicts": identity_conflicts,
        "similarity_metric_under_review": {
            "primary": (
                "max(abs(peer_funding/anchor_funding-1), "
                "abs(peer_assets/anchor_assets-1))"
            ),
            "tie_breaker": "funding_gap + assets_gap",
            "policy_locked": False,
            "peer_count_or_threshold_locked": False,
        },
        "persistence_enabled": False,
        "ui_ready_enabled": False,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        "eligibility evidence "
        f"financial={overlay.financial_as_of} "
        f"evaluated={overlay.eligibility_as_of} "
        f"product_candidates={len(scenario_candidates)} "
        f"remote={overlay.remote.eligible_count} "
        f"branch_busan={overlay.branch_busan.eligible_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
