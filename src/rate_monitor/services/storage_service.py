"""운영 상태 DB의 저장 위치 (선행 수정안 v1 §2.3, §6).

지금은 운영 DB가 Git 브랜치에 들어 있다. `rate-data/latest/` 아래 압축
SQLite를 두고 다음 실행이 그걸 내려받아 복원한다. DB가 관측을 누적하므로
파일이 계속 커지고, GitHub의 100 MB **개별 파일** 한도에 언젠가 부딪힌다.
2026-08-06 현재 50.75 MiB다.

옮길 곳은 R2다. 다만 **한 번에 갈아타지 않는다.** 계정과 버킷은 코드가
끝난 뒤에 만들 것이고, 그 전까지 수집이 멈추면 안 된다. 그래서 세 상태를
둔다.

    github_legacy   R2를 쓰지 않는다. 지금 그대로.
                    GitHub DB가 공식 원본이다.

    r2_migration    R2에 올리고 다시 받아 검증까지 한다. 그러나 복원은
                    여전히 GitHub에서 하고, rate-data의 DB도 그대로 둔다.
                    **R2는 시험 저장소다.** 여기서 R2가 실패해도 수집은
                    계속된다 — 실패를 크게 적을 뿐이다.

    r2              R2가 공식 원본이다. 복원도 R2에서 한다. 여기서 R2가
                    실패하면 **멈춘다.** GitHub에는 SQLite를 두지 않는다.

전환은 사람이 명시적으로 한다. 시크릿이 생겼다고 저절로 넘어가지 않는다 —
저절로 넘어가면 아무도 언제 넘어갔는지 모른다.

절대 하지 않는 것 (§6.4):

    - R2가 설정되지 않았다고 빈 DB를 만들지 않는다
    - 복원할 것을 못 찾았는데 빈 DB로 시작하지 않는다
    - 검증이 끝나기 전에 current 포인터를 바꾸지 않는다
"""

import gzip
import hashlib
import json
import os
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from rate_monitor.domain.timeutil import to_kst as _kst
from rate_monitor.services.canonical_writer_guard import (
    CanonicalWriterGuardError,
    ensure_current_main_writer,
)

CURRENT_KEY = "state/current.json"
SNAPSHOT_PREFIX = "state/snapshots/"

# 되돌아갈 자리를 남긴다. 마지막 것이 깨졌을 때 그 앞으로 갈 수 있어야 한다.
KEEP_SNAPSHOTS = 7

SCHEMA_VERSION = 1

# 검증에 쓰는 표. 행 수가 맞는지 대조한다.
COUNTED_TABLES = (
    "rate_observations",
    "institutions",
    "products",
    "product_variants",
    "collection_runs",
)


class StorageError(RuntimeError):
    """저장 계층 실패. 부르는 쪽이 상태에 따라 멈출지 말지 정한다."""


def _guard_current_main_writer() -> None:
    """Map canonical-writer freshness failures onto the storage error contract."""
    try:
        ensure_current_main_writer()
    except CanonicalWriterGuardError as exc:
        raise StorageError(str(exc)) from exc


class StorageBackend(StrEnum):
    GITHUB_LEGACY = "github_legacy"
    R2_MIGRATION = "r2_migration"
    R2 = "r2"

    @property
    def uses_r2(self) -> bool:
        """R2를 건드리는가.

        >>> [b.uses_r2 for b in StorageBackend]
        [False, True, True]
        """
        return self is not StorageBackend.GITHUB_LEGACY

    @property
    def r2_is_authoritative(self) -> bool:
        """R2가 공식 원본인가. 아니면 시험 저장소다.

        >>> StorageBackend.R2_MIGRATION.r2_is_authoritative
        False
        >>> StorageBackend.R2.r2_is_authoritative
        True
        """
        return self is StorageBackend.R2


# ── 객체 저장소 ─────────────────────────────────────────────────────────


class ObjectStore(Protocol):
    """S3 호환 저장소에서 우리가 쓰는 것만."""

    def put(self, key: str, data: bytes) -> None: ...
    def get(self, key: str) -> bytes: ...
    def exists(self, key: str) -> bool: ...
    def list(self, prefix: str) -> list[str]: ...
    def delete(self, key: str) -> None: ...


