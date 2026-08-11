"""Durable checkpoint primitives for long-running source acquisition.

This module deliberately knows nothing about NH ``brc`` or KFCC ``gmgoCd``.
Adapters provide deterministic work keys and fully built ``RawArtifactData`` objects;
this layer only persists immutable chunks/manifests and decides whether a same-cycle
checkpoint is safe to resume.

Checkpoint state is staging/evidence, never canonical rate data.
"""

from __future__ import annotations

import dataclasses
import hashlib
import io
import json
import tarfile
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any

from rate_monitor.domain.schemas import RawArtifactData
from rate_monitor.services.storage_service import ObjectStore, StorageError

CHECKPOINT_PREFIX = "checkpoints/v1"
CHECKPOINT_SCHEMA_VERSION = 1
CHECKPOINT_CONTRACT_VERSION = 1
ACTIVE_SCHEMA_VERSION = 1

RESUMABLE_STATUSES = frozenset({"collecting", "recoverable_failed", "complete"})
TERMINAL_STATUSES = frozenset(
    {
        "guard_tripped",
        "blocked",
        "contract_failed",
        "abandoned",
        "canonical_committed",
    }
)
ALL_STATUSES = RESUMABLE_STATUSES | TERMINAL_STATUSES


class CheckpointError(StorageError):
    """Base error for resumable-acquisition checkpoint state."""


class CheckpointCorruptError(CheckpointError):
    """A checkpoint object exists but fails schema/hash/integrity validation."""


class CheckpointIncompatibleError(CheckpointError):
    """The active checkpoint belongs to a different acquisition contract."""


@dataclass(frozen=True)
class AcquisitionSessionIdentity:
    source_id: str
    cycle_date_kst: str
    request_fingerprint: str
    checkpoint_contract_version: int = CHECKPOINT_CONTRACT_VERSION
    acquisition_contract_version: int = 1


@dataclass(frozen=True)
class CheckpointArtifact:
    work_key: str
    artifact: RawArtifactData
    captured_at: str | None = None


@dataclass(frozen=True)
class CheckpointChunkRef:
    sequence: int
    object_key: str
    sha256: str
    item_count: int
    bytes: int
    created_at: str


