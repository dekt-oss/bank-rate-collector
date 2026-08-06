"""rate-monitor CLI.

명세서 v3.1 §9.1: collect / build-dashboard / validate.
`serve`는 만들지 않는다 — Actions 실행형이라 로컬 서버를 볼 수 없다.
"""

import argparse
import asyncio
import sys
import tempfile
from pathlib import Path

from rate_monitor.collectors.bok_ecos.adapter import BokEcosAdapter
from rate_monitor.collectors.cu.adapter import CuAdapter
from rate_monitor.collectors.finlife.adapter import (
    FinlifeBankAdapter,
    FinlifeSavingsBankAdapter,
)
from rate_monitor.collectors.fsb.adapter import FsbAdapter
from rate_monitor.collectors.kfcc.adapter import KfccAdapter
from rate_monitor.collectors.nh_local.adapter import NhLocalAdapter
from rate_monitor.db.session import DEFAULT_DB_PATH, create_db_engine, make_session_factory
from rate_monitor.domain.schemas import CollectionRequest
from rate_monitor.services.collection_service import DEFAULT_RAW_ROOT, collect_source
from rate_monitor.services.dashboard_service import (
    DEFAULT_PUBLIC_SITE,
    DEFAULT_PUBLIC_TEMPLATE,
    DEFAULT_SITE,
    DEFAULT_SUMMARY,
    DEFAULT_TEMPLATE,
    build_dashboard,
)
from rate_monitor.services.export_service import export_dataset
from rate_monitor.services.indicator_service import collect_indicator
from rate_monitor.services.site_service import DEFAULT_OUT as DEFAULT_SITE_OUT
from rate_monitor.services.site_service import DEFAULT_TEMPLATE as DEFAULT_SITE_TEMPLATE
from rate_monitor.services.site_service import build_site
from rate_monitor.services.snapshot_service import create_snapshot
from rate_monitor.services.storage_service import (
    CURRENT_KEY,
    SNAPSHOT_PREFIX,
    LocalObjectStore,
    R2Config,
    SnapshotRef,
    StorageError,
    check_round_trip,
    load_backend,
    open_store,
    restore_snapshot,
    upload_snapshot,
)
from rate_monitor.services.validation_service import run_validations

ADAPTERS = {
    # finlife는 권역마다 소스가 갈린다 (v4 §6.2). 옛 이름 `finlife`는
    # 더 받지 않는다 — 그 이름으로 돌리면 어느 권역인지 알 수 없다.
    "finlife_savings_bank": FinlifeSavingsBankAdapter,
    "finlife_bank": FinlifeBankAdapter,
    "fsb": FsbAdapter,
    "cu": CuAdapter,
    "kfcc": KfccAdapter,
    "nh_local": NhLocalAdapter,
}

# 지표 수집원. 금리와 저장 표가 달라 오케스트레이터도 다르다 (v4 §7.1).
INDICATOR_ADAPTERS = {
    "bok_ecos": BokEcosAdapter,
}


def _finlife_request(args: argparse.Namespace) -> CollectionRequest:
    """권역은 어댑터가 안다. `--groups`를 안 주면 넘기지 않는다.

    예전에는 `--groups`의 기본값이 `030300`이라, 그 값이 어댑터 종류와
    상관없이 항상 실려 갔다. 그래서 `--source finlife_bank`를 그냥 돌리면
    저축은행 권역을 요청하는 꼴이 되어 어댑터가 거부했다.

        finlife_bank가 맡지 않은 권역: ['030300']

    이제 안 주면 비운다. 어댑터가 자기 권역을 쓴다.
    """
    options: dict[str, tuple[str, ...]] = {"services": tuple(args.services)}
    if args.groups:
        options["groups"] = tuple(args.groups)
    return CollectionRequest(source_id=args.source, options=options)


def _default_request(args: argparse.Namespace) -> CollectionRequest:
    """지역 기반 수집원의 기본형.

    지역을 직접 적으면 그것만, `--scope`를 주면 config의 그 범위를, 둘 다
    없으면 config의 `default_scope`를 쓴다.
    """
    options: dict[str, str] = {}
    if args.scope:
        options["scope"] = args.scope
    return CollectionRequest(
        source_id=args.source,
        regions=tuple(args.regions or ()),
        options=options,
    )


