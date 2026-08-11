"""Machine-readable checkpoint operations used by collection workflows."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rate_monitor.collectors.kfcc.resumable import build_kfcc_checkpoint_context
from rate_monitor.collectors.nh_local.resumable import build_nh_checkpoint_context
from rate_monitor.domain.schemas import CollectionRequest
from rate_monitor.services.resumable_acquisition import (
    CHECKPOINT_CONTRACT_VERSION,
    AcquisitionSessionIdentity,
    decide_recovery,
)
from rate_monitor.services.storage_service import (
    LocalObjectStore,
    R2Config,
    StorageError,
    open_store,
)
from rate_monitor.services.workflow_context import resolve_cycle_date_kst


def _store(local_root: str | None):
    if local_root:
        return LocalObjectStore(Path(local_root))
    config = R2Config.from_env()
    if config is None:
        raise StorageError(
            "checkpoint R2 시크릿이 없다. 실제 R2는 "
            f"{', '.join(R2Config.ENV_KEYS)}가 필요하고, 시험은 --local-root를 쓴다"
        )
    return open_store(config)


def _prepare_context(args: argparse.Namespace) -> int:
    cycle_date = args.cycle_date or resolve_cycle_date_kst()
    options = {"scope": args.scope} if args.scope else {}
    if args.source == "nh_local":
        if args.regions:
            raise ValueError("nh_local prepare-context는 --regions를 쓰지 않는다")
        request = CollectionRequest(source_id="nh_local", options=options)
        context = build_nh_checkpoint_context(request, cycle_date_kst=cycle_date)
    elif args.source == "kfcc":
        request = CollectionRequest(
            source_id="kfcc",
            regions=tuple(args.regions or ()),
            options=options,
        )
        context = build_kfcc_checkpoint_context(request, cycle_date_kst=cycle_date)
    else:  # argparse choices should make this unreachable.
        raise ValueError(f"prepare-context가 지원하지 않는 source: {args.source}")
    body = json.dumps(context.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.json:
        path = Path(args.json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    sys.stdout.write(body)
    return 0


def _recovery_decision(args: argparse.Namespace) -> int:
    identity = AcquisitionSessionIdentity(
        source_id=args.source,
        cycle_date_kst=args.cycle_date,
        request_fingerprint=args.request_fingerprint,
        checkpoint_contract_version=args.checkpoint_contract_version,
        acquisition_contract_version=args.acquisition_contract_version,
    )
    decision = decide_recovery(
        _store(args.local_root), identity, attempt_failed=args.attempt_failed
    )
    body = decision.to_json() + "\n"
    if args.json:
        path = Path(args.json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    sys.stdout.write(body)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rate-monitor-checkpoint")
    sub = parser.add_subparsers(dest="action", required=True)

    prepare = sub.add_parser(
        "prepare-context",
        help="NH/KFCC source command와 recovery decision이 공유할 identity를 만든다",
    )
    prepare.add_argument("--source", required=True, choices=["nh_local", "kfcc"])
    prepare.add_argument("--scope", default=None)
    prepare.add_argument(
        "--regions",
        nargs="+",
        default=None,
        help="KFCC만 지원. 직접 지정한 r1 지역 목록",
    )
    prepare.add_argument(
        "--cycle-date", default=None,
        help="생략하면 GitHub current run의 run_started_at을 KST 날짜로 변환",
    )
    prepare.add_argument("--json", default=None)
    prepare.set_defaults(func=_prepare_context)

    recovery = sub.add_parser(
        "recovery-decision",
        help="same-cycle active checkpoint를 검증해 자동 복구 가능 여부를 JSON으로 낸다",
    )
    recovery.add_argument("--source", required=True, choices=["nh_local", "kfcc"])
    recovery.add_argument(
        "--cycle-date",
        required=True,
        help="workflow run_started_at 기준 KST YYYY-MM-DD",
    )
    recovery.add_argument("--request-fingerprint", required=True)
    recovery.add_argument(
        "--checkpoint-contract-version", type=int, default=CHECKPOINT_CONTRACT_VERSION
    )
    recovery.add_argument("--acquisition-contract-version", type=int, default=1)
    recovery.add_argument(
        "--attempt-failed",
        action="store_true",
        help="first source attempt가 이미 failure로 끝났음을 caller가 확인했다",
    )
    recovery.add_argument("--json", default=None, help="동일 JSON을 저장할 경로")
    recovery.add_argument(
        "--local-root",
        default=None,
        help="테스트용 ObjectStore 디렉터리. 생략하면 R2 env를 요구한다",
    )
    recovery.set_defaults(func=_recovery_decision)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (StorageError, ValueError) as exc:
        print(f"checkpoint 오류: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
