"""ECOS transient transport recovery and secret-safe failure contracts."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable

import httpx
import pytest

from rate_monitor.collectors.base import CollectorError, SourceBlockedError
from rate_monitor.collectors.bok_ecos.transport import (
    MAX_ATTEMPTS,
    RETRY_DELAYS_SECONDS,
    get_ecos_response,
)


class FakeClient:
    def __init__(self, outcomes: Iterable[int | Exception]) -> None:
        self.outcomes = list(outcomes)
        self.calls = 0

    async def get(self, url: str) -> httpx.Response:
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        request = httpx.Request("GET", url)
        return httpx.Response(outcome, request=request, content=b"{}")


async def _record_sleep(delays: list[float], seconds: float) -> None:
    delays.append(seconds)


def test_transient_503_is_retried_then_succeeds() -> None:
    client = FakeClient([503, 200])
    delays: list[float] = []

    response = asyncio.run(
        get_ecos_response(
            client,  # type: ignore[arg-type]
            "https://ecos.bok.or.kr/api/SECRET/json",
            sleep=lambda seconds: _record_sleep(delays, seconds),
        )
    )

    assert response.status_code == 200
    assert client.calls == 2
    assert delays == [RETRY_DELAYS_SECONDS[0]]


def test_transport_timeout_is_retried_then_succeeds() -> None:
    client = FakeClient([httpx.ReadTimeout("temporary timeout"), 200])
    delays: list[float] = []

    response = asyncio.run(
        get_ecos_response(
            client,  # type: ignore[arg-type]
            "https://ecos.bok.or.kr/api/SECRET/json",
            sleep=lambda seconds: _record_sleep(delays, seconds),
        )
    )

    assert response.status_code == 200
    assert client.calls == 2
    assert delays == [RETRY_DELAYS_SECONDS[0]]


def test_transient_failure_is_bounded_and_secret_safe() -> None:
    client = FakeClient([503] * MAX_ATTEMPTS)
    delays: list[float] = []

    with pytest.raises(CollectorError) as exc_info:
        asyncio.run(
            get_ecos_response(
                client,  # type: ignore[arg-type]
                "https://ecos.bok.or.kr/api/SUPER-SECRET/json",
                sleep=lambda seconds: _record_sleep(delays, seconds),
            )
        )

    assert client.calls == MAX_ATTEMPTS
    assert delays == list(RETRY_DELAYS_SECONDS)
    assert "SUPER-SECRET" not in str(exc_info.value)
    assert "503" in str(exc_info.value)


def test_blocked_status_is_fail_closed_without_retry() -> None:
    client = FakeClient([403, 200])
    delays: list[float] = []

    with pytest.raises(SourceBlockedError, match="403"):
        asyncio.run(
            get_ecos_response(
                client,  # type: ignore[arg-type]
                "https://ecos.bok.or.kr/api/SECRET/json",
                sleep=lambda seconds: _record_sleep(delays, seconds),
            )
        )

    assert client.calls == 1
    assert delays == []


def test_non_transient_http_failure_is_not_retried_or_leaked() -> None:
    client = FakeClient([400, 200])
    delays: list[float] = []

    with pytest.raises(CollectorError) as exc_info:
        asyncio.run(
            get_ecos_response(
                client,  # type: ignore[arg-type]
                "https://ecos.bok.or.kr/api/SUPER-SECRET/json",
                sleep=lambda seconds: _record_sleep(delays, seconds),
            )
        )

    assert client.calls == 1
    assert delays == []
    assert "SUPER-SECRET" not in str(exc_info.value)
    assert "400" in str(exc_info.value)