def _nh_local_request(args: argparse.Namespace) -> CollectionRequest:
    """농·축협은 `--regions`를 받지 않는다.

    원천에 지역 요청 인자가 없다. 명부가 통째로 오고 범위는 주소로 거른다.
    `--regions 부산`을 실행 이력에 남기면 그 값이 요청에 갔던 것처럼 보인다.
    """
    if args.regions:
        raise ValueError(
            "nh_local은 --regions를 쓰지 않는다. 원천에 지역 인자가 없으므로 "
            "--scope로 고른다 (전국·부산·수도권)"
        )
    options: dict[str, str] = {}
    if args.scope:
        options["scope"] = args.scope
    return CollectionRequest(source_id=args.source, options=options)


# 수집원마다 필요한 인자가 다르다. finlife의 services/groups를 모든 원천에
# 무조건 밀어 넣으면 지역 기반 수집원에서 뜻 없는 값이 실행 이력에 남는다.
REQUEST_BUILDERS = {
    "finlife_savings_bank": _finlife_request,
    "finlife_bank": _finlife_request,
    "nh_local": _nh_local_request,
}


def _collect(args: argparse.Namespace) -> int:
    if args.source in INDICATOR_ADAPTERS:
        return _collect_indicator(args)

    adapter_cls = ADAPTERS.get(args.source)
    if adapter_cls is None:
        print(f"알 수 없는 수집원: {args.source}", file=sys.stderr)
        return 2

    engine = create_db_engine(args.db)
    factory = make_session_factory(engine)
    build_request = REQUEST_BUILDERS.get(args.source, _default_request)
    try:
        request = build_request(args)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
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


def _collect_indicator(args: argparse.Namespace) -> int:
    """참고지표 수집 (v4 §7). 금리와 저장 표가 다르다."""
    engine = create_db_engine(args.db)
    factory = make_session_factory(engine)
    result = asyncio.run(
        collect_indicator(
            INDICATOR_ADAPTERS[args.source](),
            CollectionRequest(source_id=args.source),
            factory,
            raw_root=Path(args.raw_root),
        )
    )
    print(f"run_id      : {result.run_id}")
    print(f"status      : {result.status}")
    print(f"raw/parsed  : {result.fetched} / {result.parsed}")
    print(f"새/그대로   : {result.stored} / {result.unchanged}")
    print(f"warnings    : {result.warnings}")
    print(f"message     : {result.message}")
    # no_change는 실패가 아니다. 기준금리는 몇 달씩 안 바뀐다.
    return 0 if result.status in ("success", "partial", "no_change") else 1


def _snapshot(args: argparse.Namespace) -> int:
    """작업본을 일관된 배포 스냅샷으로 굳힌다 (명세서 v3.1 §3)."""
    manifest = create_snapshot(
        Path(args.db), Path(args.publish_db), Path(args.manifest)
    )
    print(f"snapshot : {args.publish_db}")
    print(f"sha256   : {manifest.sqlite_sha256[:16]}…")
    for table, count in sorted(manifest.row_counts.items()):
        print(f"  {table:22s} {count}")
    return 0


def _build_dashboard(args: argparse.Namespace) -> int:
    summary = build_dashboard(
        Path(args.db), Path(args.template), Path(args.site), Path(args.summary),
        Path(args.public_template), Path(args.public_site),
    )
    totals = summary["totals"]
    print(f"site    : {args.site}")
    print(f"public  : {args.public_site}")
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


def _storage_store(args: argparse.Namespace):
    """R2 또는 로컬 디렉터리. 후자는 R2 없이 전 구간을 돌려 보기 위한 것이다."""
    if args.local_root:
        return LocalObjectStore(Path(args.local_root))
    config = R2Config.from_env()
    if config is None:
        raise StorageError(
            "R2 시크릿이 없다. 실제 R2에 붙으려면 "
            f"{', '.join(R2Config.ENV_KEYS)}를 넣거나, 시험용이면 --local-root를 준다"
        )
    return open_store(config)