@dataclass(frozen=True)
class R2Config:
    """GitHub Secrets에서 읽는다 (§6.1). 공개 사이트에서는 쓰지 않는다."""

    account_id: str
    access_key_id: str
    secret_access_key: str
    bucket: str
    endpoint: str
    region: str = "auto"

    # 다섯 개가 다 있어야 설정된 것으로 본다.
    #
    # 저장 위치가 갈린다 — 비밀 둘은 Secrets, 나머지 셋은 Variables다.
    ENV_KEYS = (
        "R2_ACCOUNT_ID",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
        "R2_BUCKET",
        "R2_ENDPOINT",
    )
    # 없으면 auto. R2는 지역 개념이 없어 auto가 정답이다.
    OPTIONAL_ENV_KEYS = ("R2_REGION",)

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "R2Config | None":
        """다섯 개가 모두 있어야 설정된 것으로 본다.

        일부만 있으면 **없는 것으로 치지 않고 실패한다.** 절반만 채워 놓고
        R2에 올라가고 있다고 믿는 상태가 제일 나쁘다.

        >>> R2Config.from_env({}) is None
        True
        >>> R2Config.from_env({"R2_BUCKET": "b"})
        Traceback (most recent call last):
        rate_monitor.services.storage_service.StorageError: R2 설정이 일부만 있다...
        """
        source = os.environ if env is None else env
        present = {k: source.get(k, "") for k in cls.ENV_KEYS}
        filled = {k: v for k, v in present.items() if v}
        if not filled:
            return None
        if len(filled) != len(cls.ENV_KEYS):
            missing = ", ".join(k for k in cls.ENV_KEYS if k not in filled)
            raise StorageError(f"R2 설정이 일부만 있다. 빠진 것: {missing}")
        return cls(
            account_id=present["R2_ACCOUNT_ID"],
            access_key_id=present["R2_ACCESS_KEY_ID"],
            secret_access_key=present["R2_SECRET_ACCESS_KEY"],
            bucket=present["R2_BUCKET"],
            endpoint=present["R2_ENDPOINT"],
            region=(source.get("R2_REGION") or "auto").strip() or "auto",
        )


DEFAULT_CONFIG_PATH = Path("config/storage.yaml")


@dataclass(frozen=True)
class BackendChoice:
    """무엇이 골라졌고 **어디서 왔는지**.

    출처를 함께 들고 다녀야 로그에 적을 수 있다. 환경변수가 config를 이기는
    구조라, 어느 쪽이 먹혔는지 모르면 왜 이 모드로 도는지 알 수 없다.
    """

    backend: StorageBackend
    source: str


def load_backend(
    config_path: Path = DEFAULT_CONFIG_PATH, env: dict[str, str] | None = None
) -> BackendChoice:
    """환경변수 > config 파일 > 기본값.

    환경변수를 위에 두는 것은 되돌리기 위해서다. config를 고치려면 커밋과
    머지가 필요한데, 잘못 전환했을 때는 그 시간이 없다.
    """
    source = os.environ if env is None else env
    if (source.get("STORAGE_BACKEND") or "").strip():
        return BackendChoice(backend_from_env(source), "STORAGE_BACKEND 환경변수")

    if config_path.is_file():
        import yaml

        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        raw = str(data.get("backend") or "").strip()
        if raw:
            backend = _parse_backend(raw)
            _require_secrets(backend, source)
            return BackendChoice(backend, str(config_path))

    return BackendChoice(StorageBackend.GITHUB_LEGACY, "기본값")


def _parse_backend(raw: str) -> StorageBackend:
    try:
        return StorageBackend(raw)
    except ValueError as exc:
        allowed = ", ".join(b.value for b in StorageBackend)
        raise StorageError(f"backend 값이 잘못됐다: {raw!r} (가능: {allowed})") from exc


