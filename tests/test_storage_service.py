"""상태 DB 저장소 (선행 수정안 v1 §2.3, §6).

이 계층이 잘못되면 잃는 것이 크다. 잘못 올리면 다음 실행이 깨진 DB를 받아
복원하고, 잘못 복원하면 빈 DB 위에 사이트를 발행해 예전 것을 덮어쓴다.
그래서 **막는 것**을 먼저 확인한다.

R2 없이 전 구간을 돈다. `LocalObjectStore`가 디렉터리를 객체 저장소처럼
쓰므로 우리 로직은 전부 검증된다. `R2ObjectStore`의 boto3 배선만 실제
계정이 생긴 뒤에 확인된다 — 그건 여기서 확인할 수 없다.
"""

import gzip
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from rate_monitor.services.storage_service import (
    CURRENT_KEY,
    SNAPSHOT_PREFIX,
    BackendChoice,
    LocalObjectStore,
    R2Config,
    SnapshotRef,
    StorageBackend,
    StorageError,
    backend_from_env,
    inspect_db,
    load_backend,
    prune_snapshots,
    restore_snapshot,
    snapshot_key,
    upload_snapshot,
)

SECRETS = {
    "R2_ACCOUNT_ID": "a",
    "R2_ACCESS_KEY_ID": "b",
    "R2_SECRET_ACCESS_KEY": "c",
    "R2_BUCKET": "d",
    "R2_ENDPOINT": "e",
}


@pytest.fixture
def db(tmp_path: Path) -> Path:
    """작지만 진짜 SQLite. 흉내가 아니라 실제로 열리고 검사가 도는 파일이라야 한다."""
    path = tmp_path / "src.sqlite3"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE rate_observations (id INTEGER PRIMARY KEY, rate TEXT)")
    conn.execute("CREATE TABLE institutions (id INTEGER PRIMARY KEY)")
    conn.executemany(
        "INSERT INTO rate_observations (rate) VALUES (?)", [(f"00{i}.5",) for i in range(50)]
    )
    conn.executemany("INSERT INTO institutions (id) VALUES (?)", [(i,) for i in range(7)])
    conn.commit()
    conn.close()
    return path


@pytest.fixture
def store(tmp_path: Path) -> LocalObjectStore:
    return LocalObjectStore(tmp_path / "bucket")


# ── 설정을 잘못 넣었을 때 ───────────────────────────────────────────────


def test_half_filled_secrets_fail_instead_of_looking_absent() -> None:
    """절반만 채워 놓고 R2에 올라간다고 믿는 상태가 제일 나쁘다."""
    with pytest.raises(StorageError, match="일부만"):
        R2Config.from_env({"R2_BUCKET": "b", "R2_ENDPOINT": "e"})
    assert R2Config.from_env({}) is None
    assert R2Config.from_env(SECRETS) is not None


def test_asking_for_r2_without_secrets_fails() -> None:
    """조용히 legacy로 떨어지면 R2에 저장되고 있다고 믿는 채로 몇 주가 간다."""
    for mode in ("r2", "r2_migration"):
        with pytest.raises(StorageError, match="시크릿이 없다"):
            backend_from_env({"STORAGE_BACKEND": mode})
        assert backend_from_env({"STORAGE_BACKEND": mode, **SECRETS}) == StorageBackend(mode)


def test_an_unknown_backend_name_fails() -> None:
    with pytest.raises(StorageError, match="잘못됐다"):
        backend_from_env({"STORAGE_BACKEND": "s3"})


def test_default_keeps_todays_behaviour() -> None:
    """설정을 안 건드리면 지금 그대로 돈다. 갈아타기는 사람이 정한다."""
    assert backend_from_env({}) is StorageBackend.GITHUB_LEGACY


# ── 설정을 어디서 읽는가 ────────────────────────────────────────────────


