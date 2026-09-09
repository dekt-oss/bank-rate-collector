"""한국은행 ECOS HTTP 전송 계약.

ECOS는 인증키가 URL path에 들어간다. 따라서 httpx의 원본 예외 문자열을
그대로 실행 이력에 남기면 URL과 함께 키가 노출될 수 있다. 이 모듈은
일시적인 전송/서버 오류만 짧게 재시도하고, 최종 오류 메시지는 URL을
포함하지 않도록 공통화한다.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import httpx

from rate_monitor.collectors.base import CollectorError, SourceBlockedError

BLOCK_STATUSES = frozenset({401, 403, 429})
TRANSIENT_STATUSES = frozenset({408, 500, 502, 503, 504})
MAX_ATTEMPTS = 3
RETRY_DELAYS_SECONDS = (1.0, 2.0)

Sleep = Callable[[float], Awaitable[None]]


async def get_ecos_response(
    client: httpx.AsyncClient,
    url: str,
    *,
    sleep: Sleep = asyncio.sleep,
) -> httpx.Response:
    """GET one ECOS resource with bounded, policy-safe retries.

    Transport failures and explicit transient HTTP statuses are retried. Auth/access
    failures remain fail-closed and are never retried into a false success. Error
    messages intentionally omit the request URL because it contains ``ECOS_API_KEY``.
    """

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = await client.get(url)
        except httpx.TransportError as error:
            if attempt >= MAX_ATTEMPTS:
                raise CollectorError(
                    "ECOS 전송 실패 — "
                    f"{MAX_ATTEMPTS}회 시도 후 중단 ({type(error).__name__})"
                ) from error
            await sleep(RETRY_DELAYS_SECONDS[attempt - 1])
            continue

        status = response.status_code
        if status in BLOCK_STATUSES:
            raise SourceBlockedError(f"차단 응답 {status} — 우회하지 않고 중단한다")

        if status in TRANSIENT_STATUSES:
            if attempt >= MAX_ATTEMPTS:
                raise CollectorError(
                    f"ECOS 일시 오류 HTTP {status} — {MAX_ATTEMPTS}회 시도 후 중단"
                )
            await sleep(RETRY_DELAYS_SECONDS[attempt - 1])
            continue

        if status >= 400:
            # response.raise_for_status()의 문자열에는 요청 URL이 들어간다. ECOS는
            # 인증키를 path에 넣으므로 여기서는 status만 남겨 secret leak을 막는다.
            raise CollectorError(f"ECOS HTTP 오류 {status}")

        return response

    raise AssertionError("ECOS retry loop exhausted without terminal result")
