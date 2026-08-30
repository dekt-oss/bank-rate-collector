from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from rate_monitor.services.evidence_lifecycle_service import (
    INTERMEDIATE_PREFIX,
    RAW_EVIDENCE_PREFIX,
    cleanup_intermediate,
    intermediate_key,
    persist_raw_tree,
)
from rate_monitor.services.storage_service import LocalObjectStore, StorageError


def test_raw_evidence_is_immutable_and_manifested(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path / "store")
    raw = tmp_path / "raw"
    (raw / "source").mkdir(parents=True)
    (raw / "source" / "response.json").write_text('{"ok":true}\n', encoding="utf-8")

    result = persist_raw_tree(
        store,
        root=raw,
        category="institution-funding",
        run_id="12345",
    )

    assert result["status"] == "stored"
    assert result["object_count"] == 1
    assert result["manifest_key"].startswith(RAW_EVIDENCE_PREFIX)
    assert store.exists(result["manifest_key"])
    object_key = result["objects"][0]["object_key"]
    assert store.get(object_key) == b'{"ok":true}\n'

    (raw / "source" / "response.json").write_text('{"ok":false}\n', encoding="utf-8")
    with pytest.raises(StorageError, match="immutable evidence key 충돌"):
        persist_raw_tree(
            store,
            root=raw,
            category="institution-funding",
            run_id="12345",
        )


def test_intermediate_cleanup_is_30_day_scoped_and_dry_run_first(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path / "store")
    now = datetime(2026, 8, 30, tzinfo=UTC)
    old_key = intermediate_key(
        category="candidate",
        name="old.sqlite3",
        generated_at=now - timedelta(days=31),
    )
    fresh_key = intermediate_key(
        category="candidate",
        name="fresh.sqlite3",
        generated_at=now - timedelta(days=29),
    )
    store.put(old_key, b"old")
    store.put(fresh_key, b"fresh")
    store.put(f"{INTERMEDIATE_PREFIX}not-a-timestamp/legacy.bin", b"legacy")
    store.put("state/snapshots/protected.sqlite3.gz", b"state")
    store.put(f"{RAW_EVIDENCE_PREFIX}source/run/raw.json", b"raw")

    preview = cleanup_intermediate(store, now=now)
    assert preview["dry_run"] is True
    assert preview["candidates"] == [old_key]
    assert store.exists(old_key)

    applied = cleanup_intermediate(store, now=now, dry_run=False)
    assert applied["deleted"] == [old_key]
    assert not store.exists(old_key)
    assert store.exists(fresh_key)
    assert store.exists(f"{INTERMEDIATE_PREFIX}not-a-timestamp/legacy.bin")
    assert store.exists("state/snapshots/protected.sqlite3.gz")
    assert store.exists(f"{RAW_EVIDENCE_PREFIX}source/run/raw.json")
