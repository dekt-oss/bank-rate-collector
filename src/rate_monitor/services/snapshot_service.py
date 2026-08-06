"""배포용 SQLite 스냅샷 (명세서 v3.1 §3).

작업 중인 DB를 그대로 커밋하지 않는다. WAL 모드에서는 커밋 시점의 파일이
불완전할 수 있고, -wal/-shm이 분리돼 있으면 복원이 깨진다.

    모든 트랜잭션 종료
    → Connection.backup() → publish/rate_monitor.sqlite3
    → PRAGMA integrity_check
    → PRAGMA foreign_key_check
    → SHA256
    → manifest.json

integrity_check나 foreign_key_check가 실패하면 스냅샷을 배포하지 않는다.
이전 배포본을 유지한다.
"""

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path

from rate_monitor.domain.timeutil import now_kst

DEFAULT_PUBLISH_PATH = Path("publish/rate_monitor.sqlite3")
DEFAULT_MANIFEST_PATH = Path("publish/manifest.json")

# manifest에 행 수를 기록할 테이블. 대시보드가 대조에 쓴다.
COUNTED_TABLES = (
    "institutions",
    "products",
    "product_variants",
    "rate_observations",
    "collection_runs",
    "raw_artifacts",
    "review_items",
)


class SnapshotIntegrityError(RuntimeError):
    """스냅샷 무결성 검사 실패. 배포하지 않는다."""


@dataclass
class Manifest:
    generated_at: str
    run_id: str | None
    sqlite_sha256: str
    sqlite_bytes: int
    integrity_check: str
    foreign_key_check_violations: int
    row_counts: dict[str, int] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2, sort_keys=True)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _row_counts(conn: sqlite3.Connection) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in COUNTED_TABLES:
        counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    return counts


def create_snapshot(
    work_db: Path,
    publish_db: Path = DEFAULT_PUBLISH_PATH,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    *,
    run_id: str | None = None,
) -> Manifest:
    """작업 DB에서 일관된 배포 스냅샷을 만든다.

    Raises:
        SnapshotIntegrityError: integrity_check가 ok가 아니거나 FK 위반이 있을 때.
    """
    if not work_db.exists():
        raise FileNotFoundError(f"작업 DB가 없다: {work_db}")

    publish_db.parent.mkdir(parents=True, exist_ok=True)
    if publish_db.exists():
        publish_db.unlink()

    # backup()은 열린 DB에서 일관된 사본을 만든다. 파일 복사와 달리 WAL을 반영한다.
    source = sqlite3.connect(work_db)
    target = sqlite3.connect(publish_db)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()

    conn = sqlite3.connect(publish_db)
    try:
        # backup()은 원본의 journal_mode(WAL)를 물려준다. 배포본이 WAL이면
        # 이후 쓰기가 -wal 사이드카로 가서 본체 바이트가 안 바뀐다. 그러면
        # manifest의 SHA256이 변조를 잡지 못하고, v3.1 §3이 금지한 사이드카
        # 파일 없이는 복원도 불완전해진다. 단일 파일로 완결시킨다.
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.commit()

        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        counts = _row_counts(conn)
    finally:
        conn.close()

    # 사이드카가 남아 있으면 배포본이 자족적이지 않다.
    for suffix in ("-wal", "-shm"):
        sidecar = publish_db.with_name(publish_db.name + suffix)
        sidecar.unlink(missing_ok=True)

    if integrity != "ok":
        publish_db.unlink(missing_ok=True)
        raise SnapshotIntegrityError(f"integrity_check 실패: {integrity}")
    if violations:
        publish_db.unlink(missing_ok=True)
        raise SnapshotIntegrityError(f"foreign_key_check 위반 {len(violations)}건")

    manifest = Manifest(
        generated_at=now_kst().isoformat(),
        run_id=run_id,
        sqlite_sha256=sha256_of(publish_db),
        sqlite_bytes=publish_db.stat().st_size,
        integrity_check=integrity,
        foreign_key_check_violations=0,
        row_counts=counts,
    )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(manifest.to_json(), encoding="utf-8")
    return manifest


def verify_snapshot(publish_db: Path, manifest_path: Path) -> None:
    """배포본이 manifest와 일치하는지 확인한다 (P1-A 게이트).

    Raises:
        SnapshotIntegrityError: 해시나 행 수가 어긋날 때.
    """
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    actual_hash = sha256_of(publish_db)
    if actual_hash != manifest["sqlite_sha256"]:
        raise SnapshotIntegrityError(
            f"SHA256 불일치: manifest={manifest['sqlite_sha256']} 실제={actual_hash}"
        )

    conn = sqlite3.connect(publish_db)
    try:
        actual_counts = _row_counts(conn)
    finally:
        conn.close()
    if actual_counts != manifest["row_counts"]:
        raise SnapshotIntegrityError(
            f"행 수 불일치: manifest={manifest['row_counts']} 실제={actual_counts}"
        )
