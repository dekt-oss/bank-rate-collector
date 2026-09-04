"""Freshness gate for GitHub Actions writers of canonical production state."""

from __future__ import annotations

import os
import re
import subprocess

_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")

# A queued collection can legitimately outlive a presentation-only merge.  Blocking
# that run after hours of acquisition discards valid source data and turns ordinary
# UI work into an operational collection failure.  The allow-list is intentionally
# narrow and fail-closed: anything that can affect acquisition, schema, validation,
# canonical storage, production writer workflow semantics, dependencies or runtime
# code remains unsafe and must be recollected on current main.
_SAFE_STALE_PREFIXES = (
    "docs/",
    "tests/",
)
_SAFE_STRATEGY_WORKFLOW_PREFIX = ".github/workflows/strategy-"
_SAFE_PRESENTATION_SERVICE_SUFFIX = "_presentation.py"
_SAFE_SMOKE_SUFFIXES = ("_smoke.js", "_smoke.py")


class CanonicalWriterGuardError(RuntimeError):
    """A canonical main writer cannot prove that its checkout is publish-safe."""


def _git_run(args: list[str], *, timeout: int = 20) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _current_main_sha() -> str:
    try:
        result = _git_run(["git", "ls-remote", "origin", "refs/heads/main"])
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
    return remote_sha


def _is_publish_safe_stale_path(path: str) -> bool:
    normalized = path.strip().replace("\\", "/")
    if not normalized:
        return True
    if normalized.startswith(_SAFE_STALE_PREFIXES):
        return True
    if normalized.startswith(_SAFE_STRATEGY_WORKFLOW_PREFIX):
        return True
    if normalized.startswith("src/rate_monitor/services/") and normalized.endswith(
        _SAFE_PRESENTATION_SERVICE_SUFFIX
    ):
        return True
    if normalized.startswith("scripts/") and normalized.endswith(_SAFE_SMOKE_SUFFIXES):
        return True
    return False


def _changed_paths(run_sha: str, remote_sha: str) -> tuple[str, ...]:
    """Return tree changes between the queued run and current main.

    ``actions/checkout`` is shallow, so the current main object may not exist locally.
    Fetch exactly the already-validated SHA, then compare the two trees directly.  We
    do not need ancestry for this safety decision; we need to know whether the current
    production writer/acquisition contract differs from the run's tree.
    """

    try:
        _git_run(
            ["git", "fetch", "--no-tags", "--depth=1", "origin", remote_sha],
            timeout=60,
        )
        result = _git_run(
            ["git", "diff", "--name-only", "--no-renames", run_sha, remote_sha, "--"],
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise CanonicalWriterGuardError(
            "stale-main writer gate: 현재 main과 실행 checkout의 변경 경로를 검증하지 못했다"
        ) from exc

    return tuple(line.strip() for line in result.stdout.splitlines() if line.strip())


def ensure_current_main_writer() -> None:
    """Allow current main, or narrowly compatible presentation-only main drift.

    Local runs, PR/evidence branches and other non-main Actions are intentionally
    untouched.  A stale production writer is still blocked whenever current main has
    *any* change outside the explicit presentation/test/docs allow-list.  This keeps
    the #293 schema/canonical-state rollback protection while avoiding loss of a long
    collection merely because a Strategy presentation PR merged during acquisition.
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

    remote_sha = _current_main_sha()
    if remote_sha == run_sha:
        return

    changed = _changed_paths(run_sha, remote_sha)
    unsafe = tuple(path for path in changed if not _is_publish_safe_stale_path(path))
    if not unsafe:
        return

    preview = ", ".join(unsafe[:8])
    if len(unsafe) > 8:
        preview += f", ... (+{len(unsafe) - 8})"
    raise CanonicalWriterGuardError(
        "stale-main writer blocked: "
        f"run_sha={run_sha} current_main_sha={remote_sha}. "
        f"canonical/acquisition-sensitive changes={preview}. "
        "오래 대기한 writer는 변경된 계약으로 canonical R2/rate-data를 갱신할 수 없다"
    )
