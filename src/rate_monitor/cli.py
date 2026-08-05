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
from rate_monitor.services.dashboard_service import (
    DEFAULT_SITE,
    DEFAULT_SUMMARY,
    DEFAULT_TEMPLATE,
    build_dashboard,
)
from rate_monitor.services.export_service import export_dataset
from rate_monitor.services.snapshot_service import create_snapshot
from rate_monitor.services.validation_service import run_validations

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


def _snapshot(args: argparse.Namespace) -> int:
    """작업본을 일관된 배포 스냅샷으로 굳힌다 (명세서 v3.1 §3)."""
    manifest = create_snapshot(
        Path(args.db), Path(args.publish_db), Path(args.manifest)
    )
    print(f"snapshot : {args.publish_db}")
    print(f"sha256   : {manifest.sha256[:16]}…")
    for table, count in sorted(manifest.row_counts.items()):
        print(f"  {table:22s} {count}")
    return 0


def _build_dashboard(args: argparse.Namespace) -> int:
    summary = build_dashboard(
        Path(args.db), Path(args.template), Path(args.site), Path(args.summary)
    )
    totals = summary["totals"]
    print(f"site    : {args.site}")
    print(f"summary : {args.summary}")
    print(f"totals  : {totals}")
    print(f"구·군    : {len(summary.get('by_district') or [])}개")
    return 0


def _validate(args: argparse.Namespace) -> int:
    """저장된 데이터가 계약을 지키는지 확인한다.

    게이트(`scripts/verify_gate.py`)는 배포 산출물 전체를 본다. 이쪽은 DB만
    보고 빨리 답한다. 수집 직후 손으로 확인할 때 쓴다.
    """
    checks = run_validations(Path(args.db))
    failed = [c for c in checks if not c.ok]
    for check in checks:
        mark = "PASS" if check.ok else "FAIL"
        print(f"  [{mark}] {check.name} — {check.detail}")
    print(f"  {len(checks) - len(failed)}/{len(checks)} 통과")
    return 1 if failed else 0


def _export(args: argparse.Namespace) -> int:
    """전체 조사 내용을 파일로 뽑는다."""
    written = export_dataset(Path(args.db), Path(args.out), formats=tuple(args.format))
    for path in written:
        print(f"  {path}  ({path.stat().st_size:,} bytes)")
    return 0


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

    snapshot = sub.add_parser("snapshot", help="배포용 스냅샷과 manifest를 만든다")
    snapshot.add_argument("--db", default=str(DEFAULT_DB_PATH))
    snapshot.add_argument("--publish-db", default="publish/rate_monitor.sqlite3")
    snapshot.add_argument("--manifest", default="publish/manifest.json")
    snapshot.set_defaults(func=_snapshot)

    dashboard = sub.add_parser("build-dashboard", help="정적 대시보드를 생성한다")
    dashboard.add_argument("--db", default="publish/rate_monitor.sqlite3")
    dashboard.add_argument("--template", default=str(DEFAULT_TEMPLATE))
    dashboard.add_argument("--site", default=str(DEFAULT_SITE))
    dashboard.add_argument("--summary", default=str(DEFAULT_SUMMARY))
    dashboard.set_defaults(func=_build_dashboard)

    validate = sub.add_parser("validate", help="저장된 데이터의 계약 위반을 찾는다")
    validate.add_argument("--db", default=str(DEFAULT_DB_PATH))
    validate.set_defaults(func=_validate)

    export = sub.add_parser("export", help="전체 조사 내용을 파일로 내보낸다")
    export.add_argument("--db", default="publish/rate_monitor.sqlite3")
    export.add_argument("--out", default="publish/export")
    export.add_argument(
        "--format", nargs="+", default=["csv", "json"], choices=["csv", "json"],
    )
    export.set_defaults(func=_export)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
