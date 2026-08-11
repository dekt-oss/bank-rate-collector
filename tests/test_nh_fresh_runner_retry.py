from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker

from rate_monitor.collectors.nh_local.resumable import build_nh_checkpoint_context
from rate_monitor.db.models import Base, CollectionRun, Source
from rate_monitor.db.session import create_db_engine, make_session_factory
from rate_monitor.domain.enums import RunStatus
from rate_monitor.domain.schemas import CollectionRequest, RawArtifactData
from rate_monitor.nh_runner_retry import decide_nh_fresh_runner_retry
from rate_monitor.services.resumable_acquisition import (
    AcquisitionSessionIdentity,
    CheckpointArtifact,
    ResumableAcquisitionService,
)
from rate_monitor.services.storage_service import LocalObjectStore

PARENT_START = datetime(2026, 8, 11, 15, 17, tzinfo=UTC)
PARENT_END = PARENT_START + timedelta(hours=1)
RUN_STARTED = (PARENT_START + timedelta(minutes=5)).replace(tzinfo=None)


def _factory(tmp_path: Path) -> sessionmaker:
    engine = create_db_engine(tmp_path / "state.sqlite3")
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    with factory.begin() as session:
        session.add(
            Source(
                id="nh_local",
                name="NH",
                sector="nh_local",
                mode="http",
                source_role="secondary_official",
                trust_level="official_direct",
                priority=10,
                enabled=True,
                policy_status="allowed",
                coverage_status="partial",
                parser_version="0.1.0",
                created_at=RUN_STARTED,
                updated_at=RUN_STARTED,
            )
        )
    return factory


def _add_run(
    factory: sessionmaker,
    *,
    status: str = RunStatus.FAILED,
    raw_count: int = 0,
    message: str = (
        "NhRequestFailure: NETWORK_CONNECT: phase=preflight screen=SFDPW0161R "
        "attempt=4/4 retries=3 failures=NETWORK_CONNECT 3, NETWORK_TIMEOUT 1"
    ),
    started_at: datetime = RUN_STARTED,
) -> str:
    with factory.begin() as session:
        run = CollectionRun(
            source_id="nh_local",
            mode="http",
            started_at=started_at,
            finished_at=started_at + timedelta(minutes=1),
            status=status,
            query_context_json={"regions": [], "options": {}},
            raw_count=raw_count,
            parsed_count=0,
            valid_count=0,
            warning_count=0,
            error_count=0,
            message=message,
        )
        session.add(run)
        session.flush()
        return run.id


def _checkpoint_service(store: LocalObjectStore) -> ResumableAcquisitionService:
    cycle_date = PARENT_START.astimezone(UTC).astimezone(
        __import__("datetime").timezone(timedelta(hours=9))
    ).date().isoformat()
    context = build_nh_checkpoint_context(
        CollectionRequest(source_id="nh_local"), cycle_date_kst=cycle_date
    )
    return ResumableAcquisitionService(
        store,
        AcquisitionSessionIdentity(
            source_id=context.source_id,
            cycle_date_kst=context.cycle_date_kst,
            request_fingerprint=context.request_fingerprint,
            acquisition_contract_version=context.acquisition_contract_version,
        ),
    )


def _zero_progress_checkpoint(store: LocalObjectStore) -> None:
    service = _checkpoint_service(store)
    manifest = service.open("auto")
    service.mark_recoverable_failed(
        manifest,
        reason_code="RECOVERABLE_NETWORK",
        reason="preflight connection failed",
    )


