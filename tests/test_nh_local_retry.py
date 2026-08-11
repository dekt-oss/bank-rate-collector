"""농·축협 HTTP retry 계약 — 외부 네트워크 없이 오류 형태만 고정한다."""

import asyncio

import httpx
import pytest

from rate_monitor.collectors.base import SourceBlockedError
from rate_monitor.collectors.nh_local.adapter import (
    LIST_SCREEN,
    MAX_TOTAL_RETRIES,
    NhLocalAdapter,
    NhRequestFailure,
)


class SleepRecorder:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)


def _run_get(adapter: NhLocalAdapter, handler, *, phase: str = "preflight") -> bytes:
    async def run() -> bytes:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            return await adapter._get(client, LIST_SCREEN, {}, phase=phase)

    return asyncio.run(run())


def test_preflight_connect_error_retries_then_succeeds(caplog) -> None:
    calls = 0
    sleep = SleepRecorder()

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectError("temporary connect failure", request=request)
        return httpx.Response(200, content=b"ok", request=request)

    adapter = NhLocalAdapter(sleep=sleep)
    with caplog.at_level("WARNING"):
        body = _run_get(adapter, handler)

    assert body == b"ok"
    assert calls == 2
    assert sleep.delays == [6.0]  # 정상 간격 1초 + preflight backoff 5초
    assert adapter._retry_count == 1
    assert adapter._retry_reasons == {"NETWORK_CONNECT": 1}
    assert "source_id=nh_local" in caplog.text
    assert "phase=preflight" in caplog.text
    assert "error_class=NETWORK_CONNECT" in caplog.text


def test_preflight_connect_timeout_exhausts_four_attempts() -> None:
    calls = 0
    sleep = SleepRecorder()

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectTimeout("connect timeout", request=request)

    adapter = NhLocalAdapter(sleep=sleep)
    with pytest.raises(NhRequestFailure) as caught:
        _run_get(adapter, handler)

    assert caught.value.code == "NETWORK_TIMEOUT"
    assert caught.value.phase == "preflight"
    assert caught.value.attempt == caught.value.max_attempts == 4
    assert calls == 4
    assert sleep.delays == [6.0, 21.0, 61.0]
    assert adapter._retry_count == 3


def test_preflight_503_retries_then_succeeds() -> None:
    calls = 0
    sleep = SleepRecorder()

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503, content=b"unavailable", request=request)
        return httpx.Response(200, content=b"ok", request=request)

    adapter = NhLocalAdapter(sleep=sleep)
    assert _run_get(adapter, handler) == b"ok"
    assert calls == 2
    assert sleep.delays == [6.0]
    assert adapter._retry_reasons == {"HTTP_SERVER_ERROR": 1}


def test_detail_read_timeout_uses_shorter_retry_policy() -> None:
    calls = 0
    sleep = SleepRecorder()

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ReadTimeout("read timeout", request=request)
        return httpx.Response(200, content=b"detail", request=request)

    adapter = NhLocalAdapter(sleep=sleep)
    assert _run_get(adapter, handler, phase="detail") == b"detail"
    assert calls == 2
    assert sleep.delays == [4.0]  # 정상 간격 1초 + detail backoff 3초
    assert adapter._retry_reasons == {"NETWORK_TIMEOUT": 1}


@pytest.mark.parametrize("status", [403, 429])
def test_access_control_statuses_are_not_retried(status: int) -> None:
    calls = 0
    sleep = SleepRecorder()

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status, content=b"plain rejection", request=request)

    adapter = NhLocalAdapter(sleep=sleep)
    with pytest.raises(httpx.HTTPStatusError):
        _run_get(adapter, handler)

    assert calls == 1
    assert sleep.delays == []
    assert adapter._retry_count == 0


def test_block_marker_is_not_retried() -> None:
    calls = 0
    sleep = SleepRecorder()

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(403, content=b"Request Blocked", request=request)

    adapter = NhLocalAdapter(sleep=sleep)
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

    adapter = NhLocalAdapter(sleep=sleep)
    adapter._retry_count = MAX_TOTAL_RETRIES

    with pytest.raises(NhRequestFailure) as caught:
        _run_get(adapter, handler, phase="detail")

    assert caught.value.code == "RETRY_BUDGET_EXHAUSTED"
    assert calls == 1
    assert sleep.delays == []
    assert adapter._retry_count == MAX_TOTAL_RETRIES


def test_retry_note_records_successful_recovery_reason() -> None:
    sleep = SleepRecorder()
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.RemoteProtocolError("protocol blip", request=request)
        return httpx.Response(200, content=b"ok", request=request)

    adapter = NhLocalAdapter(sleep=sleep)
    _run_get(adapter, handler)

    assert adapter._retry_note() == "재시도 1회 (NETWORK_PROTOCOL 1)"
