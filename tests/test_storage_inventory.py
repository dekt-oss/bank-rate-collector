"""R2 용량 조회. 읽기만 하고, 계열·단위별 합계가 맞는지 본다."""

import json
from pathlib import Path

from rate_monitor.cli import main
from rate_monitor.services.storage_inventory import build_inventory
from rate_monitor.services.storage_service import (
    LocalObjectStore,
    R2Config,
    R2ObjectStore,
)


def _seed(store: LocalObjectStore) -> None:
    store.put("state/current.json", b"{}")
    store.put("state/snapshots/20261015T003647-aaaaaaaa.sqlite3.gz", b"x" * 100)
    store.put("state/snapshots/20261016T035605-bbbbbbbb.sqlite3.gz", b"x" * 120)
    store.put("checkpoints/v1/nh_local/2026-10-15/sessions/s1/chunks/000001-a.tar.gz", b"c" * 50)
    store.put("checkpoints/v1/nh_local/2026-10-16/sessions/s2/chunks/000001-b.tar.gz", b"c" * 70)
    store.put("checkpoints/v1/nh_local/2026-10-16/active.json", b"{}")
    store.put("raw-evidence/institution_funding/111/manifest.json", b"r" * 10)


def test_inventory_groups_by_family_and_unit(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path / "bucket")
    _seed(store)

    report = build_inventory(store)
    families = {f["family"]: f for f in report["families"]}

    assert report["total_objects"] == 7
    assert report["total_bytes"] == 2 + 100 + 120 + 50 + 70 + 2 + 10
    assert families["state/snapshots"]["units"] == 2
    assert families["state/snapshots"]["last_unit_bytes"] == 120
    nh = families["checkpoints/v1/nh_local"]
    assert (nh["first_unit"], nh["last_unit"]) == ("2026-10-15", "2026-10-16")
    assert nh["last_unit_bytes"] == 72
    assert report["by_top_level"]["checkpoints"] == 122
    # 10 GB 무료 구간 아래면 요금은 0이다.
    assert report["estimated_monthly_storage_usd"] == 0


def test_inventory_does_not_change_the_bucket(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path / "bucket")
    _seed(store)
    before = store.list_sizes("")
    build_inventory(store)
    assert store.list_sizes("") == before


def test_r2_list_sizes_follows_pagination() -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def list_objects_v2(self, **kwargs):
            self.calls.append(kwargs)
            if "ContinuationToken" not in kwargs:
                return {
                    "Contents": [{"Key": "a", "Size": 1}],
                    "IsTruncated": True,
                    "NextContinuationToken": "t",
                }
            return {"Contents": [{"Key": "b", "Size": 2}], "IsTruncated": False}

    config = R2Config("acct", "id", "secret", "bucket", "https://example.invalid")
    client = FakeClient()
    store = R2ObjectStore(config, client=client)

    assert store.list_sizes("") == [("a", 1), ("b", 2)]
    assert client.calls[1]["ContinuationToken"] == "t"


def test_cli_inventory_writes_json(tmp_path: Path, capsys) -> None:
    root = tmp_path / "bucket"
    _seed(LocalObjectStore(root))
    out = tmp_path / "inventory.json"

    code = main([
        "storage", "inventory",
        "--local-root", str(root),
        "--json-out", str(out),
        "--config", str(tmp_path / "missing.yaml"),
    ])

    assert code == 0
    assert json.loads(out.read_text(encoding="utf-8"))["total_objects"] == 7
    assert "checkpoints/v1/nh_local" in capsys.readouterr().out
