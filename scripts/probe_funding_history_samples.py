"""Read-only representative historical Data.go funding probe for GitHub Actions.

The runner-local DB is created/migrated by the diagnostic workflow.  This script probes
sparse historical reporting months so a slow full-range backfill is not required to
prove that the source serves historical ``basYm`` rows.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rate_monitor.collectors.data_go_funding.collector import CONTRACTS
from rate_monitor.collectors.data_go_funding.resilient import collect_source_resilient

SAMPLE_MONTHS = {
    "savings_bank": ("202006", "202212", "202406", "202606"),
    "nh_local": ("202006", "202212", "202406", "202606"),
    "cu": ("202212", "202406", "202606"),
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--json", type=Path, required=True)
    parser.add_argument(
        "--sectors",
        default="savings_bank,nh_local,cu",
        help="쉼표로 구분한 probe sector 목록",
    )
    args = parser.parse_args()
    sectors = {value.strip() for value in args.sectors.split(",") if value.strip()}
    known = {contract.sector for contract in CONTRACTS}
    unknown = sectors - known
    if not sectors or unknown:
        raise SystemExit(f"지원하지 않는 sector: {sorted(unknown)}")

    results = []
    for contract in CONTRACTS:
        if contract.sector not in sectors:
            continue
        result = collect_source_resilient(
            contract,
            db_path=args.db,
            raw_root=args.raw_root,
            periods=1,
            required=False,
            requested_months=SAMPLE_MONTHS[contract.sector],
        )
        results.append(result.__dict__)

    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
