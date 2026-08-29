from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from sqlalchemy import select

from rate_monitor.collectors.cu.funding import (
    IDENTITY_STATUS,
    METRIC_CODE,
    NORMALIZED_UNIT,
    SOURCE_ID,
    SOURCE_UNIT,
    _targets,
    collect_cu_disclosure_funding,
)
from rate_monitor.db.institution_funding_models import InstitutionFundingObservation
from rate_monitor.db.session import create_db_engine, make_session_factory, session_scope

FORCED_CONTROLS = ("02002", "02022")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--json", type=Path, required=True)
    parser.add_argument("--sample-size", type=int, default=24)
    parser.add_argument("--periods", type=int, default=12)
    parser.add_argument("--request-interval", type=float, default=1.0)
    return parser


def _even_sample(keys: list[str], size: int) -> list[str]:
    if size < 1:
        raise ValueError("sample-size는 1 이상이어야 한다")
    if size >= len(keys):
        return list(keys)

    chosen: list[str] = []
    seen: set[str] = set()
    for control in FORCED_CONTROLS:
        if control in keys and control not in seen:
            chosen.append(control)
            seen.add(control)

    remaining = max(0, size - len(chosen))
    if remaining:
        if remaining == 1:
            positions = [len(keys) // 2]
        else:
            positions = [
                round(index * (len(keys) - 1) / (remaining - 1))
                for index in range(remaining)
            ]
        for position in positions:
            key = keys[position]
            if key not in seen:
                chosen.append(key)
                seen.add(key)

    if len(chosen) < size:
        for key in keys:
            if key in seen:
                continue
            chosen.append(key)
            seen.add(key)
            if len(chosen) == size:
                break

    return sorted(chosen[:size])


def _observation_payload(db_path: Path, sample: list[str]) -> dict[str, Any]:
    engine = create_db_engine(db_path)
    factory = make_session_factory(engine)
    with session_scope(factory) as session:
        rows = list(
            session.scalars(
                select(InstitutionFundingObservation).where(
                    InstitutionFundingObservation.source_id == SOURCE_ID,
                    InstitutionFundingObservation.source_institution_key.in_(sample),
                    InstitutionFundingObservation.metric_code == METRIC_CODE,
                    InstitutionFundingObservation.valid_to.is_(None),
                )
            )
        )

    grouped: dict[str, list[InstitutionFundingObservation]] = defaultdict(list)
    for row in rows:
        grouped[row.source_institution_key].append(row)

    institutions: list[dict[str, Any]] = []
    for key in sample:
        items = sorted(grouped.get(key, []), key=lambda row: row.source_effective_month)
        institutions.append(
            {
                "cu_ingno": key,
                "observation_count": len(items),
                "earliest_month": items[0].source_effective_month if items else None,
                "latest_month": items[-1].source_effective_month if items else None,
                "latest_value_million_krw": str(items[-1].value) if items else None,
                "source_name": items[-1].source_institution_name if items else None,
            }
        )

    invalid = [
        {
            "cu_ingno": row.source_institution_key,
            "month": row.source_effective_month,
            "unit": row.unit,
            "source_unit": row.source_unit,
            "identity_status": row.identity_status,
            "institution_id": row.institution_id,
        }
        for row in rows
        if (
            row.unit != NORMALIZED_UNIT
            or row.source_unit != SOURCE_UNIT
            or row.identity_status != IDENTITY_STATUS
            or row.institution_id is None
            or not row.source_effective_month.endswith(("-06", "-12"))
        )
    ]
    return {
        "active_observations": len(rows),
        "institutions_with_observations": len(grouped),
        "missing_sample_targets": sorted(set(sample) - set(grouped)),
        "contract_violations": invalid,
        "institutions": institutions,
    }


def main() -> int:
    args = _parser().parse_args()
    engine = create_db_engine(args.db)
    factory = make_session_factory(engine)
    targets = _targets(factory, None)
    target_keys = [row[0] for row in targets]
    sample = _even_sample(target_keys, args.sample_size)

    started = time.monotonic()
    result = collect_cu_disclosure_funding(
        db_path=args.db,
        raw_root=args.raw_root,
        periods=args.periods,
        only_cu_nos=set(sample),
        request_interval=args.request_interval,
    )
    elapsed = time.monotonic() - started
    observations = _observation_payload(args.db, sample)

    payload = {
        "mode": "nationwide_even_sample_r2_restore_no_publish",
        "nationwide_target_count": len(targets),
        "nationwide_target_first": target_keys[0],
        "nationwide_target_last": target_keys[-1],
        "sample_size": len(sample),
        "sample_keys": sample,
        "periods_requested": args.periods,
        "request_interval_seconds": args.request_interval,
        "elapsed_seconds": round(elapsed, 3),
        "seconds_per_target": round(elapsed / len(sample), 3),
        "collection": {
            "status": result.status,
            "run_id": result.run_id,
            "target_count": result.target_count,
            "completed_targets": result.completed_targets,
            "failed_targets": list(result.failed_targets),
            "fetched_artifacts": result.fetched_artifacts,
            "parsed_points": result.parsed_points,
            "stored": result.stored,
            "unchanged": result.unchanged,
            "revisions": result.revisions,
            "warning_count": result.warning_count,
            "warning_rate_per_target": round(result.warning_count / len(sample), 6),
            "message": result.message,
        },
        "observations": observations,
    }
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    if result.status != "success" or result.completed_targets != len(sample):
        return 1
    if observations["missing_sample_targets"] or observations["contract_violations"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