def _require_secrets(backend: StorageBackend, source: Any) -> None:
    """R2를 쓰겠다고 했으면 시크릿이 있어야 한다.

    조용히 legacy로 떨어뜨리지 않는다. 그러면 R2에 저장되고 있다고 믿는
    채로 몇 주가 지나갈 수 있다.
    """
    if backend.uses_r2 and R2Config.from_env(source) is None:
        raise StorageError(
            f"backend={backend.value} 인데 R2 시크릿이 없다. "
            f"필요: {', '.join(R2Config.ENV_KEYS)}"
        )


def backend_from_env(env: dict[str, str] | None = None) -> StorageBackend:
    """`STORAGE_BACKEND`. 없으면 지금 동작을 유지한다.

    R2를 쓰겠다고 했는데 시크릿이 없으면 **실패한다.** 조용히 legacy로
    떨어지면 R2에 저장되고 있다고 믿는 채로 몇 주가 지나갈 수 있다.

    >>> backend_from_env({})
    <StorageBackend.GITHUB_LEGACY: 'github_legacy'>
    >>> backend_from_env({"STORAGE_BACKEND": "r2"})
    Traceback (most recent call last):
    rate_monitor.services.storage_service.StorageError: backend=r2 인데 R2 시크릿이 없다...
    """
    source = os.environ if env is None else env
    raw = (source.get("STORAGE_BACKEND") or "").strip() or StorageBackend.GITHUB_LEGACY
    backend = _parse_backend(str(raw))
    _require_secrets(backend, source)
    return backend


# ── 스냅샷 ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SnapshotRef:
    """`state/current.json`에 그대로 실리는 값 (§2.3)."""

    schema_version: int
    object_key: str
    sha256: str
    compressed_bytes: int
    sqlite_bytes: int
    generated_at: str
    integrity_check: str
    foreign_key_check_violations: int
    row_counts: dict[str, int]

    def to_json(self) -> str:
        return json.dumps(self.__dict__, ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, raw: bytes | str) -> "SnapshotRef":
        data = json.loads(raw)
        known = {k: data[k] for k in cls.__dataclass_fields__ if k in data}
        return cls(**known)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_db(path: Path) -> tuple[str, int, dict[str, int]]:
    """무결성·외래키·행 수. 올리기 전에 본다.

    깨진 DB를 올리면 다음 실행이 그걸 받아 복원한다. 그때는 되돌릴 곳이
    없다 — 올리기 전에 막는 편이 훨씬 싸다.
    """
    conn = sqlite3.connect(path)
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        violations = len(conn.execute("PRAGMA foreign_key_check").fetchall())
        counts: dict[str, int] = {}
        for table in COUNTED_TABLES:
            try:
                counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            except sqlite3.OperationalError:
                # 표가 아직 없는 초기 DB도 있다. 없는 것과 0건은 다르다.
                continue
    except sqlite3.DatabaseError as exc:
        # SQLite로 열리지도 않는 파일. 이것도 저장소 실패다 — 부르는 쪽이
        # sqlite3 예외까지 따로 잡게 하면 어딘가에서 빠뜨린다.
        raise StorageError(f"SQLite로 열리지 않는다: {path.name} ({exc})") from exc
    finally:
        conn.close()
    return integrity, violations, counts


def _compress(src: Path, dest: Path) -> None:
    """gzip으로 압축한다.

    명세서는 zstd를 권했지만 gzip을 쓴다. 파이썬 3.12 표준 라이브러리에
    zstd가 없어 의존성이 하나 늘고, 이 파일은 하루 한 번 오가는 것이라
    압축률 차이가 비용에 거의 영향을 주지 않는다. 표준 도구로 아무 데서나
    풀 수 있다는 쪽이 낫다 — 백업은 꺼낼 수 있어야 백업이다.
    """
    with src.open("rb") as fin, gzip.open(dest, "wb", compresslevel=9) as fout:
        shutil.copyfileobj(fin, fout)


def _decompress(src: Path, dest: Path) -> None:
    with gzip.open(src, "rb") as fin, dest.open("wb") as fout:
        shutil.copyfileobj(fin, fout)


