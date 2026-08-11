"""KFCC durable acquisition resume contract — no external network/R2 required."""

import asyncio
from pathlib import Path

import pytest

from rate_monitor.collectors.base import SchemaChangedError, SourceBlockedError
from rate_monitor.collectors.kfcc import parser
from rate_monitor.collectors.kfcc.adapter import KfccRequestFailure
from rate_monitor.collectors.kfcc.resumable import (
    KfccResumableAdapter,
    build_kfcc_checkpoint_context,
    kfcc_request_fingerprint,
)
from rate_monitor.collectors.repeat_guard import RepeatGuard
from rate_monitor.domain.schemas import CollectionRequest
from rate_monitor.services.resumable_acquisition import (
    AcquisitionSessionIdentity,
    CheckpointIncompatibleError,
    decide_recovery,
)
from rate_monitor.services.storage_service import LocalObjectStore

CYCLE = "2026-08-11"
ROWS = {
    "부산": [
        {
            "gmgoCd": "100",
            "gmgoNm": "가금고",
            "divCd": "001",
            "divNm": "본점",
            "gmgoType": "지역",
            "addr": "부산 중구 1",
            "r1": "부산",
            "r2": "중구",
        },
        {
            "gmgoCd": "200",
            "gmgoNm": "나금고",
            "divCd": "001",
            "divNm": "본점",
            "gmgoType": "지역",
            "addr": "부산 서구 1",
            "r1": "부산",
            "r2": "서구",
        },
    ],
    "경남": [
        {
            "gmgoCd": "100",
            "gmgoNm": "가금고",
            "divCd": "002",
            "divNm": "경남지점",
            "gmgoType": "지역",
            "addr": "경남 창원시 1",
            "r1": "경남",
            "r2": "창원시",
        },
        {
            "gmgoCd": "300",
            "gmgoNm": "다금고",
            "divCd": "001",
            "divNm": "본점",
            "gmgoType": "지역",
            "addr": "경남 김해시 1",
            "r1": "경남",
            "r2": "김해시",
        },
    ],
}


def _request(*, regions=("부산", "경남"), groups=("13",)) -> CollectionRequest:
    return CollectionRequest(
        source_id="kfcc",
        regions=regions,
        options={"groups": groups},
    )


def _identity(request: CollectionRequest) -> AcquisitionSessionIdentity:
    context = build_kfcc_checkpoint_context(request, cycle_date_kst=CYCLE)
    return AcquisitionSessionIdentity(
        source_id=context.source_id,
        cycle_date_kst=context.cycle_date_kst,
        request_fingerprint=context.request_fingerprint,
        acquisition_contract_version=context.acquisition_contract_version,
    )


def _install_parser(monkeypatch, rows=None) -> None:
    current = rows or ROWS

    def fake_parse(html: str):
        region = html.removeprefix("LIST:")
        return [dict(row) for row in current[region]]

    monkeypatch.setattr(parser, "parse_list", fake_parse)
    monkeypatch.setattr(parser, "check_list_schema", lambda html: [])
    monkeypatch.setattr(parser, "schema_fingerprint", lambda html: "fp-rate")


def _run(adapter: KfccResumableAdapter, request: CollectionRequest):
    return asyncio.run(adapter.fetch(request))


def _failure(*, gmgo_cd: str) -> KfccRequestFailure:
    cause = RuntimeError("simulated connection loss")
    return KfccRequestFailure(
        "NETWORK_CONNECT",
        phase="rate",
        request_label=f"gmgoCd={gmgo_cd} gubuncode=13",
        attempt=3,
        max_attempts=3,
        cause=cause,
        retry_count=2,
        failure_reasons={"NETWORK_CONNECT": 3},
    )


def _shape(artifacts):  # noqa: ANN001
    return [
        (artifact.filename, artifact.content, artifact.request_meta)
        for artifact in artifacts
    ]


