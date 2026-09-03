"""Canonical snapshot stale-main writer gate."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from rate_monitor.services import snapshot_service
from rate_monitor.services.snapshot_service import SnapshotIntegrityError

RUN_SHA = "1" * 40
CURRENT_SHA = "2" * 40


def _main_actions(monkeypatch: pytest.MonkeyPatch, *, sha: str = RUN_SHA) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setenv("GITHUB_SHA", sha)


def test_local_snapshot_does_not_query_remote(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)

    def unexpected(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("local snapshot must not query origin/main")

    monkeypatch.setattr(snapshot_service.subprocess, "run", unexpected)
    snapshot_service._guard_current_main_writer()


def test_non_main_actions_does_not_query_remote(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/feat/evidence")
    monkeypatch.setenv("GITHUB_SHA", RUN_SHA)

    def unexpected(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("non-main Actions must not query origin/main")

    monkeypatch.setattr(snapshot_service.subprocess, "run", unexpected)
    snapshot_service._guard_current_main_writer()


def test_main_actions_requires_valid_run_sha(monkeypatch: pytest.MonkeyPatch) -> None:
    _main_actions(monkeypatch, sha="")
    with pytest.raises(SnapshotIntegrityError, match="GITHUB_SHA"):
        snapshot_service._guard_current_main_writer()


def test_current_main_writer_is_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    _main_actions(monkeypatch)
    monkeypatch.setattr(
        snapshot_service.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(  # noqa: ARG005
            stdout=f"{RUN_SHA}\trefs/heads/main\n"
        ),
    )
    snapshot_service._guard_current_main_writer()


def test_stale_main_writer_is_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    _main_actions(monkeypatch)
    monkeypatch.setattr(
        snapshot_service.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(  # noqa: ARG005
            stdout=f"{CURRENT_SHA}\trefs/heads/main\n"
        ),
    )
    with pytest.raises(SnapshotIntegrityError, match="stale-main writer blocked") as exc_info:
        snapshot_service._guard_current_main_writer()
    assert RUN_SHA in str(exc_info.value)
    assert CURRENT_SHA in str(exc_info.value)


def test_remote_lookup_failure_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    _main_actions(monkeypatch)

    def fail(*args, **kwargs):  # noqa: ANN002, ANN003
        raise subprocess.TimeoutExpired(cmd="git ls-remote", timeout=20)

    monkeypatch.setattr(snapshot_service.subprocess, "run", fail)
    with pytest.raises(SnapshotIntegrityError, match="검증하지 못했다"):
        snapshot_service._guard_current_main_writer()


def test_malformed_remote_ref_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    _main_actions(monkeypatch)
    monkeypatch.setattr(
        snapshot_service.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout="not-a-sha refs/heads/main\n"),  # noqa: ARG005
    )
    with pytest.raises(SnapshotIntegrityError, match="SHA 형식"):
        snapshot_service._guard_current_main_writer()


def test_guard_runs_before_existing_publish_artifacts_are_touched(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    work_db = tmp_path / "work.sqlite3"
    publish_db = tmp_path / "publish.sqlite3"
    manifest = tmp_path / "manifest.json"
    work_db.write_bytes(b"not reached because guard blocks first")
    publish_db.write_bytes(b"last-known-good")
    manifest.write_text('{"state":"last-known-good"}\n', encoding="utf-8")

    def block() -> None:
        raise SnapshotIntegrityError("stale-main writer blocked")

    monkeypatch.setattr(snapshot_service, "_guard_current_main_writer", block)
    with pytest.raises(SnapshotIntegrityError, match="stale-main writer blocked"):
        snapshot_service.create_snapshot(work_db, publish_db, manifest)

    assert publish_db.read_bytes() == b"last-known-good"
    assert manifest.read_text(encoding="utf-8") == '{"state":"last-known-good"}\n'