def _storage(args: argparse.Namespace) -> int:
    """상태 DB 저장소를 다룬다 (선행 수정안 v1 §6).

    `status`와 `verify`는 아무것도 바꾸지 않는다. 전환을 결정하기 전에
    지금 상태를 확인하는 용도다.
    """
    choice = load_backend(Path(args.config))
    print(f"backend : {choice.backend.value}  ({choice.source})")

    if args.action == "check":
        # 자격증명만 보지 않는다. 실제로 쓰고 읽고 지워 봐야 "붙기는 하는데
        # 못 쓰는" 상태를 안 넘긴다.
        store = _storage_store(args)
        result = check_round_trip(store)
        for label, detail in result["steps"]:
            print(f"  [{label:9s}] {detail}")
        print(f"\n  왕복 확인 — {result['bytes']:,} bytes, sha256 {result['sha256'][:16]}…")
        return 0

    if args.action == "status":
        secrets = R2Config.from_env()
        print(f"R2 시크릿: {'있음' if secrets else '없음'}")
        if not (secrets or args.local_root):
            print("R2 저장소를 볼 수 없다. --local-root를 주거나 시크릿을 넣는다")
            return 0
        store = _storage_store(args)
        if not store.exists(CURRENT_KEY):
            print(f"{CURRENT_KEY} 없음 — 아직 한 번도 올린 적이 없다")
            return 0
        ref = SnapshotRef.from_json(store.get(CURRENT_KEY))
        print(f"current : {ref.object_key}")
        print(f"  생성   : {ref.generated_at}")
        print(f"  압축   : {ref.compressed_bytes:,} bytes  (원본 {ref.sqlite_bytes:,})")
        print(f"  무결성 : {ref.integrity_check}, fk 위반 {ref.foreign_key_check_violations}")
        print(f"  행 수  : {ref.row_counts}")
        print(f"  보관   : 스냅샷 {len(store.list(SNAPSHOT_PREFIX))}개")
        return 0

    store = _storage_store(args)
    work = Path(args.work_dir)

    if args.action in ("upload", "migrate"):
        ref = upload_snapshot(store, Path(args.db), work)
        ratio = ref.compressed_bytes / ref.sqlite_bytes if ref.sqlite_bytes else 0
        print(f"올림    : {ref.object_key}")
        print(f"  크기   : {ref.sqlite_bytes:,} → {ref.compressed_bytes:,} bytes"
              f"  ({ratio:.1%})")
        print(f"  해시   : {ref.sha256}")
        print(f"  행 수  : {ref.row_counts}")
        print("  검증   : 다시 받아 해시·무결성·행 수까지 대조했다")
        if args.action == "migrate":
            print("\n다음: `storage verify`로 한 번 더 확인한 뒤")
            print("config/storage.yaml의 backend를 r2_migration으로 바꾼다")
        return 0

    if args.action == "verify":
        # 받아서 확인만 하고 지운다. 여기서 남기면 그게 진짜 DB인 줄 알고
        # 누가 쓰기 시작한다.
        with tempfile.TemporaryDirectory() as tmp:
            ref = restore_snapshot(store, Path(tmp) / "verify.sqlite3", Path(tmp))
        print(f"확인    : {ref.object_key}")
        print("  해시   : 기록과 일치")
        print(f"  무결성 : {ref.integrity_check}, fk 위반 {ref.foreign_key_check_violations}")
        print(f"  행 수  : {ref.row_counts}")
        return 0

    ref = restore_snapshot(store, Path(args.dest), work)
    print(f"복원    : {args.dest}")
    print(f"  출처   : {ref.object_key}  ({ref.generated_at})")
    print(f"  행 수  : {ref.row_counts}")
    return 0


