"""R2 lifecycle policy for raw evidence and rebuildable intermediate artifacts.

Three retention tiers are intentionally separate:

1. ``state/snapshots/``: authoritative operational DB snapshots. The existing
   storage service keeps the latest seven and protects the current pointer.
2. ``raw-evidence/``: immutable source evidence. This module never deletes it.
3. ``intermediate/``: rebuildable candidate/reconciliation artifacts. Only this
   prefix may be age-pruned, with a 30-day default and dry-run by default.

The delete boundary is deliberately narrower than an S3/R2 bucket lifecycle
rule so every deletion decision is visible in repository code and workflow logs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any

from rate_monitor.services.storage_service import (
    ObjectStore,
    R2Config,
    StorageError,
    open_store,
)

RAW_EVIDENCE_PREFIX = "raw-evidence/"
INTERMEDIATE_PREFIX = "intermediate/"
INTERMEDIATE_RETENTION_DAYS = 30
PROTECTED_PREFIXES = ("state/", RAW_EVIDENCE_PREFIX)
_TIMESTAMP_FORMAT = "%Y%m%dT%H%M%SZ"
_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9._-]+$")


@dataclass(frozen=True)
class EvidenceObject:
    relative_path: str
    object_key: str
    sha256: str
    bytes: int


def _safe_component(value: str, *, name: str) -> str:
    text = value.strip()
    if not text or not _SAFE_COMPONENT.fullmatch(text):
        raise StorageError(f"{name}에 허용되지 않은 문자가 있다: {value!r}")
    return text


def _safe_relative_path(path: Path, root: Path) -> str:
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError as exc:
        raise StorageError(f"raw evidence root 밖의 파일이다: {path}") from exc
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts:
        raise StorageError(f"안전하지 않은 evidence 상대경로다: {relative}")
    return pure.as_posix()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def raw_evidence_key(category: str, run_id: str, relative_path: str) -> str:
    category = _safe_component(category, name="category")
    run_id = _safe_component(run_id, name="run_id")
    pure = PurePosixPath(relative_path)
    if pure.is_absolute() or not pure.parts or ".." in pure.parts:
        raise StorageError(f"안전하지 않은 evidence 상대경로다: {relative_path}")
    return f"{RAW_EVIDENCE_PREFIX}{category}/{run_id}/{pure.as_posix()}"


def _put_immutable(store: ObjectStore, key: str, data: bytes) -> str:
    digest = _sha256(data)
    if store.exists(key):
        existing = store.get(key)
        if _sha256(existing) != digest:
            raise StorageError(f"immutable evidence key 충돌: {key}")
        return digest
    store.put(key, data)
    if not store.exists(key):
        raise StorageError(f"evidence 업로드 후 객체가 없다: {key}")
    fetched = store.get(key)
    if _sha256(fetched) != digest:
        raise StorageError(f"evidence R2 readback SHA256 불일치: {key}")
    return digest


def persist_raw_tree(
    store: ObjectStore,
    *,
    root: Path,
    category: str,
    run_id: str,
) -> dict[str, Any]:
    """Persist every file below ``root`` under an immutable run-scoped prefix."""
    if not root.is_dir():
        return {
            "category": category,
            "run_id": run_id,
            "root": str(root),
            "objects": [],
            "object_count": 0,
            "total_bytes": 0,
            "status": "no_raw_directory",
        }

    objects: list[EvidenceObject] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = _safe_relative_path(path, root)
        key = raw_evidence_key(category, run_id, relative)
        data = path.read_bytes()
        digest = _put_immutable(store, key, data)
        objects.append(
            EvidenceObject(
                relative_path=relative,
                object_key=key,
                sha256=digest,
                bytes=len(data),
            )
        )

    manifest = {
        "schema_version": 1,
        "category": category,
        "run_id": run_id,
        "retention": "long_term_no_auto_delete",
        "objects": [item.__dict__ for item in objects],
        "object_count": len(objects),
        "total_bytes": sum(item.bytes for item in objects),
    }
    manifest_key = raw_evidence_key(category, run_id, "manifest.json")
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode(
        "utf-8"
    )
    _put_immutable(store, manifest_key, manifest_bytes)
    return {**manifest, "manifest_key": manifest_key, "status": "stored"}


def intermediate_key(
    *,
    category: str,
    name: str,
    generated_at: datetime | None = None,
) -> str:
    """Create a timestamped key that can be pruned without object metadata."""
    category = _safe_component(category, name="category")
    name = _safe_component(name, name="name")
    stamp = (generated_at or datetime.now(UTC)).astimezone(UTC).strftime(
        _TIMESTAMP_FORMAT
    )
    return f"{INTERMEDIATE_PREFIX}{stamp}/{category}/{name}"


def put_intermediate(
    store: ObjectStore,
    *,
    category: str,
    name: str,
    data: bytes,
    generated_at: datetime | None = None,
) -> str:
    key = intermediate_key(category=category, name=name, generated_at=generated_at)
    store.put(key, data)
    return key


def _intermediate_timestamp(key: str) -> datetime | None:
    if not key.startswith(INTERMEDIATE_PREFIX):
        return None
    remainder = key[len(INTERMEDIATE_PREFIX) :]
    stamp = remainder.split("/", 1)[0]
    try:
        return datetime.strptime(stamp, _TIMESTAMP_FORMAT).replace(tzinfo=UTC)
    except ValueError:
        return None


def _assert_deletable(key: str) -> None:
    if any(key.startswith(prefix) for prefix in PROTECTED_PREFIXES):
        raise StorageError(f"보호 prefix 삭제 시도: {key}")
    if not key.startswith(INTERMEDIATE_PREFIX):
        raise StorageError(f"intermediate 외 객체 삭제 시도: {key}")


def cleanup_intermediate(
    store: ObjectStore,
    *,
    now: datetime | None = None,
    retention_days: int = INTERMEDIATE_RETENTION_DAYS,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Delete only timestamped intermediate objects older than retention."""
    if retention_days < 1:
        raise ValueError("retention_days는 1 이상이어야 한다")
    current = (now or datetime.now(UTC)).astimezone(UTC)
    cutoff = current - timedelta(days=retention_days)
    candidates: list[str] = []
    skipped_unparseable: list[str] = []
    for key in sorted(store.list(INTERMEDIATE_PREFIX)):
        generated_at = _intermediate_timestamp(key)
        if generated_at is None:
            skipped_unparseable.append(key)
            continue
        if generated_at < cutoff:
            _assert_deletable(key)
            candidates.append(key)

    deleted: list[str] = []
    if not dry_run:
        for key in candidates:
            _assert_deletable(key)
            store.delete(key)
            deleted.append(key)

    return {
        "retention_days": retention_days,
        "cutoff": cutoff.isoformat(),
        "dry_run": dry_run,
        "candidates": candidates,
        "deleted": deleted,
        "skipped_unparseable": skipped_unparseable,
    }


def _r2_store() -> ObjectStore:
    config = R2Config.from_env()
    if config is None:
        raise StorageError("R2 evidence lifecycle 실행에 R2 설정이 필요하다")
    return open_store(config)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="R2 evidence lifecycle")
    sub = parser.add_subparsers(dest="command", required=True)

    upload = sub.add_parser("upload-raw")
    upload.add_argument("--root", type=Path, required=True)
    upload.add_argument("--category", required=True)
    upload.add_argument("--run-id", required=True)

    cleanup = sub.add_parser("cleanup-intermediate")
    cleanup.add_argument("--retention-days", type=int, default=INTERMEDIATE_RETENTION_DAYS)
    cleanup.add_argument("--apply", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    store = _r2_store()
    if args.command == "upload-raw":
        result = persist_raw_tree(
            store,
            root=args.root,
            category=args.category,
            run_id=args.run_id,
        )
    else:
        result = cleanup_intermediate(
            store,
            retention_days=args.retention_days,
            dry_run=not args.apply,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
