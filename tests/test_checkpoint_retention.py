"""체크포인트 보관 기간 정리. 날짜·운영 포인터 조건과 삭제 범위를 고정한다."""

import json
from datetime import date
from pathlib import Path

import pytest

from rate_monitor.checkpoint_cli import main
from rate_monitor.services.checkpoint_retention import cleanup_checkpoints
from rate_monitor.services.storage_service import (
    CURRENT_KEY,
    LocalObjectStore,
    StorageError,
)

TODAY = date(2026, 10, 16)


def _pointer(store: LocalObjectStore, generated_at: str) -> None:
    store.put(CURRENT_KEY, json.dumps({
        "schema_version": 1,
        "object_key": "state/snapshots/x.sqlite3.gz",
        "sha256": "0" * 64,
        "compressed_bytes": 1,
        "sqlite_bytes": 1,
        "generated_at": generated_at,
        "integrity_check": "ok",
        "foreign_key_check_violations": 0,
        "row_counts": {},
    }).encode())


def _cycle(store: LocalObjectStore, source: str, day: str) -> None:
    base = f"checkpoints/v1/{source}/{day}"
    store.put(f"{base}/active.json", b"{}")
    store.put(f"{base}/sessions/s/chunks/000001-a.tar.gz", b"c" * 100)


@pytest.fixture
def store(tmp_path: Path) -> LocalObjectStore:
    s = LocalObjectStore(tmp_path / "bucket")
    # 운영 DB는 10-16 03:56 KST에 갱신됐다 (UTC 10-15 18:56).
    _pointer(s, "2026-10-15T18:56:05+00:00")
    for day in ("2026-08-12", "2026-10-08", "2026-10-09", "2026-10-15"):
        _cycle(s, "nh_local", day)
    _cycle(s, "kfcc", "2026-10-01")
    s.put("state/snapshots/x.sqlite3.gz", b"db")
    s.put("raw-evidence/institution-funding/1/manifest.json", b"{}")
    return s


def _keys(store: LocalObjectStore) -> list[str]:
    return [k for k, _ in store.list_sizes("")]


def test_dry_run_only_lists(store) -> None:
    before = _keys(store)
    result = cleanup_checkpoints(store, today_kst=TODAY)

    assert _keys(store) == before
    assert result["dry_run"] is True
    assert result["cutoff_kst"] == "2026-10-09"
    assert [(r["source"], r["cycle_date"]) for r in result["candidate_cycles"]] == [
        ("kfcc", "2026-10-01"),
        ("nh_local", "2026-08-12"),
        ("nh_local", "2026-10-08"),
    ]
    assert result["candidate_objects"] == 6
    assert result["deleted_objects"] == 0


def test_apply_deletes_old_cycles_and_nothing_else(store) -> None:
    result = cleanup_checkpoints(store, today_kst=TODAY, dry_run=False)
    keys = _keys(store)

    assert result["deleted_objects"] == 6
    # 기준일(10-09)과 그 뒤 날짜는 남는다.
    assert any("/nh_local/2026-10-09/" in k for k in keys)
    assert any("/nh_local/2026-10-15/" in k for k in keys)
    assert not any("/2026-08-12/" in k or "/2026-10-08/" in k or "/2026-10-01/" in k
                   for k in keys)
    # checkpoint 밖은 그대로다.
    assert CURRENT_KEY in keys
    assert "state/snapshots/x.sqlite3.gz" in keys
    assert "raw-evidence/institution-funding/1/manifest.json" in keys


def test_cycles_after_the_last_publish_are_held(store) -> None:
    # 발행이 10-05 이후 멈췄다. 10-05 이후 수집일은 체크포인트가 유일한 결과일 수 있다.
    _pointer(store, "2026-10-05T01:00:00+00:00")
    result = cleanup_checkpoints(store, today_kst=TODAY, dry_run=False)

    held = [(r["source"], r["cycle_date"]) for r in result["held_uncommitted_cycles"]]
    assert held == [("nh_local", "2026-10-08")]
    assert any("/nh_local/2026-10-08/" in k for k in _keys(store))
    assert not any("/nh_local/2026-08-12/" in k for k in _keys(store))


def test_missing_pointer_deletes_nothing(tmp_path: Path) -> None:
    s = LocalObjectStore(tmp_path / "bucket")
    _cycle(s, "nh_local", "2026-08-12")
    with pytest.raises(StorageError):
        cleanup_checkpoints(s, today_kst=TODAY, dry_run=False)
    assert len(_keys(s)) == 2


def test_retention_must_be_positive(store) -> None:
    with pytest.raises(ValueError):
        cleanup_checkpoints(store, today_kst=TODAY, retention_days=0)


def test_cli_defaults_to_dry_run(store, tmp_path: Path, capsys) -> None:
    root = tmp_path / "bucket"
    before = _keys(store)

    assert main(["cleanup", "--local-root", str(root), "--today", "2026-10-16"]) == 0
    assert _keys(store) == before
    assert json.loads(capsys.readouterr().out)["candidate_objects"] == 6

    assert main(["cleanup", "--local-root", str(root), "--today", "2026-10-16", "--apply"]) == 0
    assert json.loads(capsys.readouterr().out)["deleted_objects"] == 6


def test_workflow_applies_only_on_schedule_or_explicit_dispatch() -> None:
    import yaml

    text = Path(".github/workflows/checkpoint-retention.yml").read_text(encoding="utf-8")
    flow = yaml.safe_load(text)
    on = flow[True]

    assert on["workflow_dispatch"]["inputs"]["apply"]["default"] is False
    assert "schedule" in on
    env = flow["jobs"]["cleanup"]["env"]
    assert env["APPLY"] == "${{ github.event_name == 'schedule' || inputs.apply == true }}"
    assert "--retention-days 7" in text
    # state/·raw-evidence/를 쓰지 않으므로 운영 writer 직렬화 그룹 밖에 둔다.
    assert flow["concurrency"]["group"] == "checkpoint-retention"
