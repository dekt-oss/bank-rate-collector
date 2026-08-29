"""Operator CLI for durable CU disclosure-funding acquisition.

`acquire` writes only content-addressed checkpoint objects.  It never writes the
canonical `state/current.json` pointer.  `validate` reads a *complete* checkpoint,
replays it into the supplied runner-local database, proves idempotency, and emits
reconciliation evidence.  Publishing the validated database is deliberately out
of scope for this CLI.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from rate_monitor.collectors.cu.resumable_funding import (
    acquire_cu_funding_checkpoint,
    replay_cu_funding_checkpoint,
)
from rate_monitor.collectors.data_go_funding.reconciliation import build_report
from rate_monitor.services.storage_service import R2Config, StorageError, open_store


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    acquire = sub.add_parser("acquire")
    acquire.add_argument("--db", type=Path, required=True)
    acquire.add_argument("--cycle-date", required=True)
    acquire.add_argument("--periods", type=int, default=12)
    acquire.add_argument("--resume-mode", choices=("auto", "fresh"), default="auto")
    acquire.add_argument("--max-new-targets", type=int, default=150)
    acquire.add_argument("--request-interval", type=float, default=1.0)
    acquire.add_argument("--json", type=Path, required=True)

    validate = sub.add_parser("validate")
    validate.add_argument("--db", type=Path, required=True)
    validate.add_argument("--raw-root", type=Path, required=True)
    validate.add_argument("--cycle-date", required=True)
    validate.add_argument("--periods", type=int, default=12)
    validate.add_argument("--json", type=Path, required=True)
    return parser


def _store():
    config = R2Config.from_env()
    if config is None:
        raise StorageError("CU funding checkpoint operation requires complete R2 config")
    return open_store(config)


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _acquire(args: argparse.Namespace) -> int:
    max_new_targets = args.max_new_targets or None
    if max_new_targets is not None and max_new_targets < 1:
        raise SystemExit("--max-new-targets는 0(무제한) 또는 1 이상이어야 한다")
    progress = acquire_cu_funding_checkpoint(
        store=_store(),
        db_path=args.db,
        periods=args.periods,
        cycle_date_kst=args.cycle_date,
        resume_mode=args.resume_mode,
        max_new_targets=max_new_targets,
        request_interval=args.request_interval,
    )
    payload = {
        "mode": "r2_checkpoint_acquire_no_canonical_publish",
        "cycle_date_kst": args.cycle_date,
        "periods": args.periods,
        "resume_mode": args.resume_mode,
        "max_new_targets": max_new_targets,
        "status": progress.status,
        "session_id": progress.session_id,
        "expected_targets": progress.expected_targets,
        "completed_targets": progress.completed_targets,
        "newly_completed_targets": progress.newly_completed_targets,
        "warning_count": progress.warning_count,
        "canonical_r2_publish": False,
    }
    _write(args.json, payload)
    return 0


def _validate(args: argparse.Namespace) -> int:
    store = _store()
    first = replay_cu_funding_checkpoint(
        store=store,
        db_path=args.db,
        raw_root=args.raw_root,
        periods=args.periods,
        cycle_date_kst=args.cycle_date,
    )
    second = replay_cu_funding_checkpoint(
        store=store,
        db_path=args.db,
        raw_root=args.raw_root,
        periods=args.periods,
        cycle_date_kst=args.cycle_date,
    )
    if second.stored != 0 or second.revisions != 0:
        raise SystemExit(
            "CU funding complete-checkpoint replay가 idempotent하지 않다: "
            f"stored={second.stored} revisions={second.revisions}"
        )
    if second.unchanged != second.parsed_points:
        raise SystemExit(
            "CU funding complete-checkpoint unchanged 수가 parsed point와 다르다: "
            f"unchanged={second.unchanged} parsed={second.parsed_points}"
        )

    report = build_report(args.db)
    cu_coverage = [item for item in report["coverage"] if item["sector"] == "cu"]
    cu_reconciliation = [
        item for item in report["reconciliation"] if item["sector"] == "cu"
    ]
    if not cu_coverage:
        raise SystemExit("CU funding checkpoint replay 후 coverage가 0건이다")
    if any(item["source_id"] != "cu_disclosure_funding" for item in cu_coverage):
        raise SystemExit("CU funding coverage에 승인되지 않은 active source가 섞였다")
    if any(item["source_unit"] != "million_krw" for item in cu_coverage):
        raise SystemExit("CU funding coverage source unit이 million_krw가 아니다")
    matched = [
        item
        for item in cu_reconciliation
        if item["status"] != "no_matching_ecos_period"
    ]
    if not matched:
        raise SystemExit("CU funding과 동일 기준월인 ECOS reconciliation이 한 건도 없다")

    payload = {
        "mode": "complete_r2_checkpoint_replay_validation_no_canonical_publish",
        "cycle_date_kst": args.cycle_date,
        "periods": args.periods,
        "first_replay": {
            "run_id": first.run_id,
            "target_count": first.target_count,
            "raw_artifacts": first.raw_artifacts,
            "parsed_points": first.parsed_points,
            "stored": first.stored,
            "unchanged": first.unchanged,
            "revisions": first.revisions,
            "warning_count": first.warning_count,
        },
        "second_replay": {
            "run_id": second.run_id,
            "target_count": second.target_count,
            "raw_artifacts": second.raw_artifacts,
            "parsed_points": second.parsed_points,
            "stored": second.stored,
            "unchanged": second.unchanged,
            "revisions": second.revisions,
            "warning_count": second.warning_count,
        },
        "cu_coverage": cu_coverage,
        "cu_reconciliation": cu_reconciliation,
        "matched_ecos_periods": len(matched),
        "canonical_r2_publish": False,
    }
    _write(args.json, payload)
    return 0


def main() -> int:
    args = _parser().parse_args()
    if args.command == "acquire":
        return _acquire(args)
    if args.command == "validate":
        return _validate(args)
    raise SystemExit(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
