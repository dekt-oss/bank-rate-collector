"""Freshness gate for GitHub Actions writers of canonical production state."""

from __future__ import annotations

import os
import re
import subprocess

_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")

# A queued collection can legitimately outlive a presentation-only merge. Blocking
# that run after hours of acquisition discards valid source data and turns ordinary
# UI work into an operational collection failure. The allow-list is intentionally
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

# Source-aware writer scopes. A long-running collector must not be discarded because
# an unrelated collector/workflow changed while it was acquiring data. Only paths
# explicitly mapped here may be ignored for another scope; every unknown/shared path
# remains fail-closed. ``collect.yml`` intentionally uses one broad scope because the
# same workflow can collect core rates or KFCC depending on the trigger.
_WORKFLOW_SCOPES: dict[str, frozenset[str]] = {
    ".github/workflows/collect.yml": frozenset({"collect"}),
    ".github/workflows/collect-nh.yml": frozenset({"nh_local"}),
    ".github/workflows/nh-attempt.yml": frozenset({"nh_local"}),
    ".github/workflows/collect-savings-fast.yml": frozenset({"fast_bank"}),
    ".github/workflows/collect-institution-funding.yml": frozenset({"institution_funding"}),
    ".github/workflows/collect-cu-funding-bootstrap.yml": frozenset({"cu_funding"}),
    ".github/workflows/collect-cu-total-assets-bootstrap.yml": frozenset({"cu_total_assets"}),
    ".github/workflows/collect-size-peer-total-assets.yml": frozenset({"size_peer_total_assets"}),
    ".github/workflows/recover-size-peer-production-financial-axis.yml": frozenset(
        {"size_peer_recovery"}
    ),
}
_SOURCE_PREFIX_SCOPES: tuple[tuple[str, frozenset[str]], ...] = (
    ("src/rate_monitor/collectors/finlife/", frozenset({"collect", "fast_bank"})),
    ("src/rate_monitor/collectors/fsb/", frozenset({"collect", "fast_bank"})),
    ("src/rate_monitor/collectors/bok_ecos/", frozenset({"collect"})),
    (
        "src/rate_monitor/collectors/cu/",
        frozenset({"collect", "cu_funding", "cu_total_assets", "size_peer_recovery"}),
    ),
    ("src/rate_monitor/collectors/kfcc/", frozenset({"collect"})),
    ("src/rate_monitor/collectors/nh_local/", frozenset({"nh_local"})),
    (
        "src/rate_monitor/collectors/data_go_funding/",
        frozenset({"institution_funding", "size_peer_total_assets", "size_peer_recovery"}),
    ),
    (
        "src/rate_monitor/services/size_peer_",
        frozenset({"size_peer_total_assets", "size_peer_recovery"}),
    ),
)


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
    return normalized.startswith("scripts/") and normalized.endswith(_SAFE_SMOKE_SUFFIXES)


def _workflow_path_from_ref(workflow_ref: str) -> str:
    """Extract ``.github/workflows/*.yml`` from GITHUB_WORKFLOW_REF fail-closed."""

    marker = "/.github/workflows/"
    value = workflow_ref.strip().replace("\\", "/")
    if marker not in value:
        return ""
    tail = value.split(marker, 1)[1]
    filename = tail.split("@", 1)[0]
    if not filename or "/" in filename:
        return ""
    return f".github/workflows/{filename}"


def _infer_writer_scope() -> str:
    explicit = os.environ.get("RATE_MONITOR_WRITER_SCOPE", "").strip()
    if explicit:
        return explicit
    workflow_path = _workflow_path_from_ref(os.environ.get("GITHUB_WORKFLOW_REF", ""))
    scopes = _WORKFLOW_SCOPES.get(workflow_path, frozenset())
    if len(scopes) != 1:
        return ""
    return next(iter(scopes))


def _is_scope_irrelevant_stale_path(path: str, writer_scope: str) -> bool:
    """Return True only for an explicitly source-local path outside this writer scope.

    An absent/unknown writer scope deliberately preserves the historical strict guard.
    Shared persistence/schema/runtime paths are never inferred to be safe.
    """

    scope = writer_scope.strip()
    if not scope:
        return False

    normalized = path.strip().replace("\\", "/")
    workflow_scopes = _WORKFLOW_SCOPES.get(normalized)
    if workflow_scopes is not None:
        return scope not in workflow_scopes

    for prefix, affected_scopes in _SOURCE_PREFIX_SCOPES:
        if normalized.startswith(prefix):
            return scope not in affected_scopes
    return False


def _changed_paths(run_sha: str, remote_sha: str) -> tuple[str, ...]:
    """Return tree changes between the queued run and current main.

    ``actions/checkout`` is shallow, so the current main object may not exist locally.
    Fetch exactly the already-validated SHA, then compare the two trees directly. We
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


def _refresh_safe_paths(remote_sha: str, changed: tuple[str, ...]) -> None:
    """Refresh presentation-only paths so a stale collector cannot roll UI back.

    Acquisition has already used the run's original code. If the only main drift is
    explicitly presentation/test/docs-only, keeping the collected DB is safe, but
    publishing the old presentation would temporarily undo the UI merge that caused
    the drift. Refresh only the allow-listed paths from the exact verified main SHA.
    Subsequent build commands are separate processes and therefore consume these
    current-main presentation files. Any checkout failure is fail-closed.

    Source-local paths belonging to another collector are deliberately *not* refreshed:
    they are irrelevant to this run and refreshing operational code after acquisition
    could create a mixed-code runtime. They are merely ignored by the stale decision.
    """

    if not changed:
        return
    try:
        _git_run(["git", "checkout", remote_sha, "--", *changed], timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        raise CanonicalWriterGuardError(
            "stale-main writer gate: 안전한 presentation 변경을 현재 main에서 동기화하지 못했다"
        ) from exc


def ensure_current_main_writer() -> None:
    """Allow current main, compatible presentation drift, or unrelated source drift.

    Local runs, PR/evidence branches and other non-main Actions are intentionally
    untouched. A stale production writer is blocked whenever current main changes a
    shared/unknown path or a path mapped to this writer's inferred source scope.
    Explicitly mapped changes for another source do not invalidate hours of unrelated
    acquisition. If workflow scope cannot be inferred, behavior remains strictly
    backward-compatible and fail-closed.

    Presentation-only safe paths are refreshed from the verified current main commit
    before publication. Scope-irrelevant operational paths are not refreshed.
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
    writer_scope = _infer_writer_scope()
    unsafe = tuple(
        path
        for path in changed
        if not _is_publish_safe_stale_path(path)
        and not _is_scope_irrelevant_stale_path(path, writer_scope)
    )
    if unsafe:
        preview = ", ".join(unsafe[:8])
        if len(unsafe) > 8:
            preview += f", ... (+{len(unsafe) - 8})"
        scope_note = f" writer_scope={writer_scope}." if writer_scope else ""
        raise CanonicalWriterGuardError(
            "stale-main writer blocked: "
            f"run_sha={run_sha} current_main_sha={remote_sha}.{scope_note} "
            f"canonical/acquisition-sensitive changes={preview}. "
            "오래 대기한 writer는 변경된 계약으로 canonical R2/rate-data를 갱신할 수 없다"
        )

    refreshable = tuple(path for path in changed if _is_publish_safe_stale_path(path))
    _refresh_safe_paths(remote_sha, refreshable)