def snapshot_key(generated_at: datetime, digest: str) -> str:
    """시각이 앞에 오는 키. 이름순이 곧 시간순이라야 오래된 것을 고를 수 있다.

    시각은 한국시간이다. 버킷을 열어 보는 사람이 한국에 있고, `Z`가 붙어
    있으면 UTC로 읽는다 — 그래서 붙이지 않는다.

    >>> snapshot_key(datetime(2026, 8, 6, 2, 15, tzinfo=UTC), "abcd1234" * 8)
    'state/snapshots/20260806T111500-abcd1234.sqlite3.gz'

    이름순 정렬이 시간순과 어긋나지 않는다. 모두 같은 시간대를 쓰므로
    UTC일 때와 순서가 같다.

    >>> a = snapshot_key(datetime(2026, 8, 5, 23, 0, tzinfo=UTC), "a" * 64)
    >>> b = snapshot_key(datetime(2026, 8, 6, 1, 0, tzinfo=UTC), "b" * 64)
    >>> a < b
    True
    """
    stamp = _kst(generated_at).strftime("%Y%m%dT%H%M%S")
    return f"{SNAPSHOT_PREFIX}{stamp}-{digest[:8]}.sqlite3.gz"


# ── 올리기 ──────────────────────────────────────────────────────────────


def upload_snapshot(
    store: ObjectStore, db_path: Path, work_dir: Path, *, now: datetime | None = None
) -> SnapshotRef:
    """DB 한 벌을 올리고, 다시 받아 확인한 뒤에야 포인터를 바꾼다 (§6.3).

    순서가 중요하다. 검증 전에 `current.json`을 건드리면, 검증이 실패했을
    때 다음 실행이 깨진 스냅샷을 가리키는 포인터를 따라간다.
    """
    if not db_path.is_file():
        raise StorageError(f"올릴 DB가 없다: {db_path}")

    integrity, violations, counts = inspect_db(db_path)
    if integrity != "ok":
        raise StorageError(f"integrity_check 실패: {integrity}")
    if violations:
        raise StorageError(f"foreign_key_check 위반 {violations}건")

    work_dir.mkdir(parents=True, exist_ok=True)
    packed = work_dir / "snapshot.sqlite3.gz"
    _compress(db_path, packed)

    digest = sha256_of(packed)
    generated_at = now or datetime.now(UTC)
    key = snapshot_key(generated_at, digest)

    # A long writer may have been current at snapshot time and become stale while
    # building/gating the publish payload. Re-check before the first R2 mutation.
    _guard_current_main_writer()
    store.put(key, packed.read_bytes())

    # 다시 받아 확인한다. put이 성공했다는 말과 실제로 그 바이트가 거기
    # 있다는 것은 다르다.
    fetched = work_dir / "verify.sqlite3.gz"
    fetched.write_bytes(store.get(key))
    if sha256_of(fetched) != digest:
        store.delete(key)
        raise StorageError(f"올린 것과 받은 것의 해시가 다르다: {key}")

    # 풀어서 DB로 열리는지까지 본다. 해시가 같아도 압축이 깨졌을 수 있다.
    restored = work_dir / "verify.sqlite3"
    _decompress(fetched, restored)
    back_integrity, back_violations, back_counts = inspect_db(restored)
    if back_integrity != "ok" or back_violations:
        store.delete(key)
        raise StorageError(
            f"받아서 연 DB가 성하지 않다: integrity={back_integrity}, fk={back_violations}"
        )
    if back_counts != counts:
        store.delete(key)
        raise StorageError(f"행 수가 다르다. 올린 것 {counts}, 받은 것 {back_counts}")

    ref = SnapshotRef(
        schema_version=SCHEMA_VERSION,
        object_key=key,
        sha256=digest,
        compressed_bytes=packed.stat().st_size,
        sqlite_bytes=db_path.stat().st_size,
        generated_at=generated_at.isoformat(),
        integrity_check=integrity,
        foreign_key_check_violations=violations,
        row_counts=counts,
    )
    # Pointer movement is the canonical commit. Re-check immediately before it.
    # If main moved during upload/readback verification, delete the now-orphaned
    # snapshot and leave current.json untouched.
    try:
        _guard_current_main_writer()
    except StorageError:
        store.delete(key)
        raise
    store.put(CURRENT_KEY, ref.to_json().encode("utf-8"))
    prune_snapshots(store)
    return ref