def test_env_beats_the_config_file(tmp_path: Path) -> None:
    """config를 고치려면 커밋과 머지가 필요한데, 잘못 전환했을 땐 그 시간이 없다."""
    config = tmp_path / "storage.yaml"
    config.write_text("backend: r2_migration\n", encoding="utf-8")

    from_file = load_backend(config, {**SECRETS})
    assert from_file == BackendChoice(StorageBackend.R2_MIGRATION, str(config))

    override = load_backend(config, {"STORAGE_BACKEND": "github_legacy", **SECRETS})
    assert override.backend is StorageBackend.GITHUB_LEGACY
    # 출처를 함께 들고 다녀야 로그에 적을 수 있다.
    assert "환경변수" in override.source


def test_a_missing_config_is_not_an_error(tmp_path: Path) -> None:
    choice = load_backend(tmp_path / "없음.yaml", {})
    assert choice.backend is StorageBackend.GITHUB_LEGACY
    assert choice.source == "기본값"


def test_the_repo_config_is_valid_and_still_legacy() -> None:
    """저장소에 커밋된 값. r2로 바뀌는 순간이 곧 전환이다."""
    choice = load_backend(Path("config/storage.yaml"), {})
    assert choice.backend is StorageBackend.GITHUB_LEGACY


# ── 올리기 ──────────────────────────────────────────────────────────────


def test_upload_verifies_by_reading_it_back(db: Path, store, tmp_path: Path) -> None:
    ref = upload_snapshot(store, db, tmp_path / "work")
    assert store.exists(ref.object_key)
    assert store.exists(CURRENT_KEY)
    assert ref.row_counts["rate_observations"] == 50
    assert ref.integrity_check == "ok"
    # 포인터가 방금 올린 것을 가리켜야 한다.
    assert SnapshotRef.from_json(store.get(CURRENT_KEY)).object_key == ref.object_key


def test_a_broken_db_is_refused_before_it_is_uploaded(tmp_path: Path, store) -> None:
    """깨진 DB를 올리면 다음 실행이 그걸 받아 복원한다. 그때는 되돌릴 곳이 없다."""
    broken = tmp_path / "broken.sqlite3"
    broken.write_bytes(b"SQLite format 3\x00" + b"\x00" * 500)
    with pytest.raises(StorageError):
        upload_snapshot(store, broken, tmp_path / "work")
    assert not store.exists(CURRENT_KEY)


def test_a_missing_db_is_refused(tmp_path: Path, store) -> None:
    with pytest.raises(StorageError, match="올릴 DB가 없다"):
        upload_snapshot(store, tmp_path / "없음.sqlite3", tmp_path / "work")


def test_a_corrupted_upload_leaves_the_pointer_alone(db: Path, tmp_path: Path) -> None:
    """검증 전에 포인터를 바꾸면, 검증이 실패했을 때 다음 실행이 깨진 것을 따라간다."""

    class CorruptingStore(LocalObjectStore):
        def get(self, key: str) -> bytes:
            data = super().get(key)
            return data[:-1] if key.startswith(SNAPSHOT_PREFIX) else data

    store = CorruptingStore(tmp_path / "bucket")
    with pytest.raises(StorageError, match="해시가 다르다"):
        upload_snapshot(store, db, tmp_path / "work")

    assert not store.exists(CURRENT_KEY)
    # 못 쓰는 객체를 남기지 않는다.
    assert store.list(SNAPSHOT_PREFIX) == []


