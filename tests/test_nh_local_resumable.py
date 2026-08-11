"""NH durable acquisition resume contract — no external network/R2 required."""

import asyncio
from pathlib import Path

import pytest

from rate_monitor.collectors.base import SchemaChangedError, SourceBlockedError
from rate_monitor.collectors.nh_local import parser
from rate_monitor.collectors.nh_local.adapter import LIST_SCREEN, NhRequestFailure
from rate_monitor.collectors.nh_local.resumable import (
    NhResumableAdapter,
    build_nh_checkpoint_context,
    nh_request_fingerprint,
)
from rate_monitor.collectors.repeat_guard import RepeatGuard
from rate_monitor.domain.enums import ProductType
from rate_monitor.domain.schemas import CollectionRequest
from rate_monitor.services.resumable_acquisition import (
    AcquisitionSessionIdentity,
    CheckpointIncompatibleError,
    decide_recovery,
)
from rate_monitor.services.storage_service import LocalObjectStore

CYCLE = "2026-08-11"
OUTLETS = [
    parser.NhOutlet("100001", "가농협", "서울특별시 중구 1"),
    parser.NhOutlet("100002", "나농협", "서울특별시 중구 2"),
    parser.NhOutlet("100003", "다농협", "서울특별시 중구 3"),
]


def _request(*, scope: str = "전국") -> CollectionRequest:
    return CollectionRequest(
        source_id="nh_local",
        options={
            "scope": scope,
            "products": (ProductType.TERM_DEPOSIT,),
        },
    )


def _identity(request: CollectionRequest) -> AcquisitionSessionIdentity:
    context = build_nh_checkpoint_context(request, cycle_date_kst=CYCLE)
    return AcquisitionSessionIdentity(
        source_id=context.source_id,
        cycle_date_kst=context.cycle_date_kst,
        request_fingerprint=context.request_fingerprint,
        acquisition_contract_version=context.acquisition_contract_version,
    )


def _install_directory(monkeypatch) -> None:
    monkeypatch.setattr(parser, "parse_outlet_list", lambda html: list(OUTLETS))


def _body_for(brc: str) -> bytes:
    return f"<html><th>rate</th><p>{brc}</p></html>".encode()


def _run(adapter: NhResumableAdapter, request: CollectionRequest):
    return asyncio.run(adapter.fetch(request))


def test_resume_skips_durable_work_and_matches_fresh_artifact_set(
    tmp_path: Path, monkeypatch
) -> None:
    _install_directory(monkeypatch)
    request = _request()
    store = LocalObjectStore(tmp_path / "resume")
    first_calls: list[str] = []

    first = NhResumableAdapter(
        store,
        cycle_date_kst=CYCLE,
        sleep=lambda delay: asyncio.sleep(0),
        flush_items=1,
    )

    async def first_get(client, screen, params, *, phase):  # noqa: ANN001
        if screen == LIST_SCREEN:
            first_calls.append("directory")
            return b"<html><th>directory</th></html>"
        brc = params["brc"]
        first_calls.append(brc)
        if brc == "100003":
            cause = RuntimeError("simulated connection loss")
            raise NhRequestFailure(
                "NETWORK_CONNECT",
                phase=phase,
                screen=screen,
                attempt=3,
                max_attempts=3,
                cause=cause,
                retry_count=2,
                failure_reasons={"NETWORK_CONNECT": 3},
            ) from cause
        return _body_for(brc)

    monkeypatch.setattr(first, "_get", first_get)
    with pytest.raises(NhRequestFailure):
        _run(first, request)

    decision = decide_recovery(store, _identity(request), attempt_failed=True)
    assert decision.eligible is True
    assert decision.reason_code == "RECOVERABLE_NETWORK"
    assert decision.completed_work_count == 3  # directory + first two details
    assert first_calls == ["directory", "100001", "100002", "100003"]

    resumed_calls: list[str] = []
    resumed = NhResumableAdapter(
        store,
        cycle_date_kst=CYCLE,
        sleep=lambda delay: asyncio.sleep(0),
        flush_items=1,
    )

    async def resumed_get(client, screen, params, *, phase):  # noqa: ANN001
        assert screen != LIST_SCREEN, "frozen directory must not be refetched"
        brc = params["brc"]
        assert brc not in {"100001", "100002"}, "durable detail was refetched"
        resumed_calls.append(brc)
        return _body_for(brc)

    monkeypatch.setattr(resumed, "_get", resumed_get)
    resumed_artifacts = _run(resumed, request)
    assert resumed_calls == ["100003"]

    baseline_store = LocalObjectStore(tmp_path / "fresh")
    baseline = NhResumableAdapter(
        baseline_store,
        cycle_date_kst=CYCLE,
        resume_mode="fresh",
        sleep=lambda delay: asyncio.sleep(0),
        flush_items=1,
    )

    async def baseline_get(client, screen, params, *, phase):  # noqa: ANN001
        if screen == LIST_SCREEN:
            return b"<html><th>directory</th></html>"
        return _body_for(params["brc"])

    monkeypatch.setattr(baseline, "_get", baseline_get)
    baseline_artifacts = _run(baseline, request)

    def shape(artifacts):  # noqa: ANN001
        return [
            (artifact.filename, artifact.content, artifact.request_meta)
            for artifact in artifacts
        ]

    assert shape(resumed_artifacts) == shape(baseline_artifacts)


