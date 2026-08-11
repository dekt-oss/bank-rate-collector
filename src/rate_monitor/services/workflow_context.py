"""GitHub Actions run identity used by resumable acquisition.

The checkpoint contract defines ``cycle_date_kst`` from the workflow run's
``run_started_at`` rather than from the source step's wall clock. That avoids a
manual run crossing midnight between workflow start and collector start.
"""

from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

KST = ZoneInfo("Asia/Seoul")


class WorkflowContextError(RuntimeError):
    """The current GitHub Actions run identity cannot be resolved safely."""


def cycle_date_kst(run_started_at: str) -> str:
    """Convert GitHub's ISO ``run_started_at`` timestamp to a KST calendar date."""
    try:
        started = datetime.fromisoformat(run_started_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise WorkflowContextError(
            f"GitHub run_started_at 형식이 잘못됐다: {run_started_at!r}"
        ) from exc
    if started.tzinfo is None:
        raise WorkflowContextError("GitHub run_started_at에 timezone이 없다")
    return started.astimezone(KST).date().isoformat()


def resolve_cycle_date_kst(
    *,
    client: httpx.Client | None = None,
    environ: dict[str, str] | None = None,
) -> str:
    """Read the current Actions run and return its KST cycle date.

    Public repositories can use the endpoint without authentication. If
    ``GITHUB_TOKEN`` is explicitly available, it is used to avoid anonymous API
    rate-limit dependence. Missing/invalid run identity fails closed; callers must
    not silently substitute the source-step wall clock.
    """
    env = os.environ if environ is None else environ
    run_id = env.get("GITHUB_RUN_ID", "").strip()
    repository = env.get("GITHUB_REPOSITORY", "").strip()
    api_url = env.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    if not run_id.isdigit() or not repository or "/" not in repository:
        raise WorkflowContextError(
            "GITHUB_RUN_ID/GITHUB_REPOSITORY가 없어 checkpoint cycle을 확정할 수 없다"
        )

    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = env.get("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    owns_client = client is None
    http = client or httpx.Client(timeout=10.0, follow_redirects=True)
    try:
        response = http.get(
            f"{api_url}/repos/{repository}/actions/runs/{run_id}",
            headers=headers,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        raise WorkflowContextError(f"GitHub workflow run 조회 실패: {exc}") from exc
    finally:
        if owns_client:
            http.close()

    if str(payload.get("id")) != run_id:
        raise WorkflowContextError("GitHub workflow run 응답 id가 현재 GITHUB_RUN_ID와 다르다")
    started = payload.get("run_started_at")
    if not isinstance(started, str) or not started:
        raise WorkflowContextError("GitHub workflow run 응답에 run_started_at이 없다")
    return cycle_date_kst(started)