def _build_site(args: argparse.Namespace) -> int:
    """공개 웹사이트 한 벌을 만든다.

    `build-dashboard`가 만드는 화면은 데이터를 HTML 안에 통째로 박는다.
    아티팩트로 공유할 때는 그래야 했지만 진짜 호스팅에 올리면 화면이 무거워
    지기만 한다. 이쪽은 화면과 데이터를 나눠 쓴다.
    """
    manifest = build_site(
        Path(args.db),
        Path(args.template),
        Path(args.out),
        export_dir=Path(args.export_dir) if args.export_dir else None,
    )
    print(f"out     : {args.out}")
    print(f"page    : {manifest.page_bytes:,} bytes")
    print(f"table   : {manifest.data_bytes:,} bytes  ({manifest.rows:,} rows)")
    for name in manifest.files:
        print(f"  {name}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rate-monitor")
    sub = parser.add_subparsers(dest="command", required=True)

    collect = sub.add_parser("collect", help="수집원을 실행해 SQLite에 저장한다")
    collect.add_argument(
        "--source", default="finlife_savings_bank",
        choices=sorted({*ADAPTERS, *INDICATOR_ADAPTERS}),
    )
    collect.add_argument("--db", default=str(DEFAULT_DB_PATH))
    collect.add_argument("--raw-root", default=str(DEFAULT_RAW_ROOT))
    collect.add_argument(
        "--services",
        nargs="+",
        default=["depositProductsSearch", "savingProductsSearch"],
    )
    collect.add_argument(
        "--groups", nargs="+", default=None,
        help="finlife 전용. 권역코드. 생략하면 수집원이 맡은 권역을 쓴다 "
             "(finlife_savings_bank=030300, finlife_bank=020000)",
    )
    collect.add_argument(
        "--regions", nargs="+", default=None,
        help="지역 기반 수집원 전용. 지역 이름 (예: 부산 경남). "
             "생략하면 --scope를 따른다",
    )
    collect.add_argument(
        "--scope", default=None,
        help="지역 기반 수집원 전용. config/regions.yaml의 수집 범위 이름 "
             "(전국·부산·수도권). 생략하면 config의 default_scope",
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
    dashboard.add_argument(
        "--public-template", default=str(DEFAULT_PUBLIC_TEMPLATE),
        help="공개용 전체 조회 화면 템플릿",
    )
    dashboard.add_argument(
        "--public-site", default=str(DEFAULT_PUBLIC_SITE),
        help="공개용 전체 조회 화면 출력 경로",
    )
    dashboard.set_defaults(func=_build_dashboard)

    site = sub.add_parser("build-site", help="배포용 공개 웹사이트를 생성한다")
    site.add_argument("--db", default="publish/rate_monitor.sqlite3")
    site.add_argument("--template", default=str(DEFAULT_SITE_TEMPLATE))
    site.add_argument("--out", default=str(DEFAULT_SITE_OUT))
    site.add_argument(
        "--export-dir", default="publish/export",
        help="여기 있는 CSV·JSON을 data/로 복사해 내려받기 링크가 가리키게 한다",
    )
    site.set_defaults(func=_build_site)

    # 상태 DB 저장소 (선행 수정안 v1 §6).
    #
    # status와 verify는 아무것도 바꾸지 않는다. R2 계정이 생긴 뒤 전환을
    # 결정하기 전에 이 둘로 지금 상태를 본다.
    storage = sub.add_parser("storage", help="상태 DB 저장소를 다룬다 (R2)")
    storage.add_argument(
        "action",
        choices=["check", "status", "upload", "restore", "migrate", "verify"],
        help="check=쓰기·읽기·삭제 왕복 시험, status=현황만 본다, "
             "upload=올린다, restore=받는다, "
             "migrate=기존 GitHub DB를 R2로 옮긴다, verify=받아서 확인만 한다",
    )
    storage.add_argument("--db", default="publish/rate_monitor.sqlite3",
                         help="upload·migrate가 올릴 DB")
    storage.add_argument("--dest", default="work/rate_monitor.sqlite3",
                         help="restore가 쓸 자리")
    storage.add_argument("--config", default="config/storage.yaml")
    storage.add_argument("--work-dir", default="work/storage",
                         help="압축·검증에 쓰는 임시 자리")
    storage.add_argument(
        "--local-root", default=None,
        help="R2 대신 이 디렉터리를 저장소처럼 쓴다. 시크릿 없이 전 구간을 "
             "돌려 볼 때 쓴다",
    )
    storage.set_defaults(func=_storage)

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
    try:
        return args.func(args)
    except StorageError as exc:
        # 저장소 실패는 설정이 틀렸거나 R2가 안 되는 것이고, 둘 다 사람이
        # 읽고 고칠 문제다. traceback은 그걸 가린다.
        print(f"저장소 오류: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