def test_directory_is_frozen_and_plan_change_fails_closed(tmp_path: Path, monkeypatch) -> None:
    _install_directory(monkeypatch)
    request = _request()
    store = LocalObjectStore(tmp_path / "objects")
    adapter = NhResumableAdapter(
        store,
        cycle_date_kst=CYCLE,
        sleep=lambda delay: asyncio.sleep(0),
        flush_items=1,
    )

    async def fail_after_directory(client, screen, params, *, phase):  # noqa: ANN001
        if screen == LIST_SCREEN:
            return b"<html><th>directory</th></html>"
        cause = RuntimeError("down")
        raise NhRequestFailure(
            "NETWORK_CONNECT",
            phase=phase,
            screen=screen,
            attempt=3,
            max_attempts=3,
            cause=cause,
            retry_count=2,
            failure_reasons={"NETWORK_CONNECT": 3},
        ) from cause

    monkeypatch.setattr(adapter, "_get", fail_after_directory)
    with pytest.raises(NhRequestFailure):
        _run(adapter, request)

    monkeypatch.setattr(
        parser,
        "parse_outlet_list",
        lambda html: [*OUTLETS, parser.NhOutlet("999999", "새농협", "서울특별시 중구 9")],
    )
    resumed = NhResumableAdapter(
        store,
        cycle_date_kst=CYCLE,
        sleep=lambda delay: asyncio.sleep(0),
    )

    async def must_not_fetch_directory(client, screen, params, *, phase):  # noqa: ANN001
        assert screen != LIST_SCREEN
        return _body_for(params["brc"])

    monkeypatch.setattr(resumed, "_get", must_not_fetch_directory)
    with pytest.raises(CheckpointIncompatibleError, match="work_plan_hash"):
        _run(resumed, request)

    decision = decide_recovery(store, _identity(request), attempt_failed=True)
    assert decision.eligible is False
    assert decision.reason_code == "ACQUISITION_CONTRACT_CHANGED"


def test_blocked_source_is_terminal_and_not_recoverable(tmp_path: Path, monkeypatch) -> None:
    _install_directory(monkeypatch)
    request = _request()
    store = LocalObjectStore(tmp_path / "objects")
    adapter = NhResumableAdapter(
        store,
        cycle_date_kst=CYCLE,
        sleep=lambda delay: asyncio.sleep(0),
    )

    async def blocked(client, screen, params, *, phase):  # noqa: ANN001
        if screen == LIST_SCREEN:
            return b"<html><th>directory</th></html>"
        raise SourceBlockedError("blocked by source")

    monkeypatch.setattr(adapter, "_get", blocked)
    with pytest.raises(SourceBlockedError):
        _run(adapter, request)

    decision = decide_recovery(store, _identity(request), attempt_failed=True)
    assert decision.eligible is False
    assert decision.reason_code == "SOURCE_BLOCKED"


def test_directory_schema_change_is_terminal_and_reason_is_preserved(
    tmp_path: Path, monkeypatch
) -> None:
    request = _request()
    store = LocalObjectStore(tmp_path / "objects")
    adapter = NhResumableAdapter(
        store,
        cycle_date_kst=CYCLE,
        sleep=lambda delay: asyncio.sleep(0),
    )

    async def list_only(client, screen, params, *, phase):  # noqa: ANN001
        assert screen == LIST_SCREEN
        return b"<html><th>changed directory</th></html>"

    monkeypatch.setattr(adapter, "_get", list_only)
    monkeypatch.setattr(
        parser,
        "parse_outlet_list",
        lambda html: (_ for _ in ()).throw(SchemaChangedError("directory changed")),
    )
    with pytest.raises(SchemaChangedError):
        _run(adapter, request)

    decision = decide_recovery(store, _identity(request), attempt_failed=True)
    assert decision.eligible is False
    assert decision.reason_code == "SOURCE_SCHEMA_CHANGED"


def test_repeat_guard_returns_received_partial_but_seals_resume(
    tmp_path: Path, monkeypatch
) -> None:
    _install_directory(monkeypatch)
    request = _request()
    store = LocalObjectStore(tmp_path / "objects")
    adapter = NhResumableAdapter(
        store,
        cycle_date_kst=CYCLE,
        sleep=lambda delay: asyncio.sleep(0),
        flush_items=1,
        guard_factory=lambda: RepeatGuard(limit=1),
    )

    async def repeated(client, screen, params, *, phase):  # noqa: ANN001
        if screen == LIST_SCREEN:
            return b"directory"
        return b"same-detail-body"

    monkeypatch.setattr(adapter, "_get", repeated)
    artifacts = _run(adapter, request)

    assert len(artifacts) == 3  # directory + two received detail responses
    assert adapter.fetch_alert
    assert "되풀이 한도 초과" in adapter.fetch_note
    decision = decide_recovery(store, _identity(request), attempt_failed=True)
    assert decision.eligible is False
    assert decision.reason_code == "GUARD_TRIPPED"


def test_request_fingerprint_changes_with_scope_and_product_contract() -> None:
    nationwide = nh_request_fingerprint(_request(scope="전국"))
    busan = nh_request_fingerprint(_request(scope="부산"))
    savings = nh_request_fingerprint(
        CollectionRequest(
            source_id="nh_local",
            options={
                "scope": "전국",
                "products": (ProductType.INSTALLMENT_SAVINGS,),
            },
        )
    )
    assert nationwide != busan
    assert nationwide != savings