def test_resume_skips_durable_lists_and_rates_and_matches_fresh(
    tmp_path: Path, monkeypatch
) -> None:
    _install_parser(monkeypatch)
    request = _request()
    store = LocalObjectStore(tmp_path / "resume")
    first_calls: list[str] = []
    first = KfccResumableAdapter(
        store,
        cycle_date_kst=CYCLE,
        sleep=lambda delay: asyncio.sleep(0),
        flush_items=1,
    )

    async def first_get(client, url, params):  # noqa: ANN001
        if url.endswith("list.do"):
            region = params["r1"]
            first_calls.append(f"list:{region}")
            return f"LIST:{region}".encode()
        gmgo_cd = params["OPEN_TRMID"]
        first_calls.append(f"rate:{gmgo_cd}")
        if gmgo_cd == "300":
            raise _failure(gmgo_cd=gmgo_cd)
        return f"RATE:{gmgo_cd}:{params['gubuncode']}".encode()

    monkeypatch.setattr(first, "_get", first_get)
    with pytest.raises(KfccRequestFailure):
        _run(first, request)

    decision = decide_recovery(store, _identity(request), attempt_failed=True)
    assert decision.eligible is True
    assert decision.reason_code == "RECOVERABLE_NETWORK"
    assert decision.completed_work_count == 4  # two lists + rates for 100 and 200
    assert first_calls == [
        "list:부산",
        "list:경남",
        "rate:100",
        "rate:200",
        "rate:300",
    ]

    resumed_calls: list[str] = []
    resumed = KfccResumableAdapter(
        store,
        cycle_date_kst=CYCLE,
        sleep=lambda delay: asyncio.sleep(0),
        flush_items=1,
    )

    async def resumed_get(client, url, params):  # noqa: ANN001
        assert not url.endswith("list.do"), "frozen regional lists must not be refetched"
        gmgo_cd = params["OPEN_TRMID"]
        assert gmgo_cd == "300", "durable rate work was refetched"
        resumed_calls.append(gmgo_cd)
        return f"RATE:{gmgo_cd}:{params['gubuncode']}".encode()

    monkeypatch.setattr(resumed, "_get", resumed_get)
    resumed_artifacts = _run(resumed, request)
    assert resumed_calls == ["300"]

    baseline = KfccResumableAdapter(
        LocalObjectStore(tmp_path / "fresh"),
        cycle_date_kst=CYCLE,
        resume_mode="fresh",
        sleep=lambda delay: asyncio.sleep(0),
        flush_items=1,
    )

    async def baseline_get(client, url, params):  # noqa: ANN001
        if url.endswith("list.do"):
            return f"LIST:{params['r1']}".encode()
        return f"RATE:{params['OPEN_TRMID']}:{params['gubuncode']}".encode()

    monkeypatch.setattr(baseline, "_get", baseline_get)
    baseline_artifacts = _run(baseline, request)
    assert _shape(resumed_artifacts) == _shape(baseline_artifacts)

    rate_100 = next(
        artifact for artifact in resumed_artifacts
        if artifact.request_meta.get("gmgoCd") == "100"
    )
    assert rate_100.request_meta["outlet"] == ROWS["부산"][0]
    assert rate_100.request_meta["outlet_directory"] == [
        ROWS["부산"][0],
        ROWS["경남"][0],
    ]


def test_frozen_directory_plan_change_fails_closed(tmp_path: Path, monkeypatch) -> None:
    _install_parser(monkeypatch)
    request = _request()
    store = LocalObjectStore(tmp_path / "objects")
    first = KfccResumableAdapter(
        store,
        cycle_date_kst=CYCLE,
        sleep=lambda delay: asyncio.sleep(0),
        flush_items=1,
    )

    async def fail_first_rate(client, url, params):  # noqa: ANN001
        if url.endswith("list.do"):
            return f"LIST:{params['r1']}".encode()
        raise _failure(gmgo_cd=params["OPEN_TRMID"])

    monkeypatch.setattr(first, "_get", fail_first_rate)
    with pytest.raises(KfccRequestFailure):
        _run(first, request)

    changed = {key: [dict(row) for row in rows] for key, rows in ROWS.items()}
    changed["경남"].append(
        {
            "gmgoCd": "999",
            "gmgoNm": "새금고",
            "divCd": "001",
            "divNm": "본점",
            "gmgoType": "지역",
            "addr": "경남 진주시 1",
            "r1": "경남",
            "r2": "진주시",
        }
    )
    _install_parser(monkeypatch, changed)
    resumed = KfccResumableAdapter(
        store,
        cycle_date_kst=CYCLE,
        sleep=lambda delay: asyncio.sleep(0),
    )

    async def must_not_fetch_list(client, url, params):  # noqa: ANN001
        assert not url.endswith("list.do")
        return b"RATE"

    monkeypatch.setattr(resumed, "_get", must_not_fetch_list)
    with pytest.raises(CheckpointIncompatibleError, match="work_plan_hash"):
        _run(resumed, request)

    decision = decide_recovery(store, _identity(request), attempt_failed=True)
    assert decision.eligible is False
    assert decision.reason_code == "ACQUISITION_CONTRACT_CHANGED"


