"""CLI for Data.go.kr institution funding collection and evidence reports."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rate_monitor.collectors.data_go_funding.collector import collect_all, current_counts
from rate_monitor.collectors.data_go_funding.reconciliation import build_report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    collect = sub.add_parser("collect")
    collect.add_argument("--db", type=Path, required=True)
    collect.add_argument("--raw-root", type=Path, default=Path("data/raw"))
    collect.add_argument("--periods", type=int, default=12)
    collect.add_argument(
        "--require-credit-union",
        action="store_true",
        help="신협 exact finance contract가 미확정이면 전체 실행을 실패시킨다",
    )
    collect.add_argument("--json", type=Path)

    report = sub.add_parser("report")
    report.add_argument("--db", type=Path, required=True)
    report.add_argument("--json", type=Path, required=True)

    counts = sub.add_parser("counts")
    counts.add_argument("--db", type=Path, required=True)

    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.command == "collect":
        results = collect_all(
            db_path=args.db,
            raw_root=args.raw_root,
            periods=args.periods,
            allow_unavailable_credit_union=not args.require_credit_union,
        )
        payload = [result.__dict__ for result in results]
        if args.json:
            args.json.parent.mkdir(parents=True, exist_ok=True)
            args.json.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.command == "report":
        payload = build_report(args.db)
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print(json.dumps(current_counts(args.db), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
