"""CLI for Data.go.kr institution funding collection and evidence reports."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rate_monitor.collectors.data_go_funding.collector import current_counts
from rate_monitor.collectors.data_go_funding.history_audit import build_history_audit
from rate_monitor.collectors.data_go_funding.reconciliation import build_report
from rate_monitor.collectors.data_go_funding.resilient import (
    collect_all_resilient,
    required_failures,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    collect = sub.add_parser("collect")
    collect.add_argument("--db", type=Path, required=True)
    collect.add_argument("--raw-root", type=Path, default=Path("data/raw"))
    collect.add_argument(
        "--periods",
        type=int,
        default=12,
        help="명시적 backfill 범위가 없을 때 최근 source 보고기간 수",
    )
    collect.add_argument(
        "--start-month",
        help="과거 backfill 시작 기준월(YYYYMM 또는 YYYY-MM, inclusive)",
    )
    collect.add_argument(
        "--end-month",
        help="과거 backfill 종료 기준월(YYYYMM 또는 YYYY-MM, inclusive)",
    )
    collect.add_argument(
        "--require-credit-union",
        action="store_true",
        help="신협 exact finance contract가 미확정이면 전체 실행을 실패시킨다",
    )
    collect.add_argument("--json", type=Path)

    report = sub.add_parser("report")
    report.add_argument("--db", type=Path, required=True)
    report.add_argument("--json", type=Path, required=True)

    audit = sub.add_parser("audit")
    audit.add_argument("--db", type=Path, required=True)
    audit.add_argument("--json", type=Path, required=True)
    audit.add_argument(
        "--windows",
        default="24,36",
        help="연속성 감사 calendar-month window. 기본 24,36",
    )

    counts = sub.add_parser("counts")
    counts.add_argument("--db", type=Path, required=True)

    return parser


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _parse_windows(raw: str) -> tuple[int, ...]:
    try:
        values = tuple(int(value.strip()) for value in raw.split(",") if value.strip())
    except ValueError as exc:
        raise SystemExit("--windows는 쉼표로 구분한 정수여야 한다") from exc
    if not values or any(value < 1 for value in values):
        raise SystemExit("--windows는 1 이상의 값을 하나 이상 지정해야 한다")
    return values


def main() -> int:
    args = _parser().parse_args()
    if args.command == "collect":
        if bool(args.start_month) != bool(args.end_month):
            raise SystemExit("--start-month과 --end-month는 함께 지정해야 한다")
        results = collect_all_resilient(
            db_path=args.db,
            raw_root=args.raw_root,
            periods=args.periods,
            require_credit_union=args.require_credit_union,
            start_month=args.start_month,
            end_month=args.end_month,
        )
        payload = [result.__dict__ for result in results]
        if args.json:
            _write_json(args.json, payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        failures = required_failures(results)
        if failures:
            failed = ", ".join(
                f"{result.source_id}[{','.join(result.failed_months) or result.status}]"
                for result in failures
            )
            print(f"필수 source/month 미완료: {failed}")
            return 1
        return 0

    if args.command == "report":
        payload = build_report(args.db)
        _write_json(args.json, payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.command == "audit":
        payload = build_history_audit(args.db, windows=_parse_windows(args.windows))
        _write_json(args.json, payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print(json.dumps(current_counts(args.db), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
