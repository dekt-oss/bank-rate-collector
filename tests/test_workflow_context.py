"""checkpoint cycle date는 source step 시각이 아니라 workflow run start에서 온다."""

import httpx
import pytest

from rate_monitor.services.workflow_context import (
    WorkflowContextError,
    cycle_date_kst,
    resolve_cycle_date_kst,
)


def test_cycle_date_uses_kst_calendar_day() -> None:
    assert cycle_date_kst("2026-08-10T15:17:03Z") == "2026-08-11"
    assert cycle_date_kst("2026-08-11T14:59:59Z") == "2026-08-11"
    assert cycle_date_kst("2026-08-11T15:00:00Z") == "2026-08-12"


def test_cycle_date_rejects_naive_timestamp() -> None:
    with pytest.raises(WorkflowContextError, match="timezone"):
        cycle_date_kst("2026-08-11T05:00:00")


def test_resolve_cycle_date_reads_exact_current_run() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/repos/dekt-oss/bank-rate-collector/actions/runs/12345"
        assert request.headers["authorization"] == "Bearer secret"
        return httpx.Response(
            200,
            json={"id": 12345, "run_started_at": "2026-08-10T15:17:03Z"},
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        resolved = resolve_cycle_date_kst(
            client=client,
            environ={
                "GITHUB_RUN_ID": "12345",
                "GITHUB_REPOSITORY": "dekt-oss/bank-rate-collector",
                "GITHUB_API_URL": "https://api.github.test",
                "GITHUB_TOKEN": "secret",
            },
        )

    assert resolved == "2026-08-11"


def test_resolve_cycle_date_allows_public_run_without_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "authorization" not in request.headers
        return httpx.Response(
            200,
            json={"id": 12345, "run_started_at": "2026-08-10T19:17:03Z"},
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        resolved = resolve_cycle_date_kst(
            client=client,
            environ={
                "GITHUB_RUN_ID": "12345",
                "GITHUB_REPOSITORY": "dekt-oss/bank-rate-collector",
            },
        )

    assert resolved == "2026-08-11"


def test_resolve_cycle_date_fails_closed_for_wrong_run_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"id": 99999, "run_started_at": "2026-08-10T15:17:03Z"},
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(WorkflowContextError, match="GITHUB_RUN_ID"):
            resolve_cycle_date_kst(
                client=client,
                environ={
                    "GITHUB_RUN_ID": "12345",
                    "GITHUB_REPOSITORY": "dekt-oss/bank-rate-collector",
                },
            )


def test_resolve_cycle_date_fails_closed_without_run_identity() -> None:
    with pytest.raises(WorkflowContextError, match="GITHUB_RUN_ID"):
        resolve_cycle_date_kst(environ={})