def test_connect_zero_progress_is_eligible(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    run_id = _add_run(factory)
    store = LocalObjectStore(tmp_path / "objects")
    _zero_progress_checkpoint(store)

    decision = decide_nh_fresh_runner_retry(
        factory,
        store,
        parent_started_at=PARENT_START,
        parent_finished_at=PARENT_END,
    )

    assert decision.eligible is True
    assert decision.reason_code == "ELIGIBLE_NETWORK_ZERO_PROGRESS"
    assert decision.collection_run_id == run_id
    assert decision.failure_code == "NETWORK_CONNECT"
    assert decision.checkpoint_reason == "NO_DURABLE_PROGRESS"
    assert decision.checkpoint_completed_work_count == 0
    assert decision.cycle_date_kst == "2026-08-12"


def test_timeout_zero_progress_is_eligible(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    _add_run(
        factory,
        message=(
            "NhRequestFailure: NETWORK_TIMEOUT: phase=preflight screen=SFDPW0161R "
            "attempt=4/4 retries=3 failures=NETWORK_TIMEOUT 4"
        ),
    )
    store = LocalObjectStore(tmp_path / "objects")
    _zero_progress_checkpoint(store)

    decision = decide_nh_fresh_runner_retry(
        factory,
        store,
        parent_started_at=PARENT_START,
        parent_finished_at=PARENT_END,
    )

    assert decision.eligible is True
    assert decision.failure_code == "NETWORK_TIMEOUT"


@pytest.mark.parametrize(
    "message",
    [
        "NhRequestFailure: NETWORK_IO: phase=preflight failures=NETWORK_IO 4",
        "NhRequestFailure: NETWORK_PROTOCOL: phase=preflight failures=NETWORK_PROTOCOL 4",
        "NhRequestFailure: HTTP_SERVER_ERROR: phase=preflight failures=HTTP_SERVER_ERROR 4",
        "NhRequestFailure: NETWORK_UNKNOWN: phase=preflight failures=NETWORK_UNKNOWN 4",
        (
            "NhRequestFailure: RETRY_BUDGET_EXHAUSTED: phase=preflight "
            "failures=NETWORK_CONNECT 50"
        ),
        "SourceBlockedError: 차단 응답 403",
    ],
)
def test_other_terminal_failures_are_not_eligible(tmp_path: Path, message: str) -> None:
    factory = _factory(tmp_path)
    _add_run(factory, message=message)
    store = LocalObjectStore(tmp_path / "objects")
    _zero_progress_checkpoint(store)

    decision = decide_nh_fresh_runner_retry(
        factory,
        store,
        parent_started_at=PARENT_START,
        parent_finished_at=PARENT_END,
    )

    assert decision.eligible is False
    assert decision.reason_code == "NH_FAILURE_NOT_CONNECT_OR_TIMEOUT"


def test_raw_progress_is_not_eligible(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    _add_run(factory, raw_count=1)
    store = LocalObjectStore(tmp_path / "objects")
    _zero_progress_checkpoint(store)

    decision = decide_nh_fresh_runner_retry(
        factory,
        store,
        parent_started_at=PARENT_START,
        parent_finished_at=PARENT_END,
    )

    assert decision.eligible is False
    assert decision.reason_code == "NH_RAW_PROGRESS_PRESENT"


def test_durable_checkpoint_progress_stays_on_existing_resume_path(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    _add_run(factory)
    store = LocalObjectStore(tmp_path / "objects")
    service = _checkpoint_service(store)
    manifest = service.open("auto")
    manifest = service.flush(
        manifest,
        [
            CheckpointArtifact(
                work_key="directory:SFDPW0161R",
                artifact=RawArtifactData(
                    artifact_type="html",
                    content=b"directory",
                    filename="directory.html",
                    request_meta={},
                    schema_fingerprint="sha256:test",
                    source_role="secondary_official",
                    trust_level="official_direct",
                ),
            )
        ],
    )
    service.mark_recoverable_failed(
        manifest,
        reason_code="RECOVERABLE_NETWORK",
        reason="detail connection failed",
    )

    decision = decide_nh_fresh_runner_retry(
        factory,
        store,
        parent_started_at=PARENT_START,
        parent_finished_at=PARENT_END,
    )

    assert decision.eligible is False
    assert decision.reason_code == "CHECKPOINT_RECOVERY_ELIGIBLE"
    assert decision.checkpoint_completed_work_count == 1


def test_multiple_nh_attempts_in_parent_window_fail_closed(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    _add_run(factory)
    _add_run(factory, started_at=RUN_STARTED + timedelta(minutes=2))
    store = LocalObjectStore(tmp_path / "objects")
    _zero_progress_checkpoint(store)

    decision = decide_nh_fresh_runner_retry(
        factory,
        store,
        parent_started_at=PARENT_START,
        parent_finished_at=PARENT_END,
    )

    assert decision.eligible is False
    assert decision.reason_code == "MULTIPLE_NH_ATTEMPTS_IN_PARENT_RUN"


def test_no_nh_attempt_in_parent_window_is_noop(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    store = LocalObjectStore(tmp_path / "objects")

    decision = decide_nh_fresh_runner_retry(
        factory,
        store,
        parent_started_at=PARENT_START,
        parent_finished_at=PARENT_END,
    )

    assert decision.eligible is False
    assert decision.reason_code == "NO_NH_ATTEMPT_IN_PARENT_RUN"