def test_a_snapshot_that_loses_rows_is_refused(db: Path, tmp_path: Path) -> None:
    """해시가 같아도 행이 사라졌으면 안 된다. 사용자가 요구한 대조다."""

    class SwappingStore(LocalObjectStore):
        """받을 때 행이 적은 다른 DB를 돌려준다."""

        decoy: bytes = b""

        def get(self, key: str) -> bytes:
            if key.startswith(SNAPSHOT_PREFIX) and self.decoy:
                return self.decoy
            return super().get(key)

    thin = tmp_path / "thin.sqlite3"
    conn = sqlite3.connect(thin)
    conn.execute("CREATE TABLE rate_observations (id INTEGER PRIMARY KEY, rate TEXT)")
    conn.execute("CREATE TABLE institutions (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()

    store = SwappingStore(tmp_path / "bucket")
    packed = tmp_path / "thin.gz"
    with thin.open("rb") as fin, gzip.open(packed, "wb") as fout:
        fout.write(fin.read())
    store.decoy = packed.read_bytes()

    with pytest.raises(StorageError, match="해시가 다르다|행 수가 다르다"):
        upload_snapshot(store, db, tmp_path / "work")
    assert not store.exists(CURRENT_KEY)


# ── 내려받기 ────────────────────────────────────────────────────────────


def test_an_empty_store_does_not_produce_an_empty_db(tmp_path: Path, store) -> None:
    """§6.4. 여기서 빈 DB를 만들면 다음 발행이 관측 0건짜리 사이트를 올린다."""
    dest = tmp_path / "work" / "rate_monitor.sqlite3"
    with pytest.raises(StorageError, match="아직 올린 적이 없는"):
        restore_snapshot(store, dest, tmp_path / "w")
    assert not dest.exists()


def test_a_pointer_to_nothing_is_refused(db: Path, tmp_path: Path, store) -> None:
    upload_snapshot(store, db, tmp_path / "work")
    ref = SnapshotRef.from_json(store.get(CURRENT_KEY))
    store.delete(ref.object_key)

    dest = tmp_path / "out.sqlite3"
    with pytest.raises(StorageError, match="없는 객체를 가리킨다"):
        restore_snapshot(store, dest, tmp_path / "w")
    assert not dest.exists()


def test_a_hash_mismatch_is_refused(db: Path, tmp_path: Path, store) -> None:
    ref = upload_snapshot(store, db, tmp_path / "work")
    store.put(ref.object_key, gzip.compress("이건 DB가 아니다".encode()))

    dest = tmp_path / "out.sqlite3"
    with pytest.raises(StorageError, match="해시가 기록과 다르다"):
        restore_snapshot(store, dest, tmp_path / "w")
    assert not dest.exists()


def test_the_round_trip_is_byte_identical(db: Path, tmp_path: Path, store) -> None:
    """이게 전부다. 올린 것과 받은 것이 같지 않으면 나머지는 의미가 없다."""
    upload_snapshot(store, db, tmp_path / "work")
    dest = tmp_path / "out.sqlite3"
    restore_snapshot(store, dest, tmp_path / "w")
    assert dest.read_bytes() == db.read_bytes()
    assert inspect_db(dest) == inspect_db(db)


def test_restore_does_not_leave_a_half_written_db(db: Path, tmp_path: Path, store) -> None:
    """검증이 끝난 뒤 옮긴다. 중간에 죽어도 반쪽짜리가 제자리에 남지 않는다."""
    ref = upload_snapshot(store, db, tmp_path / "work")
    store.put(ref.object_key, gzip.compress("쓰레기".encode()))
    dest = tmp_path / "nested" / "out.sqlite3"
    with pytest.raises(StorageError):
        restore_snapshot(store, dest, tmp_path / "w")
    assert not dest.exists()


# ── 보관 ────────────────────────────────────────────────────────────────


def test_pruning_keeps_the_recent_ones(store) -> None:
    for i in range(12):
        store.put(f"{SNAPSHOT_PREFIX}2026080{i % 10}T00000{i % 10}Z-{i:08d}.sqlite3.gz", b"x")
    removed = prune_snapshots(store, keep=7)
    assert len(removed) == 5
    assert len(store.list(SNAPSHOT_PREFIX)) == 7


def test_pruning_never_removes_what_the_pointer_uses(db: Path, tmp_path: Path, store) -> None:
    """되돌아갈 자리를 지우면 마지막 것이 깨졌을 때 갈 데가 없다."""
    ref = upload_snapshot(store, db, tmp_path / "work")
    for i in range(10):
        store.put(f"{SNAPSHOT_PREFIX}2027010{i}T000000Z-{i:08d}.sqlite3.gz", b"x")

    removed = prune_snapshots(store, keep=1)
    assert ref.object_key not in removed
    assert store.exists(ref.object_key)


def test_snapshot_keys_sort_by_time() -> None:
    """이름순이 곧 시간순이라야 오래된 것을 고를 수 있다."""
    keys = [
        snapshot_key(datetime(2026, 8, 6, h, tzinfo=UTC), f"{h:08d}" * 8) for h in (1, 5, 23)
    ]
    assert keys == sorted(keys)
