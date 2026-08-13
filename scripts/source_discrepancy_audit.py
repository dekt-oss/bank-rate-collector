#!/usr/bin/env python3
"""FSB ↔ 금융상품한눈에 저축은행 금리 교차검증 JSON을 만든다."""

from __future__ import annotations

import argparse
from pathlib import Path

from rate_monitor.services.source_discrepancy_service import write_source_discrepancy_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, help="감사할 SQLite DB")
    parser.add_argument("--out", default="work/source-discrepancy-report.json")
    parser.add_argument("--primary-source", default="fsb")
    parser.add_argument("--secondary-source", default="finlife_savings_bank")
    parser.add_argument(
        "--official-evidence",
        default=None,
        help="개별 금융사 공식 홈페이지 증거 JSON. DB에는 쓰지 않는다.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    report = write_source_discrepancy_report(
        Path(args.db),
        Path(args.out),
        primary_source=args.primary_source,
        secondary_source=args.secondary_source,
        official_evidence_path=Path(args.official_evidence) if args.official_evidence else None,
    )
    summary = report["summary"]
    print(f"report                    : {args.out}")
    print(f"primary products          : {summary['primary_products']}")
    print(f"secondary products        : {summary['secondary_products']}")
    print(f"exact matches             : {summary['exact_matches']}")
    print(f"max agree                 : {summary['agree']}")
    print(f"max agree / date differs  : {summary['agree_rate_date_diff']}")
    print(f"max agree / date unknown  : {summary['agree_rate_date_unknown']}")
    print(f"max mismatch              : {summary['rate_mismatch']}")
    print(f"max mismatch / date differs: {summary['rate_mismatch_date_diff']}")
    print(f"max mismatch / date unknown: {summary['rate_mismatch_date_unknown']}")
    print(f"max incomplete            : {summary['incomplete_rate']}")
    print(f"base agree                : {summary['base_rate_agree']}")
    print(f"base mismatch             : {summary['base_rate_mismatch']}")
    print(f"base incomplete           : {summary['base_rate_incomplete']}")
    print(f"base both missing         : {summary['base_rate_both_missing']}")
    print(f"unmatched product         : {summary['unmatched_product']}")
    print(f"source only               : {summary['source_only']}")
    print(f"official evidence         : {summary['official_evidence_records']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
