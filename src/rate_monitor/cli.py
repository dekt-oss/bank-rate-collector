"""rate-monitor CLI.

명세서 v3.1 §9.1: collect / build-dashboard / validate.
`serve`는 만들지 않는다 — Actions 실행형이라 로컬 서버를 볼 수 없다.
"""

import argparse
import asyncio
import sys
from pathlib import Path

from rate_monitor.collectors.finlife.adapter import FinlifeAdapter
from rate_monitor.db.session import DEFAULT_DB_PATH, create_db_engine, make_session_factory
from rate_monitor.domain.schemas import CollectionRequest
from rate_monitor.services.collection_service import DEFAULT_RAW_ROOT, collect_source

ADAPTERS = {"finlife": FinlifeAdapter}


def _collect(args: argparse.Namespace) -> int:
    adapter_cls = ADAPTERS.get(args.source)
    if adapter_cls is None:
        print(f"알 수 없는 수집원: {args.source}", file=sys.stderr)
        return 2

    engine = create_db_engine(args.db)
    factory = make_session_factory(engine)
    request = CollectionRequest(
        source_id=args.source,
        options={
            "services": tuple(args.services),
            "groups": tuple(args.groups),
        },
    )
    result = asyncio.run(
        collect_source(adapter_cls(), request, factory, raw_root=Path(args.raw_root))
    )

    print(f"run_id      : {result.run_id}")
    print(f"status      : {result.status}")
    print(f"raw/parsed  : {result.raw_count} / {result.parsed_count}")
    print(f"valid/error : {result.valid_count} / {result.error_count}")
    print(f"warnings    : {result.warning_count}")
    print(f"message     : {result.message}")
    return 0 if result.status in ("success", "partial", "no_change") else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rate-monitor")
    sub = parser.add_subparsers(dest="command", required=True)

    collect = sub.add_parser("collect", help="수집원을 실행해 SQLite에 저장한다")
    collect.add_argument("--source", default="finlife", choices=sorted(ADAPTERS))
    collect.add_argument("--db", default=str(DEFAULT_DB_PATH))
    collect.add_argument("--raw-root", default=str(DEFAULT_RAW_ROOT))
    collect.add_argument(
        "--services",
        nargs="+",
        default=["depositProductsSearch", "savingProductsSearch"],
    )
    collect.add_argument(
        "--groups", nargs="+", default=["030300"],
        help="권역코드. 030300=저축은행, 020000=은행",
    )
    collect.set_defaults(func=_collect)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