def test_blocked_source_is_terminal_and_not_recoverable(tmp_path: Path, monkeypatch) -> None:
    _install_parser(monkeypatch)
    request = _request()
    store = LocalObjectStore(tmp_path / "objects")
    adapter = KfccResumableAdapter(
        store,
        cycle_date_kst=CYCLE,
        sleep=lambda delay: asyncio.sleep(0),
        flush_items=1,
    )

    async def blocked(client, url, params):  # noqa: ANN001
        if url.endswith("list.do"):
            return f"LIST:{params['r1']}".encode()
        raise SourceBlockedError("blocked by source")

    monkeypatch.setattr(adapter, "_get", blocked)
    with pytest.raises(SourceBlockedError):
        _run(adapter, request)

    decision = decide_recovery(store, _identity(request), attempt_failed=True)
    assert decision.eligible is False
    assert decision.reason_code == "SOURCE_BLOCKED"


def test_list_schema_change_is_terminal_and_raw_evidence_is_sealed(
    tmp_path: Path, monkeypatch
) -> None:
    _install_parser(monkeypatch)
    request = _request(regions=("부산",))
    store = LocalObjectStore(tmp_path / "objects")
    adapter = KfccResumableAdapter(
        store,
        cycle_date_kst=CYCLE,
        sleep=lambda delay: asyncio.sleep(0),
        flush_items=100,
    )

    async def list_only(client, url, params):  # noqa: ANN001
        return b"LIST:부산"

    monkeypatch.setattr(adapter, "_get", list_only)
    monkeypatch.setattr(
        parser,
        "check_list_schema",
        lambda html: (_ for _ in ()).throw(SchemaChangedError("directory changed")),
    )
    with pytest.raises(SchemaChangedError):
        _run(adapter, request)

    decision = decide_recovery(store, _identity(request), attempt_failed=True)
    assert decision.eligible is False
    assert decision.reason_code == "SOURCE_SCHEMA_CHANGED"


def test_repeat_guard_flushes_received_partial_and_disables_resume(
    tmp_path: Path, monkeypatch
) -> None:
    _install_parser(monkeypatch)
    request = _request(groups=("13",))
    store = LocalObjectStore(tmp_path / "objects")
    adapter = KfccResumableAdapter(
        store,
        cycle_date_kst=CYCLE,
        sleep=lambda delay: asyncio.sleep(0),
        flush_items=100,
        guard_factory=lambda: RepeatGuard(limit=1),
    )

    async def repeated(client, url, params):  # noqa: ANN001
        if url.endswith("list.do"):
            return f"LIST:{params['r1']}".encode()
        return b"same-rate-body"

    monkeypatch.setattr(adapter, "_get", repeated)
    artifacts = _run(adapter, request)

    # two regional lists + the first two rate responses; trip is an immediate
    # flush/termination boundary, so gmgoCd=300 is not requested.
    assert len(artifacts) == 4
    assert adapter.fetch_alert
    assert "되풀이 한도 초과" in adapter.fetch_note
    decision = decide_recovery(store, _identity(request), attempt_failed=True)
    assert decision.eligible is False
    assert decision.reason_code == "GUARD_TRIPPED"


def test_request_fingerprint_changes_with_scope_regions_and_groups() -> None:
    nationwide = kfcc_request_fingerprint(CollectionRequest(source_id="kfcc"))
    busan = kfcc_request_fingerprint(
        CollectionRequest(source_id="kfcc", options={"scope": "부산"})
    )
    explicit = kfcc_request_fingerprint(
        CollectionRequest(source_id="kfcc", regions=("부산", "경남"))
    )
    one_group = kfcc_request_fingerprint(_request(groups=("13",)))
    two_groups = kfcc_request_fingerprint(_request(groups=("13", "14")))
    assert nationwide != busan
    assert busan != explicit
    assert one_group != two_groups
