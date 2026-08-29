"""Structural QC for a runner-local CU funding candidate database.

This script deliberately separates structural safety gates from coverage review.
Duplicate active observations, source collisions, or SQLite integrity/FK failures
are fatal. Missing institutions and period gaps are reported for review because a
credit union can legitimately lack an eligible disclosure in the official source.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import defaultdict
from pathlib import Path

from sqlalchemy import select

from rate_monitor.collectors.data_go_funding.reconciliation import build_report
from rate_monitor.db import models as m
from rate_monitor.db.institution_funding_models import InstitutionFundingObservation
from rate_monitor.db.session import create_db_engine, make_session_factory, session_scope

EXPECTED_SOURCE = "cu_disclosure_funding"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--json", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    engine = create_db_engine(args.db)
    factory = make_session_factory(engine)
    with session_scope(factory) as session:
        links = list(
            session.scalars(
                select(m.SourceEntityLink).where(
                    m.SourceEntityLink.source_id == "cu",
                    m.SourceEntityLink.entity_type == "institution",
                    m.SourceEntityLink.valid_to.is_(None),
                )
            )
        )
        rows = list(
            session.scalars(
                select(InstitutionFundingObservation).where(
                    InstitutionFundingObservation.sector == "cu",
                    InstitutionFundingObservation.valid_to.is_(None),
                )
            )
        )

    target_keys = sorted(
        {
            link.source_entity_key.removeprefix("cu:").strip()
            for link in links
            if link.source_entity_key.startswith("cu:")
        }
    )
    funding_keys = sorted({row.source_institution_key for row in rows})
    target_set = set(target_keys)
    funding_set = set(funding_keys)

    active_key_counts: dict[tuple[str, str, str, str], int] = defaultdict(int)
    sources_by_month: dict[str, set[str]] = defaultdict(set)
    institutions_by_month: dict[str, set[str]] = defaultdict(set)
    sums_by_month: dict[str, float] = defaultdict(float)
    for row in rows:
        active_key_counts[
            (
                row.source_id,
                row.source_institution_key,
                row.metric_code,
                row.source_effective_month,
            )
        ] += 1
        sources_by_month[row.source_effective_month].add(row.source_id)
        institutions_by_month[row.source_effective_month].add(row.source_institution_key)
        sums_by_month[row.source_effective_month] += float(row.value)

    duplicates = [
        {
            "source_id": key[0],
            "source_institution_key": key[1],
            "metric_code": key[2],
            "month": key[3],
            "count": count,
        }
        for key, count in sorted(active_key_counts.items())
        if count != 1
    ]
    collisions = [
        {"month": month, "source_ids": sorted(source_ids)}
        for month, source_ids in sorted(sources_by_month.items())
        if len(source_ids) != 1 or EXPECTED_SOURCE not in source_ids
    ]

    connection = sqlite3.connect(args.db)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        fk_violations = len(connection.execute("PRAGMA foreign_key_check").fetchall())
    finally:
        connection.close()

    report = build_report(args.db)
    cu_reconciliation = [
        item for item in report["reconciliation"] if item["sector"] == "cu"
    ]
    period_coverage = [
        {
            "month": month,
            "institution_count": len(institutions_by_month[month]),
            "sum_million_krw": str(sums_by_month[month]),
            "source_ids": sorted(sources_by_month[month]),
        }
        for month in sorted(institutions_by_month, reverse=True)
    ]

    payload = {
        "target_count": len(target_keys),
        "institutions_with_any_funding": len(funding_keys),
        "institution_coverage_ratio": (
            len(funding_keys) / len(target_keys) if target_keys else 0
        ),
        "missing_target_count": len(target_set - funding_set),
        "missing_targets": sorted(target_set - funding_set),
        "unexpected_funding_keys": sorted(funding_set - target_set),
        "active_observation_count": len(rows),
        "duplicate_active_keys": duplicates,
        "source_collisions": collisions,
        "period_coverage": period_coverage,
        "cu_reconciliation": cu_reconciliation,
        "integrity_check": integrity,
        "foreign_key_violations": fk_violations,
        "structural_gate": "pass",
    }

    fatal: list[str] = []
    if integrity != "ok":
        fatal.append(f"integrity_check={integrity}")
    if fk_violations:
        fatal.append(f"foreign_key_violations={fk_violations}")
    if duplicates:
        fatal.append(f"duplicate_active_keys={len(duplicates)}")
    if collisions:
        fatal.append(f"source_collisions={len(collisions)}")
    if payload["unexpected_funding_keys"]:
        fatal.append(
            f"unexpected_funding_keys={len(payload['unexpected_funding_keys'])}"
        )
    if rows and any(row.source_id != EXPECTED_SOURCE for row in rows):
        fatal.append("unexpected active CU funding source")
    if not rows:
        fatal.append("active CU funding observation count is zero")

    if fatal:
        payload["structural_gate"] = "fail"
        payload["fatal_reasons"] = fatal

    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if fatal:
        raise SystemExit("CU funding candidate structural gate failed: " + "; ".join(fatal))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
