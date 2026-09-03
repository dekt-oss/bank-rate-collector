"""배포용 SQLite 스냅샷 (명세서 v3.1 §3).

작업 중인 DB를 그대로 커밋하지 않는다. WAL 모드에서는 커밋 시점의 파일이
불완전할 수 있고, -wal/-shm이 분리돼 있으면 복원이 깨진다.

    stale-main writer gate
    → 모든 트랜잭션 종료
    → VACUUM INTO publish/rate_monitor.sqlite3
    → PRAGMA integrity_check
    → PRAGMA foreign_key_check
    → SHA256
    → manifest.json

integrity_check나 foreign_key_check가 실패하면 스냅샷을 배포하지 않는다.
또한 GitHub Actions의 main writer가 현재 origin/main보다 오래된 SHA이면
스냅샷 단계에서 fail-closed하여 R2/rate-data에 과거 코드 상태가 덮어쓰이지 않게 한다.
이전 배포본을 유지한다.
"""

import hashlib
import json
import os
import re
import sqlite3
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

from rate_monitor.domain.timeutil import now_kst

DEFAULT_PUBLISH_PATH = Path("publish/rate_monitor.sqlite3")
DEFAULT_MANIFEST_PATH = Path("publish/manifest.json")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")

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


def _guard_current_main_writer() -> None:
    """Block a queued/running GitHub Actions writer after ``main`` moved ahead.

    The production writers share one canonical R2/rate-data state.  GitHub queues can
    therefore start an old scheduled run long after newer code merged.  An old run is
    allowed to collect locally, but it must not cross the snapshot/publish boundary.

    Local runs, PR/evidence branches and non-main Actions remain unaffected.  On a
    main Actions writer, inability to prove the current remote main SHA fails closed.
    """

    if os.environ.get("GITHUB_ACTIONS") != "true":
        return
    if os.environ.get("GITHUB_REF") != "refs/heads/main":
        return

    run_sha = os.environ.get("GITHUB_SHA", "").strip().lower()
    if not _GIT_SHA_RE.fullmatch(run_sha):
        raise SnapshotIntegrityError(
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
        raise SnapshotIntegrityError(
            "stale-main writer gate: 현재 origin/main SHA를 검증하지 못했다"
        ) from exc

    rows = [line.split() for line in result.stdout.splitlines() if line.strip()]
    if len(rows) != 1 or len(rows[0]) != 2 or rows[0][1] != "refs/heads/main":
        raise SnapshotIntegrityError(
            "stale-main writer gate: origin/main 조회 결과가 단일 ref 계약을 만족하지 않는다"
        )
    remote_sha = rows[0][0].strip().lower()
    if not _GIT_SHA_RE.fullmatch(remote_sha):
        raise SnapshotIntegrityError(
            "stale-main writer gate: origin/main SHA 형식이 유효하지 않다"
        )
    if remote_sha != run_sha:
        raise SnapshotIntegrityError(
            "stale-main writer blocked: "
            f"run_sha={run_sha} current_main_sha={remote_sha}. "
            "오래 대기한 writer는 canonical R2/rate-data를 갱신할 수 없다"
        )


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
        SnapshotIntegrityError: stale main writer, integrity/FK 검증 실패 시.
    """
    if not work_db.exists():
        raise FileNotFoundError(f"작업 DB가 없다: {work_db}")

    # Canonical writer freshness is checked before touching an existing publish
    # artifact.  A stale queued run must leave the last known-good output intact.
    _guard_current_main_writer()

    publish_db.parent.mkdir(parents=True, exist_ok=True)
    if publish_db.exists():
        publish_db.unlink()

    # `VACUUM INTO`는 일관된 사본을 만들면서 **빈 자리를 함께 걷어낸다.**
    #
    # 예전에는 backup()을 썼다. 그때는 행이 지워질 일이 없어 차이가 없었지만,
    # 관측이 변경 이벤트로 바뀌면서 마이그레이션이 4만 행을 지운다. backup()은
    # 빈 페이지까지 그대로 복사하므로 실측에서 287 MB가 445 MB로 늘었다.
    # WAL 반영은 둘 다 한다.
    source = sqlite3.connect(work_db)
    try:
        source.execute("VACUUM INTO ?", (str(publish_db),))
    finally:
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