@dataclass(frozen=True)
class AcquisitionManifest:
    schema_version: int
    source_id: str
    session_id: str
    cycle_date_kst: str
    request_fingerprint: str
    checkpoint_contract_version: int
    acquisition_contract_version: int
    revision: int
    status: str
    work_plan_hash: str | None
    expected_work_count: int | None
    completed_work_count: int
    completed_work_keys: tuple[str, ...]
    chunks: tuple[CheckpointChunkRef, ...]
    guard_state: dict[str, Any] | None
    terminal_reason_code: str | None
    terminal_reason: str | None
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        data = dataclasses.asdict(self)
        data["completed_work_keys"] = list(self.completed_work_keys)
        data["chunks"] = [dataclasses.asdict(chunk) for chunk in self.chunks]
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AcquisitionManifest":
        try:
            chunks = tuple(CheckpointChunkRef(**item) for item in data["chunks"])
            manifest = cls(
                schema_version=int(data["schema_version"]),
                source_id=str(data["source_id"]),
                session_id=str(data["session_id"]),
                cycle_date_kst=str(data["cycle_date_kst"]),
                request_fingerprint=str(data["request_fingerprint"]),
                checkpoint_contract_version=int(data["checkpoint_contract_version"]),
                acquisition_contract_version=int(data["acquisition_contract_version"]),
                revision=int(data["revision"]),
                status=str(data["status"]),
                work_plan_hash=(
                    None if data.get("work_plan_hash") is None else str(data["work_plan_hash"])
                ),
                expected_work_count=(
                    None
                    if data.get("expected_work_count") is None
                    else int(data["expected_work_count"])
                ),
                completed_work_count=int(data["completed_work_count"]),
                completed_work_keys=tuple(str(v) for v in data["completed_work_keys"]),
                chunks=chunks,
                guard_state=(
                    None if data.get("guard_state") is None else dict(data["guard_state"])
                ),
                terminal_reason_code=(
                    None
                    if data.get("terminal_reason_code") is None
                    else str(data["terminal_reason_code"])
                ),
                terminal_reason=(
                    None if data.get("terminal_reason") is None else str(data["terminal_reason"])
                ),
                created_at=str(data["created_at"]),
                updated_at=str(data["updated_at"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise CheckpointCorruptError(f"checkpoint manifest 형식이 잘못됐다: {exc}") from exc
        _validate_manifest(manifest)
        return manifest


@dataclass(frozen=True)
class ActiveCheckpointRef:
    schema_version: int
    source_id: str
    cycle_date_kst: str
    session_id: str
    manifest_key: str
    manifest_sha256: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ActiveCheckpointRef":
        try:
            ref = cls(
                schema_version=int(data["schema_version"]),
                source_id=str(data["source_id"]),
                cycle_date_kst=str(data["cycle_date_kst"]),
                session_id=str(data["session_id"]),
                manifest_key=str(data["manifest_key"]),
                manifest_sha256=str(data["manifest_sha256"]),
                updated_at=str(data["updated_at"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise CheckpointCorruptError(f"active checkpoint 형식이 잘못됐다: {exc}") from exc
        if ref.schema_version != ACTIVE_SCHEMA_VERSION:
            raise CheckpointCorruptError(
                f"active schema_version={ref.schema_version}, expected={ACTIVE_SCHEMA_VERSION}"
            )
        if not ref.manifest_key.startswith(CHECKPOINT_PREFIX + "/"):
            raise CheckpointCorruptError("active manifest_key가 checkpoint namespace 밖을 가리킨다")
        return ref


@dataclass(frozen=True)
class RecoveryDecision:
    eligible: bool
    reason_code: str
    source_id: str
    cycle_date_kst: str
    session_id: str | None
    manifest_status: str | None
    completed_work_count: int

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)


def canonical_fingerprint(value: Any) -> str:
    """Hash a JSON-compatible acquisition contract deterministically."""
    return _sha256(_canonical_json_bytes(value))


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _iso(now: datetime) -> str:
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    return now.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_iso(raw: str) -> datetime:
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CheckpointCorruptError(f"checkpoint timestamp가 잘못됐다: {raw!r}") from exc
    if value.tzinfo is None:
        raise CheckpointCorruptError(f"checkpoint timestamp에 timezone이 없다: {raw!r}")
    return value.astimezone(UTC)


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return _jsonable(value.value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if dataclasses.is_dataclass(value):
        return _jsonable(dataclasses.asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    raise TypeError(f"checkpoint JSON으로 직렬화할 수 없는 값: {type(value).__name__}")


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        _jsonable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _pretty_json_bytes(value: Any) -> bytes:
    return json.dumps(_jsonable(value), ensure_ascii=False, sort_keys=True, indent=2).encode(
        "utf-8"
    )


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _validate_cycle_date(raw: str) -> None:
    try:
        date.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"cycle_date_kst는 YYYY-MM-DD여야 한다: {raw!r}") from exc


def _validate_manifest(manifest: AcquisitionManifest) -> None:
    if manifest.schema_version != CHECKPOINT_SCHEMA_VERSION:
        raise CheckpointCorruptError(
            f"manifest schema_version={manifest.schema_version}, "
            f"expected={CHECKPOINT_SCHEMA_VERSION}"
        )
    if manifest.status not in ALL_STATUSES:
        raise CheckpointCorruptError(f"알 수 없는 manifest status: {manifest.status!r}")
    if manifest.revision < 1:
        raise CheckpointCorruptError("manifest revision은 1 이상이어야 한다")
    if manifest.completed_work_count != len(manifest.completed_work_keys):
        raise CheckpointCorruptError("completed_work_count와 completed_work_keys 길이가 다르다")
    if len(set(manifest.completed_work_keys)) != len(manifest.completed_work_keys):
        raise CheckpointCorruptError("completed_work_keys에 중복이 있다")
    if manifest.expected_work_count is not None:
        if manifest.expected_work_count < manifest.completed_work_count:
            raise CheckpointCorruptError("completed_work_count가 expected_work_count보다 크다")
    if tuple(chunk.sequence for chunk in manifest.chunks) != tuple(
        range(1, len(manifest.chunks) + 1)
    ):
        raise CheckpointCorruptError("chunk sequence가 1부터 연속적이지 않다")
    if sum(chunk.item_count for chunk in manifest.chunks) != manifest.completed_work_count:
        raise CheckpointCorruptError("chunk item_count 합과 completed_work_count가 다르다")
    _validate_cycle_date(manifest.cycle_date_kst)
    _parse_iso(manifest.created_at)
    _parse_iso(manifest.updated_at)


def _session_prefix(source_id: str, cycle_date_kst: str, session_id: str) -> str:
    return f"{CHECKPOINT_PREFIX}/{source_id}/{cycle_date_kst}/sessions/{session_id}"


def active_key(source_id: str, cycle_date_kst: str) -> str:
    return f"{CHECKPOINT_PREFIX}/{source_id}/{cycle_date_kst}/active.json"


def manifest_key(manifest: AcquisitionManifest) -> str:
    return (
        f"{_session_prefix(manifest.source_id, manifest.cycle_date_kst, manifest.session_id)}/"
        f"manifest-{manifest.revision:06d}.json"
    )


def chunk_key(manifest: AcquisitionManifest, sequence: int) -> str:
    return (
        f"{_session_prefix(manifest.source_id, manifest.cycle_date_kst, manifest.session_id)}/"
        f"chunks/{sequence:06d}.tar.gz"
    )


class CheckpointRepository:
    """Immutable checkpoint objects plus the single mutable ``active.json`` pointer."""

    def __init__(self, store: ObjectStore) -> None:
        self.store = store

    def load_active(self, source_id: str, cycle_date_kst: str) -> ActiveCheckpointRef | None:
        key = active_key(source_id, cycle_date_kst)
        if not self.store.exists(key):
            return None
        try:
            data = json.loads(self.store.get(key))
        except (json.JSONDecodeError, TypeError) as exc:
            raise CheckpointCorruptError(f"active.json을 읽을 수 없다: {key}") from exc
        ref = ActiveCheckpointRef.from_dict(data)
        if ref.source_id != source_id or ref.cycle_date_kst != cycle_date_kst:
            raise CheckpointCorruptError("active.json의 source/cycle identity가 경로와 다르다")
        return ref

    def load_manifest(self, key: str, expected_sha256: str | None = None) -> AcquisitionManifest:
        if not self.store.exists(key):
            raise CheckpointCorruptError(f"manifest가 없다: {key}")
        raw = self.store.get(key)
        actual = _sha256(raw)
        if expected_sha256 is not None and actual != expected_sha256:
            raise CheckpointCorruptError(
                f"manifest SHA256 불일치: {key} expected={expected_sha256[:12]} "
                f"actual={actual[:12]}"
            )
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise CheckpointCorruptError(f"manifest JSON이 깨졌다: {key}") from exc
        manifest = AcquisitionManifest.from_dict(data)
        if manifest_key(manifest) != key:
            raise CheckpointCorruptError("manifest 내부 identity/revision이 object key와 다르다")
        return manifest

    def load_active_manifest(
        self, source_id: str, cycle_date_kst: str
    ) -> AcquisitionManifest | None:
        ref = self.load_active(source_id, cycle_date_kst)
        if ref is None:
            return None
        manifest = self.load_manifest(ref.manifest_key, ref.manifest_sha256)
        if manifest.session_id != ref.session_id:
            raise CheckpointCorruptError("active.json session_id와 manifest session_id가 다르다")
        return manifest

    def write_manifest(self, manifest: AcquisitionManifest) -> tuple[str, str]:
        _validate_manifest(manifest)
        key = manifest_key(manifest)
        if self.store.exists(key):
            raise CheckpointError(f"immutable manifest가 이미 있다: {key}")
        raw = _pretty_json_bytes(manifest.to_dict())
        digest = _sha256(raw)
        self.store.put(key, raw)
        fetched = self.store.get(key)
        if _sha256(fetched) != digest:
            raise CheckpointCorruptError(f"manifest 업로드 검증에 실패했다: {key}")
        return key, digest

    def advance_active(self, manifest: AcquisitionManifest, manifest_sha256: str) -> None:
        key = manifest_key(manifest)
        if not self.store.exists(key):
            raise CheckpointError(f"active가 가리킬 manifest가 없다: {key}")
        ref = ActiveCheckpointRef(
            schema_version=ACTIVE_SCHEMA_VERSION,
            source_id=manifest.source_id,
            cycle_date_kst=manifest.cycle_date_kst,
            session_id=manifest.session_id,
            manifest_key=key,
            manifest_sha256=manifest_sha256,
            updated_at=manifest.updated_at,
        )
        pointer_key = active_key(manifest.source_id, manifest.cycle_date_kst)
        raw = _pretty_json_bytes(ref.to_dict())
        self.store.put(pointer_key, raw)
        loaded = self.load_active(manifest.source_id, manifest.cycle_date_kst)
        if loaded != ref:
            raise CheckpointCorruptError(f"active.json 업로드 검증에 실패했다: {pointer_key}")

    def commit_manifest(self, manifest: AcquisitionManifest, *, update_active: bool = True) -> None:
        _, digest = self.write_manifest(manifest)
        if update_active:
            self.advance_active(manifest, digest)

    def delete_active(self, source_id: str, cycle_date_kst: str) -> None:
        self.store.delete(active_key(source_id, cycle_date_kst))

    def write_chunk(
        self,
        manifest: AcquisitionManifest,
        entries: Sequence[CheckpointArtifact],
        *,
        created_at: str,
    ) -> CheckpointChunkRef:
        if not entries:
            raise ValueError("빈 checkpoint chunk는 만들지 않는다")
        sequence = len(manifest.chunks) + 1
        key = chunk_key(manifest, sequence)
        if self.store.exists(key):
            raise CheckpointError(f"immutable chunk가 이미 있다: {key}")
        raw = _encode_chunk(entries, created_at=created_at)
        digest = _sha256(raw)
        self.store.put(key, raw)
        fetched = self.store.get(key)
        if _sha256(fetched) != digest:
            raise CheckpointCorruptError(f"chunk 업로드 검증에 실패했다: {key}")
        return CheckpointChunkRef(
            sequence=sequence,
            object_key=key,
            sha256=digest,
            item_count=len(entries),
            bytes=len(raw),
            created_at=created_at,
        )

    def materialize(self, manifest: AcquisitionManifest) -> list[RawArtifactData]:
        artifacts: list[RawArtifactData] = []
        work_keys: list[str] = []
        for ref in manifest.chunks:
            if not self.store.exists(ref.object_key):
                raise CheckpointCorruptError(f"chunk가 없다: {ref.object_key}")
            raw = self.store.get(ref.object_key)
            actual = _sha256(raw)
            if actual != ref.sha256:
                raise CheckpointCorruptError(
                    f"chunk SHA256 불일치: {ref.object_key} expected={ref.sha256[:12]} "
                    f"actual={actual[:12]}"
                )
            decoded = _decode_chunk(raw)
            if len(decoded) != ref.item_count:
                raise CheckpointCorruptError(
                    f"chunk item_count 불일치: {ref.object_key} "
                    f"expected={ref.item_count} actual={len(decoded)}"
                )
            work_keys.extend(item.work_key for item in decoded)
            artifacts.extend(item.artifact for item in decoded)
        if tuple(work_keys) != manifest.completed_work_keys:
            raise CheckpointCorruptError("materialized work key 순서가 manifest와 다르다")
        return artifacts

    def latest_session_manifest(
        self, source_id: str, cycle_date_kst: str, session_id: str
    ) -> AcquisitionManifest:
        prefix = _session_prefix(source_id, cycle_date_kst, session_id) + "/manifest-"
        keys = sorted(self.store.list(prefix))
        if not keys:
            raise CheckpointCorruptError(f"session manifest가 없다: {session_id}")
        return self.load_manifest(keys[-1])

    def delete_session(self, manifest: AcquisitionManifest) -> list[str]:
        prefix = _session_prefix(
            manifest.source_id, manifest.cycle_date_kst, manifest.session_id
        ) + "/"
        removed: list[str] = []
        for key in self.store.list(prefix):
            self.store.delete(key)
            removed.append(key)
        return removed


class ResumableAcquisitionService:
    """Create/resume checkpoint sessions without knowing source-specific work semantics."""

    def __init__(
        self,
        store: ObjectStore,
        identity: AcquisitionSessionIdentity,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        _validate_cycle_date(identity.cycle_date_kst)
        if not identity.source_id:
            raise ValueError("source_id가 비어 있다")
        if not identity.request_fingerprint:
            raise ValueError("request_fingerprint가 비어 있다")
        self.identity = identity
        self.repo = CheckpointRepository(store)
        self._now = now or _utcnow

    def open(self, mode: str = "auto") -> AcquisitionManifest:
        if mode not in {"auto", "fresh"}:
            raise ValueError(f"resume mode는 auto/fresh만 가능하다: {mode!r}")
        active = self.repo.load_active_manifest(
            self.identity.source_id, self.identity.cycle_date_kst
        )
        if mode == "fresh":
            if active is not None:
                abandoned = self._next_manifest(
                    active,
                    status="abandoned",
                    terminal_reason_code="OPERATOR_FRESH",
                    terminal_reason="operator requested fresh acquisition",
                )
                self.repo.commit_manifest(abandoned)
                self.repo.delete_active(active.source_id, active.cycle_date_kst)
            return self._create_session()

        if active is None:
            return self._create_session()
        self._ensure_compatible(active)
        if active.status not in RESUMABLE_STATUSES:
            raise CheckpointIncompatibleError(
                f"active session status={active.status!r}는 auto resume 대상이 아니다; "
                "operator fresh가 필요하다"
            )
        return active

    def set_plan(
        self,
        manifest: AcquisitionManifest,
        *,
        work_plan_hash: str,
        expected_work_count: int,
    ) -> AcquisitionManifest:
        self._ensure_current(manifest)
        if expected_work_count < manifest.completed_work_count:
            raise ValueError("expected_work_count가 이미 완료한 작업 수보다 작다")
        if manifest.work_plan_hash is not None and manifest.work_plan_hash != work_plan_hash:
            raise CheckpointIncompatibleError("이미 고정된 work_plan_hash를 바꿀 수 없다")
        if (
            manifest.expected_work_count is not None
            and manifest.expected_work_count != expected_work_count
        ):
            raise CheckpointIncompatibleError("이미 고정된 expected_work_count를 바꿀 수 없다")
        updated = self._next_manifest(
            manifest,
            status="collecting",
            work_plan_hash=work_plan_hash,
            expected_work_count=expected_work_count,
            terminal_reason_code=None,
            terminal_reason=None,
        )
        self.repo.commit_manifest(updated)
        return updated

    def flush(
        self,
        manifest: AcquisitionManifest,
        entries: Sequence[CheckpointArtifact],
        *,
        guard_state: dict[str, Any] | None = None,
    ) -> AcquisitionManifest:
        self._ensure_current(manifest)
        if manifest.status not in {"collecting", "recoverable_failed"}:
            raise CheckpointError(f"status={manifest.status!r}에서는 flush할 수 없다")
        keys = [entry.work_key for entry in entries]
        if not keys:
            return manifest
        if len(keys) != len(set(keys)):
            raise CheckpointError("한 checkpoint batch 안에 work_key 중복이 있다")
        existing = set(manifest.completed_work_keys)
        duplicated = [key for key in keys if key in existing]
        if duplicated:
            raise CheckpointError(f"이미 완료된 work_key를 다시 flush하려 한다: {duplicated[:3]}")
        completed = manifest.completed_work_count + len(entries)
        if manifest.expected_work_count is not None and completed > manifest.expected_work_count:
            raise CheckpointError("flush 후 completed_work_count가 expected_work_count를 넘는다")

        now = _iso(self._now())
        ref = self.repo.write_chunk(manifest, entries, created_at=now)
        updated = self._next_manifest(
            manifest,
            status="collecting",
            completed_work_count=completed,
            completed_work_keys=(*manifest.completed_work_keys, *keys),
            chunks=(*manifest.chunks, ref),
            guard_state=guard_state,
            terminal_reason_code=None,
            terminal_reason=None,
            updated_at=now,
        )
        self.repo.commit_manifest(updated)
        return updated

    def mark_recoverable_failed(
        self,
        manifest: AcquisitionManifest,
        *,
        reason_code: str,
        reason: str,
    ) -> AcquisitionManifest:
        if (
            not reason_code.startswith("RECOVERABLE_")
            and reason_code != "CHECKPOINT_STORAGE_TRANSIENT"
        ):
            raise ValueError(f"recoverable failure code가 아니다: {reason_code!r}")
        self._ensure_current(manifest)
        updated = self._next_manifest(
            manifest,
            status="recoverable_failed",
            terminal_reason_code=reason_code,
            terminal_reason=reason,
        )
        self.repo.commit_manifest(updated)
        return updated

    def mark_complete(self, manifest: AcquisitionManifest) -> AcquisitionManifest:
        self._ensure_current(manifest)
        if (
            manifest.expected_work_count is not None
            and manifest.completed_work_count != manifest.expected_work_count
        ):
            raise CheckpointError(
                "expected work가 남아 있어 complete로 봉인할 수 없다: "
                f"{manifest.completed_work_count}/{manifest.expected_work_count}"
            )
        updated = self._next_manifest(
            manifest,
            status="complete",
            terminal_reason_code=None,
            terminal_reason=None,
        )
        self.repo.commit_manifest(updated)
        return updated

    def mark_terminal(
        self,
        manifest: AcquisitionManifest,
        *,
        status: str,
        reason_code: str,
        reason: str,
        guard_state: dict[str, Any] | None = None,
    ) -> AcquisitionManifest:
        if status not in {"guard_tripped", "blocked", "contract_failed"}:
            raise ValueError(f"terminal status가 아니다: {status!r}")
        self._ensure_current(manifest)
        updated = self._next_manifest(
            manifest,
            status=status,
            guard_state=guard_state,
            terminal_reason_code=reason_code,
            terminal_reason=reason,
        )
        self.repo.commit_manifest(updated)
        # Terminal manifest가 active에 잠깐 남아도 recovery decision은 false다.
        # 마지막으로 pointer를 지워 새 auto run이 terminal session을 주워 가지 않게 한다.
        self.repo.delete_active(updated.source_id, updated.cycle_date_kst)
        return updated

    def mark_canonical_committed(self, manifest: AcquisitionManifest) -> AcquisitionManifest:
        self._ensure_current(manifest)
        if manifest.status != "complete":
            raise CheckpointError("complete session만 canonical_committed로 바꿀 수 있다")
        updated = self._next_manifest(manifest, status="canonical_committed")
        self.repo.commit_manifest(updated)
        self.repo.delete_active(updated.source_id, updated.cycle_date_kst)
        return updated

    def materialize(self, manifest: AcquisitionManifest) -> list[RawArtifactData]:
        self._ensure_compatible(manifest)
        return self.repo.materialize(manifest)

    def _create_session(self) -> AcquisitionManifest:
        now = _iso(self._now())
        manifest = AcquisitionManifest(
            schema_version=CHECKPOINT_SCHEMA_VERSION,
            source_id=self.identity.source_id,
            session_id=uuid.uuid4().hex,
            cycle_date_kst=self.identity.cycle_date_kst,
            request_fingerprint=self.identity.request_fingerprint,
            checkpoint_contract_version=self.identity.checkpoint_contract_version,
            acquisition_contract_version=self.identity.acquisition_contract_version,
            revision=1,
            status="collecting",
            work_plan_hash=None,
            expected_work_count=None,
            completed_work_count=0,
            completed_work_keys=(),
            chunks=(),
            guard_state=None,
            terminal_reason_code=None,
            terminal_reason=None,
            created_at=now,
            updated_at=now,
        )
        self.repo.commit_manifest(manifest)
        return manifest

    def _ensure_compatible(self, manifest: AcquisitionManifest) -> None:
        expected = self.identity
        actual = (
            manifest.source_id,
            manifest.cycle_date_kst,
            manifest.request_fingerprint,
            manifest.checkpoint_contract_version,
            manifest.acquisition_contract_version,
        )
        wanted = (
            expected.source_id,
            expected.cycle_date_kst,
            expected.request_fingerprint,
            expected.checkpoint_contract_version,
            expected.acquisition_contract_version,
        )
        if actual != wanted:
            raise CheckpointIncompatibleError(
                "active checkpoint identity가 현재 acquisition contract와 다르다"
            )

    def _ensure_current(self, manifest: AcquisitionManifest) -> None:
        self._ensure_compatible(manifest)
        active = self.repo.load_active_manifest(manifest.source_id, manifest.cycle_date_kst)
        if active is None or active.session_id != manifest.session_id:
            raise CheckpointIncompatibleError("manifest가 현재 active session이 아니다")
        if active.revision != manifest.revision:
            raise CheckpointIncompatibleError(
                f"stale manifest revision: got={manifest.revision} active={active.revision}"
            )

    def _next_manifest(self, manifest: AcquisitionManifest, **changes: Any) -> AcquisitionManifest:
        changes.setdefault("revision", manifest.revision + 1)
        changes.setdefault("updated_at", _iso(self._now()))
        updated = replace(manifest, **changes)
        _validate_manifest(updated)
        return updated


def decide_recovery(
    store: ObjectStore,
    identity: AcquisitionSessionIdentity,
) -> RecoveryDecision:
    """Return a fail-closed machine-readable recovery decision."""
    repo = CheckpointRepository(store)
    try:
        manifest = repo.load_active_manifest(identity.source_id, identity.cycle_date_kst)
    except CheckpointCorruptError:
        return RecoveryDecision(
            False,
            "CHECKPOINT_CORRUPT",
            identity.source_id,
            identity.cycle_date_kst,
            None,
            None,
            0,
        )
    if manifest is None:
        return RecoveryDecision(
            False,
            "NO_VALID_CHECKPOINT",
            identity.source_id,
            identity.cycle_date_kst,
            None,
            None,
            0,
        )
    service = ResumableAcquisitionService(store, identity)
    try:
        service._ensure_compatible(manifest)
    except CheckpointIncompatibleError:
        return RecoveryDecision(
            False,
            "CHECKPOINT_INCOMPATIBLE",
            identity.source_id,
            identity.cycle_date_kst,
            manifest.session_id,
            manifest.status,
            manifest.completed_work_count,
        )

    if manifest.status == "recoverable_failed":
        reason = manifest.terminal_reason_code or "RECOVERABLE_NETWORK"
        eligible = manifest.completed_work_count > 0
        return RecoveryDecision(
            eligible,
            reason if eligible else "NO_DURABLE_PROGRESS",
            identity.source_id,
            identity.cycle_date_kst,
            manifest.session_id,
            manifest.status,
            manifest.completed_work_count,
        )
    if manifest.status == "collecting":
        eligible = manifest.completed_work_count > 0
        return RecoveryDecision(
            eligible,
            "RECOVERABLE_ABNORMAL_EXIT" if eligible else "NO_DURABLE_PROGRESS",
            identity.source_id,
            identity.cycle_date_kst,
            manifest.session_id,
            manifest.status,
            manifest.completed_work_count,
        )
    if manifest.status == "complete":
        return RecoveryDecision(
            False,
            "COMPLETE_REPLAY_UNPROVEN",
            identity.source_id,
            identity.cycle_date_kst,
            manifest.session_id,
            manifest.status,
            manifest.completed_work_count,
        )

    reason_by_status = {
        "guard_tripped": "GUARD_TRIPPED",
        "blocked": "SOURCE_BLOCKED",
        "contract_failed": "ACQUISITION_CONTRACT_CHANGED",
        "abandoned": "OPERATOR_FRESH",
        "canonical_committed": "ALREADY_COMMITTED",
    }
    return RecoveryDecision(
        False,
        reason_by_status.get(manifest.status, "UNKNOWN_FATAL"),
        identity.source_id,
        identity.cycle_date_kst,
        manifest.session_id,
        manifest.status,
        manifest.completed_work_count,
    )


def session_gc_eligible(
    manifest: AcquisitionManifest,
    *,
    active_session_id: str | None,
    now: datetime,
    incomplete_retention: timedelta = timedelta(hours=72),
    terminal_retention: timedelta = timedelta(days=7),
) -> bool:
    """Decide whether a whole historical session may be deleted.

    ``complete`` is canonical-pending and therefore protected regardless of age.
    Active sessions are always protected. This primitive intentionally does not infer
    object age from an ObjectStore API that has no metadata operation.
    """
    if manifest.session_id == active_session_id:
        return False
    if manifest.status == "complete":
        return False
    age = now.astimezone(UTC) - _parse_iso(manifest.updated_at)
    if manifest.status in {"collecting", "recoverable_failed"}:
        return age >= incomplete_retention
    return age >= terminal_retention


def _encode_chunk(entries: Sequence[CheckpointArtifact], *, created_at: str) -> bytes:
    buffer = io.BytesIO()
    index_rows: list[dict[str, Any]] = []
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for index, entry in enumerate(entries, start=1):
            if not entry.work_key:
                raise ValueError("checkpoint work_key가 비어 있다")
            body = entry.artifact.content
            item_dir = f"items/{index:06d}"
            meta = {
                "schema_version": 1,
                "work_key": entry.work_key,
                "filename": entry.artifact.filename,
                "artifact_type": entry.artifact.artifact_type,
                "encoding": "binary",
                "request_meta_json": _jsonable(entry.artifact.request_meta),
                "captured_at": entry.captured_at or created_at,
                "schema_fingerprint": entry.artifact.schema_fingerprint,
                "source_role": _jsonable(entry.artifact.source_role),
                "trust_level": _jsonable(entry.artifact.trust_level),
                "body_sha256": _sha256(body),
                "body_bytes": len(body),
                "meta_path": f"{item_dir}/meta.json",
                "body_path": f"{item_dir}/body.bin",
            }
            _tar_add_bytes(archive, meta["meta_path"], _pretty_json_bytes(meta))
            _tar_add_bytes(archive, meta["body_path"], body)
            index_rows.append(
                {
                    "work_key": entry.work_key,
                    "meta_path": meta["meta_path"],
                    "body_path": meta["body_path"],
                }
            )
        chunk_manifest = {
            "schema_version": 1,
            "created_at": created_at,
            "item_count": len(entries),
            "items": index_rows,
        }
        _tar_add_bytes(archive, "manifest.json", _pretty_json_bytes(chunk_manifest))
    return buffer.getvalue()


def _tar_add_bytes(archive: tarfile.TarFile, name: str, data: bytes) -> None:
    info = tarfile.TarInfo(name=name)
    info.size = len(data)
    info.mtime = 0
    info.mode = 0o600
    archive.addfile(info, io.BytesIO(data))


def _decode_chunk(raw: bytes) -> list[CheckpointArtifact]:
    try:
        archive = tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz")
    except tarfile.TarError as exc:
        raise CheckpointCorruptError("checkpoint chunk tar.gz를 열 수 없다") from exc
    with archive:
        manifest_member = (
            archive.getmember("manifest.json")
            if "manifest.json" in archive.getnames()
            else None
        )
        if manifest_member is None:
            raise CheckpointCorruptError("checkpoint chunk에 manifest.json이 없다")
        manifest_file = archive.extractfile(manifest_member)
        if manifest_file is None:
            raise CheckpointCorruptError("checkpoint chunk manifest를 읽을 수 없다")
        try:
            index = json.loads(manifest_file.read())
        except json.JSONDecodeError as exc:
            raise CheckpointCorruptError("checkpoint chunk manifest JSON이 깨졌다") from exc
        if index.get("schema_version") != 1 or not isinstance(index.get("items"), list):
            raise CheckpointCorruptError("checkpoint chunk manifest schema가 다르다")
        if index.get("item_count") != len(index["items"]):
            raise CheckpointCorruptError("checkpoint chunk manifest item_count가 다르다")

        decoded: list[CheckpointArtifact] = []
        for row in index["items"]:
            if not isinstance(row, dict):
                raise CheckpointCorruptError("checkpoint chunk item index 형식이 잘못됐다")
            meta_path = row.get("meta_path")
            body_path = row.get("body_path")
            if not isinstance(meta_path, str) or not isinstance(body_path, str):
                raise CheckpointCorruptError("checkpoint chunk item path가 잘못됐다")
            meta_file = archive.extractfile(meta_path)
            body_file = archive.extractfile(body_path)
            if meta_file is None or body_file is None:
                raise CheckpointCorruptError("checkpoint chunk item 파일이 없다")
            try:
                meta = json.loads(meta_file.read())
            except json.JSONDecodeError as exc:
                raise CheckpointCorruptError("checkpoint item meta JSON이 깨졌다") from exc
            body = body_file.read()
            if _sha256(body) != meta.get("body_sha256"):
                raise CheckpointCorruptError("checkpoint item body SHA256이 다르다")
            if len(body) != meta.get("body_bytes"):
                raise CheckpointCorruptError("checkpoint item body byte 수가 다르다")
            work_key = str(meta.get("work_key") or "")
            if work_key != row.get("work_key") or not work_key:
                raise CheckpointCorruptError("checkpoint item work_key가 index와 다르다")
            try:
                artifact = RawArtifactData(
                    artifact_type=str(meta["artifact_type"]),
                    content=body,
                    filename=str(meta["filename"]),
                    request_meta=dict(meta["request_meta_json"]),
                    schema_fingerprint=str(meta["schema_fingerprint"]),
                    source_role=str(meta["source_role"]),
                    trust_level=str(meta["trust_level"]),
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise CheckpointCorruptError("checkpoint item artifact metadata가 잘못됐다") from exc
            decoded.append(
                CheckpointArtifact(
                    work_key=work_key,
                    artifact=artifact,
                    captured_at=str(meta.get("captured_at") or ""),
                )
            )
        return decoded
