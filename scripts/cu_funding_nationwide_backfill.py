"""Run nationwide CU disclosure funding backfill without canonical R2 publish.

This is an operational one-shot runner for the 2026-08-29 evidence gate.  It uses
``collect_cu_disclosure_funding`` because that collector isolates target-level
source failures instead of aborting the whole nationwide run.  The caller must
still inspect the returned failed-target population before any authoritative
publish.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from rate_monitor.collectors.cu.funding import collect_cu_disclosure_funding


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--periods", type=int, default=12)
    parser.add_argument("--request-interval", type=float, default=1.0)
    parser.add_argument("--json", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    result = collect_cu_disclosure_funding(
        db_path=args.db,
        raw_root=args.raw_root,
        periods=args.periods,
        request_interval=args.request_interval,
    )
    payload = asdict(result)
    payload["failed_targets"] = list(result.failed_targets)
    payload["canonical_r2_publish"] = False
    payload["operator_note"] = (
        "target-level failures are evidence gaps, not permission to publish; "
        "run candidate QC and inspect failures first"
    )
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    # Partial target coverage is expected evidence and must not prevent candidate QC.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
