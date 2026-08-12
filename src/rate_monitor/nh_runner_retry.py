"""Decide whether a scheduled NH failure may be retried on a fresh runner.

This is deliberately narrower than the normal checkpoint recovery path. It is only
for a parent ``Collect rates`` run that reached NH, received no canonical raw
artifacts, ended with a terminal connect/timeout failure, and has no durable
checkpoint progress to resume.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from rate_monitor.collectors.nh_local.resumable import build_nh_checkpoint_context
from rate_monitor.db.models import CollectionRun
from rate_monitor.db.session import create_db_engine, make_session_factory
from rate_monitor.domain.enums import RunStatus
from rate_monitor.domain.schemas import CollectionRequest
from rate_monitor.services.resumable_acquisition import (
    AcquisitionSessionIdentity,
    RecoveryDecision,
    decide_recovery,
)
from rate_monitor.services.storage_service import (
    LocalObjectStore,
    ObjectStore,
    R2Config,
    StorageError,
    open_store,
)

KST = timezone(timedelta(hours=9))
_ALLOWED_FAILURE = re.compile(
    r"^NhRequestFailure: (?P<code>NETWORK_CONNECT|NETWORK_TIMEOUT):"
)


@dataclass(frozen=True)
class NhFreshRunnerDecision:
    eligible: bool
    reason_code: str
    cycle_date_kst: str
    collection_run_id: str | None
    failure_code: str | None
    raw_count: int | None
    checkpoint_reason: str | None
    checkpoint_completed_work_count: int | None

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True)


def _parse_github_time(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError(f"GitHub workflow 시간에는 timezone이 필요하다: {value!r}")
    return parsed.astimezone(UTC)


def _naive_utc(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None)


def _checkpoint_decision(
    store: ObjectStore,
    *,
    cycle_date_kst: str,
) -> RecoveryDecision:
    request = CollectionRequest(source_id="nh_local")
    context = build_nh_checkpoint_context(request, cycle_date_kst=cycle_date_kst)
    identity = AcquisitionSessionIdentity(
        source_id=context.source_id,
        cycle_date_kst=context.cycle_date_kst,
        request_fingerprint=context.request_fingerprint,
        acquisition_contract_version=context.acquisition_contract_version,
    )
    return decide_recovery(store, identity, attempt_failed=True)


def decide_nh_fresh_runner_retry(
    factory: sessionmaker,
    store: ObjectStore,
    *,
    parent_started_at: datetime,
    parent_finished_at: datetime,
) -> NhFreshRunnerDecision:
    """Return a fail-closed fresh-runner decision for one scheduled parent run."""
    start = parent_started_at.astimezone(UTC)
    finish = parent_finished_at.astimezone(UTC)
    if finish < start:
        raise ValueError("parent workflow 종료시각이 시작시각보다 빠르다")
    cycle_date = start.astimezone(KST).date().isoformat()

    with factory() as session:
        runs = list(
            session.scalars(
                select(CollectionRun)
                .where(
                    CollectionRun.source_id == "nh_local",
                    CollectionRun.started_at >= _naive_utc(start),
                    CollectionRun.started_at <= _naive_utc(finish),
                )
                .order_by(CollectionRun.started_at.asc(), CollectionRun.id.asc())
            )
        )

    if not runs:
        return NhFreshRunnerDecision(
            False,
            "NO_NH_ATTEMPT_IN_PARENT_RUN",
            cycle_date,
            None,
            None,
            None,
            None,
            None,
        )
    if len(runs) != 1:
        return NhFreshRunnerDecision(
            False,
            "MULTIPLE_NH_ATTEMPTS_IN_PARENT_RUN",
            cycle_date,
            None,
            None,
            None,
            None,
            None,
        )

    run = runs[0]
    if run.status != RunStatus.FAILED:
        return NhFreshRunnerDecision(
            False,
            "NH_STATUS_NOT_FAILED",
            cycle_date,
            run.id,
            None,
            run.raw_count,
            None,
            None,
        )
    if run.raw_count != 0:
        return NhFreshRunnerDecision(
            False,
            "NH_RAW_PROGRESS_PRESENT",
            cycle_date,
            run.id,
            None,
            run.raw_count,
            None,
            None,
        )

    match = _ALLOWED_FAILURE.match(run.message or "")
    if match is None:
        return NhFreshRunnerDecision(
            False,
            "NH_FAILURE_NOT_CONNECT_OR_TIMEOUT",
            cycle_date,
            run.id,
            None,
            run.raw_count,
            None,
            None,
        )
    failure_code = match.group("code")

    checkpoint = _checkpoint_decision(store, cycle_date_kst=cycle_date)
    if checkpoint.eligible:
        return NhFreshRunnerDecision(
            False,
            "CHECKPOINT_RECOVERY_ELIGIBLE",
            cycle_date,
            run.id,
            failure_code,
            run.raw_count,
            checkpoint.reason_code,
            checkpoint.completed_work_count,
        )
    if checkpoint.reason_code != "NO_DURABLE_PROGRESS":
        return NhFreshRunnerDecision(
            False,
            "CHECKPOINT_NOT_ZERO_PROGRESS",
            cycle_date,
            run.id,
            failure_code,
            run.raw_count,
            checkpoint.reason_code,
            checkpoint.completed_work_count,
        )

    return NhFreshRunnerDecision(
        True,
        "ELIGIBLE_NETWORK_ZERO_PROGRESS",
        cycle_date,
        run.id,
        failure_code,
        run.raw_count,
        checkpoint.reason_code,
        checkpoint.completed_work_count,
    )


def _store(local_root: str | None) -> ObjectStore:
    if local_root:
        return LocalObjectStore(Path(local_root))
    config = R2Config.from_env()
    if config is None:
        raise StorageError(
            "NH fresh-runner decision에는 checkpoint R2 설정이 필요하다: "
            + ", ".join(R2Config.ENV_KEYS)
        )
    return open_store(config)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m rate_monitor.nh_runner_retry")
    parser.add_argument("--db", required=True)
    parser.add_argument("--parent-start", required=True)
    parser.add_argument("--parent-end", required=True)
    parser.add_argument("--json", default=None)
    parser.add_argument(
        "--local-root",
        default=None,
        help="테스트용 checkpoint ObjectStore. 생략하면 R2 env를 요구한다",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        engine = create_db_engine(Path(args.db))
        factory = make_session_factory(engine)
        decision = decide_nh_fresh_runner_retry(
            factory,
            _store(args.local_root),
            parent_started_at=_parse_github_time(args.parent_start),
            parent_finished_at=_parse_github_time(args.parent_end),
        )
        body = decision.to_json() + "\n"
        if args.json:
            path = Path(args.json)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8")
        sys.stdout.write(body)
        return 0
    except (StorageError, ValueError) as exc:
        print(f"NH fresh-runner decision 오류: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
