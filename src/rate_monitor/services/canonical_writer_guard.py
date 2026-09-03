"""Freshness gate for GitHub Actions writers of canonical production state."""

from __future__ import annotations

import os
import re
import subprocess

_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class CanonicalWriterGuardError(RuntimeError):
    """A canonical main writer cannot prove that its checkout is current."""


def ensure_current_main_writer() -> None:
    """Fail closed when a queued/running main writer is older than ``origin/main``.

    Local runs, PR/evidence branches and other non-main Actions are intentionally
    untouched.  Production writers run from ``main`` and share one canonical
    R2/rate-data state, so a main Actions run must prove exact checkout freshness
    whenever it crosses a publish boundary.
    """

    if os.environ.get("GITHUB_ACTIONS") != "true":
        return
    if os.environ.get("GITHUB_REF") != "refs/heads/main":
        return

    run_sha = os.environ.get("GITHUB_SHA", "").strip().lower()
    if not _GIT_SHA_RE.fullmatch(run_sha):
        raise CanonicalWriterGuardError(
            "stale-main writer gate: GitHub Actions main 실행의 GITHUB_SHA가 없거나 유효하지 않다"
        )

    try:
        result = subprocess.run(
            ["git", "ls-remote", "origin", "refs/heads/main"],
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise CanonicalWriterGuardError(
            "stale-main writer gate: 현재 origin/main SHA를 검증하지 못했다"
        ) from exc

    rows = [line.split() for line in result.stdout.splitlines() if line.strip()]
    if len(rows) != 1 or len(rows[0]) != 2 or rows[0][1] != "refs/heads/main":
        raise CanonicalWriterGuardError(
            "stale-main writer gate: origin/main 조회 결과가 단일 ref 계약을 만족하지 않는다"
        )
    remote_sha = rows[0][0].strip().lower()
    if not _GIT_SHA_RE.fullmatch(remote_sha):
        raise CanonicalWriterGuardError(
            "stale-main writer gate: origin/main SHA 형식이 유효하지 않다"
        )
    if remote_sha != run_sha:
        raise CanonicalWriterGuardError(
            "stale-main writer blocked: "
            f"run_sha={run_sha} current_main_sha={remote_sha}. "
            "오래 대기한 writer는 canonical R2/rate-data를 갱신할 수 없다"
        )
