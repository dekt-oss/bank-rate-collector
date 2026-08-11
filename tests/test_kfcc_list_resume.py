"""KFCC regional-list phase can resume before the rate work plan exists."""

import asyncio
from pathlib import Path

import pytest

from rate_monitor.collectors.kfcc import parser
from rate_monitor.collectors.kfcc.adapter import KfccRequestFailure
from rate_monitor.collectors.kfcc.resumable import (
    KfccResumableAdapter,
    build_kfcc_checkpoint_context,
)
from rate_monitor.domain.schemas import CollectionRequest
from rate_monitor.services.resumable_acquisition import (
    AcquisitionSessionIdentity,
    decide_recovery,
)
from rate_monitor.services.storage_service import LocalObjectStore

CYCLE = "2026-08-11"


def _request() -> CollectionRequest:
    return CollectionRequest(
        source_id="kfcc",
        regions=("부산", "경남"),
        options={"groups": ("13",)},
    )


def _identity(request: CollectionRequest) -> AcquisitionSessionIdentity:
    context = build_kfcc_checkpoint_context(request, cycle_date_kst=CYCLE)
    return AcquisitionSessionIdentity(
        source_id="kfcc",
        cycle_date_kst=CYCLE,
        request_fingerprint=context.request_fingerprint,
        acquisition_contract_version=context.acquisition_contract_version,
    )


def _failure() -> KfccRequestFailure:
    cause = RuntimeError("simulated list connection loss")
    return KfccRequestFailure(
        "NETWORK_CONNECT",
        phase="list",
        request_label="r1=경남",
        attempt=4,
        max_attempts=4,
        cause=cause,
        retry_count=3,
        failure_reasons={"NETWORK_CONNECT": 4},
    )


def test_resume_skips_durable_region_list_before_plan(tmp_path: Path, monkeypatch) -> None:
    rows = {
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
            }
        ],
        "경남": [
            {
                "gmgoCd": "200",
                "gmgoNm": "나금고",
                "divCd": "001",
                "divNm": "본점",
                "gmgoType": "지역",
                "addr": "경남 창원시 1",
                "r1": "경남",
                "r2": "창원시",
            }
        ],
    }
    monkeypatch.setattr(parser, "check_list_schema", lambda html: [])
    monkeypatch.setattr(
        parser,
        "parse_list",
        lambda html: [dict(row) for row in rows[html.removeprefix("LIST:")]],
    )
    monkeypatch.setattr(parser, "schema_fingerprint", lambda html: "fp")

    request = _request()
    store = LocalObjectStore(tmp_path / "objects")
    first = KfccResumableAdapter(
        store,
        cycle_date_kst=CYCLE,
        sleep=lambda delay: asyncio.sleep(0),
        flush_items=1,
    )
    first_calls: list[str] = []

    async def first_get(client, url, params):  # noqa: ANN001
        region = params["r1"]
        first_calls.append(region)
        if region == "경남":
            raise _failure()
        return f"LIST:{region}".encode()

    monkeypatch.setattr(first, "_get", first_get)
    with pytest.raises(KfccRequestFailure):
        asyncio.run(first.fetch(request))

    decision = decide_recovery(store, _identity(request), attempt_failed=True)
    assert decision.eligible is True
    assert decision.completed_work_count == 1
    assert first_calls == ["부산", "경남"]

    resumed = KfccResumableAdapter(
        store,
        cycle_date_kst=CYCLE,
        sleep=lambda delay: asyncio.sleep(0),
        flush_items=1,
    )
    resumed_calls: list[str] = []

    async def resumed_get(client, url, params):  # noqa: ANN001
        if url.endswith("list.do"):
            region = params["r1"]
            resumed_calls.append(f"list:{region}")
            assert region == "경남"
            return f"LIST:{region}".encode()
        gmgo_cd = params["OPEN_TRMID"]
        resumed_calls.append(f"rate:{gmgo_cd}")
        return f"RATE:{gmgo_cd}:13".encode()

    monkeypatch.setattr(resumed, "_get", resumed_get)
    artifacts = asyncio.run(resumed.fetch(request))

    assert resumed_calls == ["list:경남", "rate:100", "rate:200"]
    assert [artifact.request_meta["kind"] for artifact in artifacts] == [
        "list",
        "list",
        "rate",
        "rate",
    ]
