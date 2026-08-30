"""CLI for Data.go.kr institution funding collection and evidence reports."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from rate_monitor.collectors.data_go_funding.collector import current_counts
from rate_monitor.collectors.data_go_funding.identity_reconciliation import (
    FUNDING_SOURCE_ID,
    reconcile_agri_funding_identity,
)
from rate_monitor.collectors.data_go_funding.operations import (
    collect_operational,
    operational_payload,
)
from rate_monitor.collectors.data_go_funding.reconciliation import build_report
from rate_monitor.collectors.data_go_funding.resilient import required_failures


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    collect = sub.add_parser("collect")
    collect.add_argument("--db", type=Path, required=True)
    collect.add_argument("--raw-root", type=Path, default=Path("data/raw"))
    collect.add_argument("--periods", type=int, default=12)
    collect.add_argument(
        "--mode",
        choices=("incremental", "backfill", "custom"),
        default="custom",
        help=(
            "incremental=최근 약 1년 revision watch, "
            "backfill=최초 6년 이력 수집, custom=--periods 사용"
        ),
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

    counts = sub.add_parser("counts")
    counts.add_argument("--db", type=Path, required=True)

    identity = sub.add_parser(
        "reconcile-nh-identity",
        help="기존 농·축협 수신 관측을 exact BRC+공식명으로 재조정한다",
    )
    identity.add_argument("--db", type=Path, required=True)
    identity.add_argument("--json", type=Path)

    return parser


def _identity_payload(db_path: Path) -> dict[str, object]:
    result = reconcile_agri_funding_identity(db_path)
    payload: dict[str, object] = {
        "source_id": FUNDING_SOURCE_ID,
        "identity_contract": "exact_brc_plus_normalized_official_source_name",
        **asdict(result),
    }
    return payload


def _print_identity(phase: str, payload: dict[str, object]) -> None:
    print(
        "funding identity reconciliation "
        f"phase={phase} source={payload['source_id']} "
        f"scanned={payload['scanned']} eligible={payload['eligible']} "
        f"mapped={payload['mapped']} unchanged={payload['unchanged']} "
        f"no_brc_link={payload['no_brc_link']} "
        f"name_mismatch={payload['name_mismatch']} "
        f"invalid_link={payload['invalid_link']}",
        flush=True,
    )


def _write_json(path: Path | None, payload: dict[str, object]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    args = _parser().parse_args()
    if args.command == "collect":
        # Reconcile historical rows before any network fan-out. This makes old
        # persisted observations recover automatically once an exact nh_local
        # BRC link becomes available. A conflicting existing mapping fails closed.
        pre_identity = _identity_payload(args.db)
        _print_identity("pre_collect", pre_identity)

        results = collect_operational(
            db_path=args.db,
            raw_root=args.raw_root,
            mode=args.mode,
            custom_periods=args.periods,
            require_credit_union=args.require_credit_union,
        )

        # Run again after collection so newly persisted NH observations are not
        # dependent on a transport result being exactly "success". Required
        # partial/failed source handling below is unchanged and can still block publish.
        post_identity = _identity_payload(args.db)
        _print_identity("post_collect", post_identity)

        payload = operational_payload(
            mode=args.mode,
            results=results,
            db_path=args.db,
        )
        payload["nh_identity_reconciliation"] = {
            "pre_collect": pre_identity,
            "post_collect": post_identity,
        }

        if args.json:
            args.json.parent.mkdir(parents=True, exist_ok=True)
            args.json.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
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

    if args.command == "reconcile-nh-identity":
        payload = _identity_payload(args.db)
        _print_identity("standalone", payload)
        _write_json(args.json, payload)
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
