"""새마을금고 HTTP retry 계약 — 외부 네트워크 없이 오류 형태만 고정한다."""

import asyncio

import httpx
import pytest

from rate_monitor.collectors.base import SourceBlockedError
from rate_monitor.collectors.kfcc.adapter import (
    BASE_URL,
    MAX_TOTAL_RETRIES,
    KfccAdapter,
    KfccRequestFailure,
    _failure_code,
)


class SleepRecorder:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)


def _run_get(
    adapter: KfccAdapter,
    handler,
    *,
    phase: str = "list",
) -> bytes:
    async def run() -> bytes:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            if phase == "list":
                return await adapter._get(
                    client,
                    f"{BASE_URL}/map/list.do",
                    {"r1": "부산", "r2": ""},
                )
            if phase == "rate":
                return await adapter._get(
                    client,
                    f"{BASE_URL}/map/goods_19.do",
                    {"OPEN_TRMID": "1203", "gubuncode": "13"},
                )
            raise ValueError(phase)

    return asyncio.run(run())


def test_list_connect_error_retries_then_succeeds(caplog) -> None:
    calls = 0
    sleep = SleepRecorder()

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectError("temporary connect failure", request=request)
        return httpx.Response(200, content=b"ok", request=request)

    adapter = KfccAdapter(sleep=sleep)
    with caplog.at_level("WARNING"):
        body = _run_get(adapter, handler)

    assert body == b"ok"
    assert calls == 2
    assert sleep.delays == [6.0]
    assert adapter._retry_count == 1
    assert adapter._retry_reasons == {"NETWORK_CONNECT": 1}
    assert "source_id=kfcc" in caplog.text
    assert "phase=list" in caplog.text
    assert "request=r1=부산" in caplog.text
    assert "error_class=NETWORK_CONNECT" in caplog.text


def test_list_connect_timeout_exhausts_four_attempts() -> None:
    calls = 0
    sleep = SleepRecorder()

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectTimeout("connect timeout", request=request)

    adapter = KfccAdapter(sleep=sleep)
    with pytest.raises(KfccRequestFailure) as caught:
        _run_get(adapter, handler)

    assert caught.value.code == "NETWORK_TIMEOUT"
    assert caught.value.phase == "list"
    assert caught.value.request_label == "r1=부산"
    assert caught.value.attempt == caught.value.max_attempts == 4
    assert calls == 4
    assert sleep.delays == [6.0, 21.0, 61.0]
    assert adapter._retry_count == 3
    assert caught.value.failure_reasons == {"NETWORK_TIMEOUT": 4}
    assert "failures=NETWORK_TIMEOUT 4" in str(caught.value)


def test_rate_read_timeout_uses_shorter_retry_policy() -> None:
    calls = 0
    sleep = SleepRecorder()

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ReadTimeout("read timeout", request=request)
        return httpx.Response(200, content=b"rate", request=request)

    adapter = KfccAdapter(sleep=sleep)
    assert _run_get(adapter, handler, phase="rate") == b"rate"
    assert calls == 2
    assert sleep.delays == [4.0]
    assert adapter._retry_reasons == {"NETWORK_TIMEOUT": 1}


@pytest.mark.parametrize(
    ("error_type", "expected_code"),
    [
        (httpx.ReadError, "NETWORK_IO"),
        (httpx.WriteError, "NETWORK_IO"),
        (httpx.WriteTimeout, "NETWORK_TIMEOUT"),
        (httpx.PoolTimeout, "NETWORK_TIMEOUT"),
        (httpx.RemoteProtocolError, "NETWORK_PROTOCOL"),
    ],
)
def test_transient_transport_failures_retry_then_succeed(
    error_type: type[httpx.RequestError], expected_code: str
) -> None:
    calls = 0
    sleep = SleepRecorder()

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise error_type("temporary transport failure", request=request)
        return httpx.Response(200, content=b"rate", request=request)

    adapter = KfccAdapter(sleep=sleep)
    assert _run_get(adapter, handler, phase="rate") == b"rate"
    assert calls == 2
    assert sleep.delays == [4.0]
    assert adapter._retry_reasons == {expected_code: 1}


def test_503_retries_then_succeeds() -> None:
    calls = 0
    sleep = SleepRecorder()

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503, content=b"unavailable", request=request)
        return httpx.Response(200, content=b"ok", request=request)

    adapter = KfccAdapter(sleep=sleep)
    assert _run_get(adapter, handler, phase="rate") == b"ok"
    assert calls == 2
    assert sleep.delays == [4.0]
    assert adapter._retry_reasons == {"HTTP_SERVER_ERROR": 1}


@pytest.mark.parametrize("status", [400, 403, 429, 501])
def test_non_retryable_http_statuses_stop_immediately(status: int) -> None:
    calls = 0
    sleep = SleepRecorder()

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status, content=b"plain rejection", request=request)

    adapter = KfccAdapter(sleep=sleep)
    with pytest.raises(httpx.HTTPStatusError):
        _run_get(adapter, handler, phase="rate")

    assert calls == 1
    assert sleep.delays == []
    assert adapter._retry_count == 0


def test_block_marker_is_not_retried() -> None:
    calls = 0
    sleep = SleepRecorder()

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(400, content=b"Request Blocked", request=request)

    adapter = KfccAdapter(sleep=sleep)
    with pytest.raises(SourceBlockedError):
        _run_get(adapter, handler)

    assert calls == 1
    assert sleep.delays == []
    assert adapter._retry_count == 0


def test_retry_budget_stops_additional_requests() -> None:
    calls = 0
    sleep = SleepRecorder()

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("still down", request=request)

    adapter = KfccAdapter(sleep=sleep)
    adapter._retry_count = MAX_TOTAL_RETRIES

    with pytest.raises(KfccRequestFailure) as caught:
        _run_get(adapter, handler, phase="rate")

    assert caught.value.code == "RETRY_BUDGET_EXHAUSTED"
    assert calls == 1
    assert sleep.delays == []
    assert adapter._retry_count == MAX_TOTAL_RETRIES
    assert caught.value.failure_reasons == {"NETWORK_CONNECT": 1}


def test_unknown_failure_taxonomy_does_not_mislabel_as_protocol() -> None:
    assert _failure_code(RuntimeError("unexpected")) == "NETWORK_UNKNOWN"


def test_retry_note_records_successful_recovery_reason() -> None:
    sleep = SleepRecorder()
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.RemoteProtocolError("protocol blip", request=request)
        return httpx.Response(200, content=b"ok", request=request)

    adapter = KfccAdapter(sleep=sleep)
    _run_get(adapter, handler, phase="rate")

    assert adapter._retry_note() == "재시도 1회 (NETWORK_PROTOCOL 1)"
