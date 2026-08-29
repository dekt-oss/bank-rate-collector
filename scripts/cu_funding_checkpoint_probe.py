from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

from rate_monitor.collectors.cu.resumable_funding import (
    acquire_cu_funding_checkpoint,
    replay_cu_funding_checkpoint,
)
from rate_monitor.services.storage_service import LocalObjectStore

CONTROL_TARGETS = {"02002", "02022", "03087", "10154"}
EXPECTED_WARNING_COUNT = 3


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--checkpoint-root", type=Path, required=True)
    parser.add_argument("--json", type=Path, required=True)
    parser.add_argument("--cycle-date", default="2026-08-29")
    parser.add_argument("--periods", type=int, default=12)
    parser.add_argument("--request-interval", type=float, default=1.0)
    return parser


def _progress(value) -> dict[str, Any]:
    return {
        "status": value.status,
        "session_id": value.session_id,
        "expected_targets": value.expected_targets,
        "completed_targets": value.completed_targets,
        "newly_completed_targets": value.newly_completed_targets,
        "warning_count": value.warning_count,
    }


def _replay(value) -> dict[str, Any]:
    return {
        "run_id": value.run_id,
        "target_count": value.target_count,
        "raw_artifacts": value.raw_artifacts,
        "parsed_points": value.parsed_points,
        "stored": value.stored,
        "unchanged": value.unchanged,
        "revisions": value.revisions,
        "warning_count": value.warning_count,
    }


def _db_integrity(db_path: Path) -> dict[str, Any]:
    connection = sqlite3.connect(db_path)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        fk = connection.execute("PRAGMA foreign_key_check").fetchall()
        active = connection.execute(
            """
            SELECT COUNT(*)
            FROM institution_funding_observations
            WHERE source_id = 'cu_disclosure_funding' AND valid_to IS NULL
            """
        ).fetchone()[0]
        runs = connection.execute(
            """
            SELECT COUNT(*)
            FROM collection_runs
            WHERE source_id = 'cu_disclosure_funding'
              AND mode = 'checkpoint_replay'
              AND status = 'success'
            """
        ).fetchone()[0]
    finally:
        connection.close()
    return {
        "integrity_check": integrity,
        "foreign_key_violations": len(fk),
        "active_cu_funding_observations": active,
        "successful_checkpoint_replay_runs": runs,
    }


def main() -> int:
    args = _parser().parse_args()
    args.checkpoint_root.mkdir(parents=True, exist_ok=True)
    args.raw_root.mkdir(parents=True, exist_ok=True)
    store = LocalObjectStore(args.checkpoint_root)

    first = acquire_cu_funding_checkpoint(
        store=store,
        db_path=args.db,
        periods=args.periods,
        cycle_date_kst=args.cycle_date,
        only_cu_nos=CONTROL_TARGETS,
        max_new_targets=2,
        request_interval=args.request_interval,
    )
    if first.status != "collecting" or first.completed_targets != 2:
        raise RuntimeError(f"first bounded acquisition mismatch: {first}")

    second = acquire_cu_funding_checkpoint(
        store=store,
        db_path=args.db,
        periods=args.periods,
        cycle_date_kst=args.cycle_date,
        only_cu_nos=CONTROL_TARGETS,
        request_interval=args.request_interval,
    )
    if second.status != "complete" or second.completed_targets != 4:
        raise RuntimeError(f"resume acquisition mismatch: {second}")
    if second.session_id != first.session_id or second.newly_completed_targets != 2:
        raise RuntimeError("resume did not continue the same CU checkpoint session")
    if second.warning_count != EXPECTED_WARNING_COUNT:
        raise RuntimeError(
            f"unexpected CU quarantine warning count: {second.warning_count}"
        )

    third = acquire_cu_funding_checkpoint(
        store=store,
        db_path=args.db,
        periods=args.periods,
        cycle_date_kst=args.cycle_date,
        only_cu_nos=CONTROL_TARGETS,
        request_interval=args.request_interval,
    )
    if third.status != "complete" or third.newly_completed_targets != 0:
        raise RuntimeError(f"complete checkpoint replay acquisition mismatch: {third}")
    if third.session_id != first.session_id:
        raise RuntimeError("complete checkpoint session identity changed")

    first_replay = replay_cu_funding_checkpoint(
        store=store,
        db_path=args.db,
        raw_root=args.raw_root,
        periods=args.periods,
        cycle_date_kst=args.cycle_date,
    )
    if first_replay.target_count != 4:
        raise RuntimeError(f"replay target count mismatch: {first_replay.target_count}")
    if first_replay.warning_count != EXPECTED_WARNING_COUNT:
        raise RuntimeError(
            f"replay warning count mismatch: {first_replay.warning_count}"
        )
    if first_replay.parsed_points <= 0:
        raise RuntimeError("checkpoint replay produced zero valid points")

    second_replay = replay_cu_funding_checkpoint(
        store=store,
        db_path=args.db,
        raw_root=args.raw_root,
        periods=args.periods,
        cycle_date_kst=args.cycle_date,
    )
    if second_replay.stored != 0 or second_replay.revisions != 0:
        raise RuntimeError(f"checkpoint replay is not idempotent: {second_replay}")
    if second_replay.unchanged != second_replay.parsed_points:
        raise RuntimeError(f"unchanged count mismatch: {second_replay}")

    integrity = _db_integrity(args.db)
    if integrity["integrity_check"] != "ok":
        raise RuntimeError(f"SQLite integrity failed: {integrity}")
    if integrity["foreign_key_violations"] != 0:
        raise RuntimeError(f"SQLite FK check failed: {integrity}")

    checkpoint_files = sorted(
        str(path.relative_to(args.checkpoint_root))
        for path in args.checkpoint_root.rglob("*")
        if path.is_file()
    )
    payload = {
        "mode": "bounded_real_source_local_checkpoint_no_publish",
        "controls": sorted(CONTROL_TARGETS),
        "cycle_date_kst": args.cycle_date,
        "periods": args.periods,
        "request_interval_seconds": args.request_interval,
        "first_acquisition": _progress(first),
        "resumed_acquisition": _progress(second),
        "complete_reopen": _progress(third),
        "first_replay": _replay(first_replay),
        "second_replay": _replay(second_replay),
        "checkpoint_file_count": len(checkpoint_files),
        "checkpoint_files": checkpoint_files,
        "database": integrity,
        "authoritative_r2_publish": False,
        "checkpoint_backend": "runner_local_filesystem",
    }
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
