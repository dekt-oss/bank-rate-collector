"""rate-monitor CLI.

명세서 v3.1 §9.1: collect / build-dashboard / validate.
`serve`는 만들지 않는다 — Actions 실행형이라 로컬 서버를 볼 수 없다.
"""

import argparse
import asyncio
import sys
from pathlib import Path

from rate_monitor.collectors.finlife.adapter import FinlifeAdapter
from rate_monitor.collectors.kfcc.adapter import KfccAdapter
from rate_monitor.db.session import DEFAULT_DB_PATH, create_db_engine, make_session_factory
from rate_monitor.domain.schemas import CollectionRequest
from rate_monitor.services.collection_service import DEFAULT_RAW_ROOT, collect_source

ADAPTERS = {"finlife": FinlifeAdapter, "kfcc": KfccAdapter}


def _finlife_request(args: argparse.Namespace) -> CollectionRequest:
    return CollectionRequest(
        source_id=args.source,
        options={
            "services": tuple(args.services),
            "groups": tuple(args.groups),
        },
    )


def _default_request(args: argparse.Namespace) -> CollectionRequest:
    """지역 기반 수집원의 기본형. 구·군 목록을 regions로 넘긴다."""
    return CollectionRequest(
        source_id=args.source,
        regions=tuple(args.regions or ()),
    )


# 수집원마다 필요한 인자가 다르다. finlife의 services/groups를 모든 원천에
# 무조건 밀어 넣으면 지역 기반 수집원에서 뜻 없는 값이 실행 이력에 남는다.
REQUEST_BUILDERS = {"finlife": _finlife_request}


def _collect(args: argparse.Namespace) -> int:
    adapter_cls = ADAPTERS.get(args.source)
    if adapter_cls is None:
        print(f"알 수 없는 수집원: {args.source}", file=sys.stderr)
        return 2

    engine = create_db_engine(args.db)
    factory = make_session_factory(engine)
    build_request = REQUEST_BUILDERS.get(args.source, _default_request)
    request = build_request(args)
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
        help="finlife 전용. 권역코드. 030300=저축은행, 020000=은행",
    )
    collect.add_argument(
        "--regions", nargs="+", default=None,
        help="지역 기반 수집원 전용. 구·군 이름 (예: 중구 서구)",
    )
    collect.set_defaults(func=_collect)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