CHECK_PREFIX = "state/_check/"


def check_round_trip(store: ObjectStore, *, now: datetime | None = None) -> dict[str, Any]:
    """저장소가 실제로 오가는지 본다. 쓰고 → 확인하고 → 읽고 → 지운다.

    자격증명이 맞는지, 버킷이 있는지, 권한이 쓰기·읽기·삭제까지 다 있는지를
    한 번에 확인한다. 자격증명만 검사하면 "붙기는 하는데 못 쓰는" 상태를
    통과시킨다.

    **끝나면 지운다.** 시험 흔적을 저장소에 남기면 다음 사람이 그게 진짜
    데이터인 줄 안다. 실패해도 지우려 시도한다.
    """
    stamp = _kst(now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%S%f")
    key = f"{CHECK_PREFIX}{stamp}.bin"
    # 압축이 잘 안 되는 내용이라야 왕복이 진짜인지 알 수 있다.
    body = hashlib.sha256(stamp.encode()).digest() * 64  # 2 KiB
    expected = hashlib.sha256(body).hexdigest()

    steps: list[tuple[str, str]] = []
    try:
        store.put(key, body)
        steps.append(("업로드", key))

        if not store.exists(key):
            raise StorageError(f"올렸는데 없다고 나온다: {key}")
        steps.append(("존재 확인", "HEAD ok"))

        listed = store.list(CHECK_PREFIX)
        if key not in listed:
            raise StorageError(f"목록에 안 보인다: {key} (목록 {len(listed)}건)")
        steps.append(("목록 조회", f"{len(listed)}건 중 발견"))

        fetched = store.get(key)
        steps.append(("다운로드", f"{len(fetched):,} bytes"))

        actual = hashlib.sha256(fetched).hexdigest()
        if actual != expected:
            raise StorageError(f"SHA256 불일치: 올림 {expected[:12]}, 받음 {actual[:12]}")
        steps.append(("SHA256 대조", f"{actual[:16]}… 일치"))
    finally:
        # 실패해도 치운다. 못 지우면 그것도 알아야 한다.
        try:
            store.delete(key)
            steps.append(("삭제", "완료"))
        except Exception as exc:  # noqa: BLE001 — 삭제 실패가 검사를 가리면 안 된다
            steps.append(("삭제", f"실패: {exc}"))

    if store.exists(key):
        raise StorageError(f"지웠는데 아직 있다: {key}")
    steps.append(("삭제 확인", "없음"))

    return {"key": key, "sha256": expected, "bytes": len(body), "steps": steps}


def prune_snapshots(store: ObjectStore, keep: int = KEEP_SNAPSHOTS) -> list[str]:
    """오래된 스냅샷을 지운다. 키에 시각이 들어 있어 이름순이 곧 시간순이다.

    현재 포인터가 가리키는 것은 몇 번째든 지우지 않는다.
    """
    keys = sorted(store.list(SNAPSHOT_PREFIX))
    current: str | None = None
    if store.exists(CURRENT_KEY):
        current = SnapshotRef.from_json(store.get(CURRENT_KEY)).object_key

    removed = []
    for key in keys[:-keep] if keep else keys:
        if key == current:
            continue
        store.delete(key)
        removed.append(key)
    return removed


# ── 내려받기 ────────────────────────────────────────────────────────────


def restore_snapshot(store: ObjectStore, dest: Path, work_dir: Path) -> SnapshotRef:
    """포인터를 따라 DB를 되살린다. 실패하면 **빈 DB를 만들지 않고 던진다.**

    §6.4 — 여기서 조용히 빈 DB를 만들면 다음 발행이 관측 0건짜리 사이트를
    올리고, 그때는 이미 예전 것을 덮어쓴 뒤다.
    """
    if not store.exists(CURRENT_KEY):
        raise StorageError(f"{CURRENT_KEY}가 없다. 아직 올린 적이 없는 저장소다")

    ref = SnapshotRef.from_json(store.get(CURRENT_KEY))
    if not store.exists(ref.object_key):
        raise StorageError(f"포인터가 없는 객체를 가리킨다: {ref.object_key}")

    work_dir.mkdir(parents=True, exist_ok=True)
    packed = work_dir / "restore.sqlite3.gz"
    packed.write_bytes(store.get(ref.object_key))

    digest = sha256_of(packed)
    if digest != ref.sha256:
        raise StorageError(
            f"해시가 기록과 다르다. 기록 {ref.sha256[:12]}, 실제 {digest[:12]}"
        )

    dest.parent.mkdir(parents=True, exist_ok=True)
    staged = work_dir / "restore.sqlite3"
    _decompress(packed, staged)

    integrity, violations, counts = inspect_db(staged)
    if integrity != "ok" or violations:
        raise StorageError(
            f"받은 DB가 성하지 않다: integrity={integrity}, fk={violations}"
        )
    if ref.row_counts and counts != ref.row_counts:
        raise StorageError(f"행 수가 기록과 다르다. 기록 {ref.row_counts}, 실제 {counts}")

    # 검증이 끝난 뒤에 제자리로 옮긴다. 중간에 죽어도 반쪽짜리 DB가 남지
    # 않는다.
    shutil.move(str(staged), dest)
    return ref


# ── R2 ──────────────────────────────────────────────────────────────────


class R2ObjectStore:
    """boto3로 R2에 붙는다. R2는 S3 호환이라 같은 API를 쓴다."""

    def __init__(self, config: R2Config, client: Any = None) -> None:
        self._bucket = config.bucket
        if client is not None:
            self._client = client
            return
        try:
            import boto3
        except ImportError as exc:  # pragma: no cover - 의존성이 있으면 안 탄다
            raise StorageError("boto3가 필요하다. `uv sync`로 설치한다") from exc
        self._client = boto3.client(
            "s3",
            endpoint_url=config.endpoint,
            aws_access_key_id=config.access_key_id,
            aws_secret_access_key=config.secret_access_key,
            region_name=config.region,
        )

    def put(self, key: str, data: bytes) -> None:
        self._client.put_object(Bucket=self._bucket, Key=key, Body=data)

    def get(self, key: str) -> bytes:
        return self._client.get_object(Bucket=self._bucket, Key=key)["Body"].read()

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
        except Exception:  # noqa: BLE001 — 없다는 것을 예외로 알리는 API다
            return False
        return True

    def list(self, prefix: str) -> list[str]:
        keys: list[str] = []
        token: str | None = None
        while True:
            kwargs: dict[str, Any] = {"Bucket": self._bucket, "Prefix": prefix}
            if token:
                kwargs["ContinuationToken"] = token
            page = self._client.list_objects_v2(**kwargs)
            keys.extend(item["Key"] for item in page.get("Contents", []))
            if not page.get("IsTruncated"):
                return keys
            token = page.get("NextContinuationToken")

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=key)


class LocalObjectStore:
    """디렉터리를 객체 저장소처럼 쓴다. 시험용이고 R2 없이 전 구간을 돈다."""

    def __init__(self, root: Path) -> None:
        self._root = root
        root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self._root / key

    def put(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def get(self, key: str) -> bytes:
        path = self._path(key)
        if not path.is_file():
            raise StorageError(f"객체가 없다: {key}")
        return path.read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def list(self, prefix: str) -> list[str]:
        base = self._root
        return sorted(
            p.relative_to(base).as_posix()
            for p in base.rglob("*")
            if p.is_file() and p.relative_to(base).as_posix().startswith(prefix)
        )

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)


def open_store(config: R2Config | None, local_root: Path | None = None) -> ObjectStore:
    """설정이 있으면 R2, `local_root`를 주면 디렉터리."""
    if config is not None:
        return R2ObjectStore(config)
    if local_root is not None:
        return LocalObjectStore(local_root)
    raise StorageError("R2 설정도 로컬 경로도 없다")
