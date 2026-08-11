"""공통 resumable acquisition checkpoint 계약 — 외부 R2 없이 검증한다."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from rate_monitor.domain.schemas import RawArtifactData
from rate_monitor.services.resumable_acquisition import (
    AcquisitionManifest,
    AcquisitionSessionIdentity,
    CheckpointArtifact,
    CheckpointChunkRef,
    CheckpointCorruptError,
    CheckpointIncompatibleError,
    CheckpointRepository,
    ResumableAcquisitionService,
    canonical_fingerprint,
    decide_recovery,
    session_gc_eligible,
)
from rate_monitor.services.storage_service import LocalObjectStore

NOW = datetime(2026, 8, 11, 5, 0, tzinfo=UTC)


def _identity(
    *,
    source_id: str = "nh_local",
    cycle: str = "2026-08-11",
    fingerprint: str | None = None,
) -> AcquisitionSessionIdentity:
    return AcquisitionSessionIdentity(
        source_id=source_id,
        cycle_date_kst=cycle,
        request_fingerprint=fingerprint or canonical_fingerprint({"scope": "전국"}),
        acquisition_contract_version=1,
    )


def _artifact(n: int) -> CheckpointArtifact:
    return CheckpointArtifact(
        work_key=f"work:{n}",
        artifact=RawArtifactData(
            artifact_type="html",
            content=f"<html>{n}</html>".encode(),
            filename=f"rate_{n}.html",
            request_meta={"n": n, "nested": {"region": "부산"}},
            schema_fingerprint=f"schema-{n}",
            source_role="primary_official",
            trust_level="official_direct",
        ),
    )


def _service(tmp_path, identity=None, *, now=NOW):
    store = LocalObjectStore(tmp_path / "objects")
    return store, ResumableAcquisitionService(
        store,
        identity or _identity(),
        now=lambda: now,
    )


def test_new_session_creates_manifest_then_active_pointer(tmp_path) -> None:
    store, service = _service(tmp_path)
    manifest = service.open()

    assert manifest.revision == 1
    assert manifest.status == "collecting"
    assert manifest.completed_work_count == 0

    repo = CheckpointRepository(store)
    active_ref = repo.load_active("nh_local", "2026-08-11")
    active = repo.load_active_manifest("nh_local", "2026-08-11")
    assert active == manifest
    assert active_ref is not None
    assert active_ref.manifest_sha256[:16] in active_ref.manifest_key


def test_flush_round_trips_raw_artifacts_and_work_order(tmp_path) -> None:
    _, service = _service(tmp_path)
    manifest = service.open()
    manifest = service.set_plan(
        manifest,
        work_plan_hash=canonical_fingerprint(["work:1", "work:2"]),
        expected_work_count=2,
    )
    manifest = service.flush(manifest, [_artifact(1), _artifact(2)])
    manifest = service.mark_complete(manifest)

    artifacts = service.materialize(manifest)
    assert [a.filename for a in artifacts] == ["rate_1.html", "rate_2.html"]
    assert [a.content for a in artifacts] == [b"<html>1</html>", b"<html>2</html>"]
    assert artifacts[0].request_meta == {"n": 1, "nested": {"region": "부산"}}
    assert manifest.completed_work_keys == ("work:1", "work:2")
    assert manifest.completed_work_count == 2
    assert manifest.chunks[0].sha256[:16] in manifest.chunks[0].object_key


def test_identical_immutable_manifest_write_is_idempotent(tmp_path) -> None:
    store, service = _service(tmp_path)
    manifest = service.open()
    repo = CheckpointRepository(store)

    first_key, first_hash = repo.write_manifest(manifest)
    second_key, second_hash = repo.write_manifest(manifest)

    assert (first_key, first_hash) == (second_key, second_hash)
    assert store.get(first_key) == store.get(second_key)


def test_crash_before_active_pointer_update_leaves_a_resumable_previous_revision(tmp_path) -> None:
    """Orphan chunk/manifest must not block the next flush after a crash window."""
    store, service = _service(tmp_path)
    first = service.open()
    repo = CheckpointRepository(store)

    orphan_chunk = repo.write_chunk(first, [_artifact(1)], created_at="2026-08-11T05:01:00Z")
    orphan_manifest = replace(
        first,
        revision=2,
        completed_work_count=1,
        completed_work_keys=("work:1",),
        chunks=(orphan_chunk,),
        updated_at="2026-08-11T05:01:00Z",
    )
    repo.commit_manifest(orphan_manifest, update_active=False)

    # Commit point(active.json)이 안 움직였으므로 durable truth는 여전히 first다.
    assert repo.load_active_manifest("nh_local", "2026-08-11") == first
    assert repo.materialize(first) == []
    assert repo.materialize(orphan_manifest)[0].filename == "rate_1.html"

    # 새 process는 first에서 재개하고 같은 logical item을 다시 받아도 된다.
    # Content-addressed object key 때문에 orphan sequence=1과 충돌하지 않는다.
    resumed = ResumableAcquisitionService(store, _identity(), now=lambda: NOW)
    active = resumed.open("auto")
    committed = resumed.flush(active, [_artifact(1)])
    assert committed.completed_work_keys == ("work:1",)
    assert committed.chunks[0].object_key != orphan_chunk.object_key or (
        committed.chunks[0].sha256 == orphan_chunk.sha256
    )
    assert repo.load_active_manifest("nh_local", "2026-08-11") == committed


def test_corrupt_chunk_fails_closed(tmp_path) -> None:
    store, service = _service(tmp_path)
    manifest = service.open()
    manifest = service.flush(manifest, [_artifact(1)])
    chunk = manifest.chunks[0]

    store.put(chunk.object_key, b"not-a-tar-gz")

    with pytest.raises(CheckpointCorruptError, match="SHA256"):
        service.materialize(manifest)


def test_corrupt_manifest_hash_fails_closed(tmp_path) -> None:
    store, service = _service(tmp_path)
    service.open()
    repo = CheckpointRepository(store)
    active = repo.load_active("nh_local", "2026-08-11")
    assert active is not None

    store.put(active.manifest_key, b"{}")

    with pytest.raises(CheckpointCorruptError, match="SHA256"):
        repo.load_active_manifest("nh_local", "2026-08-11")


def test_incompatible_fingerprint_never_silently_starts_fresh(tmp_path) -> None:
    store, service = _service(tmp_path)
    original = service.open()
    incompatible = ResumableAcquisitionService(
        store,
        _identity(fingerprint=canonical_fingerprint({"scope": "부산"})),
        now=lambda: NOW,
    )

    with pytest.raises(CheckpointIncompatibleError, match="identity"):
        incompatible.open("auto")

    active = CheckpointRepository(store).load_active_manifest("nh_local", "2026-08-11")
    assert active == original


def test_next_kst_cycle_does_not_auto_resume_yesterday(tmp_path) -> None:
    store, service = _service(tmp_path)
    yesterday = service.open()
    today_service = ResumableAcquisitionService(
        store,
        _identity(cycle="2026-08-12"),
        now=lambda: NOW + timedelta(days=1),
    )

    today = today_service.open("auto")

    assert today.session_id != yesterday.session_id
    assert today.cycle_date_kst == "2026-08-12"


def test_fresh_abandons_old_session_and_repoints_active(tmp_path) -> None:
    store, service = _service(tmp_path)
    old = service.open()

    fresh = service.open("fresh")

    repo = CheckpointRepository(store)
    old_latest = repo.latest_session_manifest("nh_local", "2026-08-11", old.session_id)
    active = repo.load_active_manifest("nh_local", "2026-08-11")
    assert old_latest.status == "abandoned"
    assert old_latest.terminal_reason_code == "OPERATOR_FRESH"
    assert fresh.session_id != old.session_id
    assert active == fresh


def test_recovery_decision_is_true_only_with_durable_recoverable_progress(tmp_path) -> None:
    store, service = _service(tmp_path)
    manifest = service.open()

    empty = decide_recovery(store, _identity())
    assert empty.eligible is False
    assert empty.reason_code == "NO_DURABLE_PROGRESS"

    manifest = service.flush(manifest, [_artifact(1)])
    live_looking = decide_recovery(store, _identity())
    assert live_looking.eligible is False
    assert live_looking.reason_code == "CALLER_FAILURE_NOT_CONFIRMED"

    collecting = decide_recovery(store, _identity(), attempt_failed=True)
    assert collecting.eligible is True
    assert collecting.reason_code == "RECOVERABLE_ABNORMAL_EXIT"

    service.mark_recoverable_failed(
        manifest,
        reason_code="RECOVERABLE_NETWORK",
        reason="connection failed after retries",
    )
    failed = decide_recovery(store, _identity())
    assert failed.eligible is True
    assert failed.reason_code == "RECOVERABLE_NETWORK"
    assert failed.completed_work_count == 1


def test_recovery_decision_fails_closed_for_corrupt_and_incompatible_state(tmp_path) -> None:
    store, service = _service(tmp_path)
    service.open()
    repo = CheckpointRepository(store)
    active = repo.load_active("nh_local", "2026-08-11")
    assert active is not None

    incompatible = decide_recovery(
        store,
        _identity(fingerprint=canonical_fingerprint({"scope": "부산"})),
    )
    assert incompatible.eligible is False
    assert incompatible.reason_code == "CHECKPOINT_INCOMPATIBLE"

    store.put(active.manifest_key, b"corrupt")
    corrupt = decide_recovery(store, _identity())
    assert corrupt.eligible is False
    assert corrupt.reason_code == "CHECKPOINT_CORRUPT"


def test_guard_terminal_is_not_resumable(tmp_path) -> None:
    store, service = _service(tmp_path)
    manifest = service.open()
    manifest = service.flush(manifest, [_artifact(1)])
    terminal = service.mark_terminal(
        manifest,
        status="guard_tripped",
        reason_code="GUARD_TRIPPED",
        reason="same response repeated",
        guard_state={"longest_run": 41},
    )

    assert terminal.status == "guard_tripped"
    assert terminal.guard_state == {"longest_run": 41}
    decision = decide_recovery(store, _identity())
    assert decision.eligible is False
    assert decision.reason_code == "GUARD_TRIPPED"

    with pytest.raises(CheckpointIncompatibleError, match="operator fresh"):
        service.open("auto")


def test_complete_is_canonical_pending_and_replay_is_not_auto_approved(tmp_path) -> None:
    store, service = _service(tmp_path)
    manifest = service.open()
    manifest = service.flush(manifest, [_artifact(1)])
    service.mark_complete(manifest)

    decision = decide_recovery(store, _identity())
    assert decision.eligible is False
    assert decision.reason_code == "COMPLETE_REPLAY_UNPROVEN"


def test_gc_protects_active_and_complete_but_expires_abandoned(tmp_path) -> None:
    _, service = _service(tmp_path)
    manifest = service.open()
    old_time = NOW - timedelta(days=10)
    old_stamp = old_time.isoformat().replace("+00:00", "Z")

    stale_collecting = replace(manifest, updated_at=old_stamp)
    assert not session_gc_eligible(
        stale_collecting,
        active_session_id=manifest.session_id,
        now=NOW,
    )

    complete = replace(stale_collecting, status="complete")
    assert not session_gc_eligible(complete, active_session_id=None, now=NOW)

    abandoned = replace(stale_collecting, status="abandoned")
    assert session_gc_eligible(abandoned, active_session_id=None, now=NOW)


def test_gc_requires_timezone_aware_now(tmp_path) -> None:
    _, service = _service(tmp_path)
    manifest = service.open()
    with pytest.raises(ValueError, match="timezone"):
        session_gc_eligible(
            manifest,
            active_session_id=None,
            now=datetime(2026, 8, 20),
        )


def test_nh_manifest_serialization_growth_is_bounded_for_v1() -> None:
    """9,742 NH-like work keys remain bounded under 200-item flush policy."""
    import json
    import math

    keys = [f"nh:{index:04d}:SFDPW0163R" for index in range(9742)]
    chunks: list[CheckpointChunkRef] = []
    cumulative_bytes = 0
    final_bytes = 0
    template = AcquisitionManifest(
        schema_version=1,
        source_id="nh_local",
        session_id="a" * 32,
        cycle_date_kst="2026-08-11",
        request_fingerprint="b" * 64,
        checkpoint_contract_version=1,
        acquisition_contract_version=1,
        revision=1,
        status="collecting",
        work_plan_hash="c" * 64,
        expected_work_count=9742,
        completed_work_count=0,
        completed_work_keys=(),
        chunks=(),
        guard_state=None,
        terminal_reason_code=None,
        terminal_reason=None,
        created_at="2026-08-11T00:00:00Z",
        updated_at="2026-08-11T00:00:00Z",
    )
    previous = 0
    for completed in range(200, 9943, 200):
        actual = min(completed, 9742)
        sequence = len(chunks) + 1
        chunks.append(
            CheckpointChunkRef(
                sequence=sequence,
                object_key=(
                    "checkpoints/v1/nh_local/2026-08-11/sessions/"
                    + "a" * 32
                    + f"/chunks/{sequence:06d}-"
                    + "d" * 16
                    + ".tar.gz"
                ),
                sha256="d" * 64,
                item_count=actual - previous,
                bytes=123456,
                created_at="2026-08-11T00:00:00Z",
            )
        )
        manifest = replace(
            template,
            revision=sequence + 1,
            completed_work_count=actual,
            completed_work_keys=tuple(keys[:actual]),
            chunks=tuple(chunks),
        )
        size = len(
            json.dumps(
                manifest.to_dict(), ensure_ascii=False, sort_keys=True, indent=2
            ).encode("utf-8")
        )
        cumulative_bytes += size
        final_bytes = size
        previous = actual
        if actual == 9742:
            break

    assert len(chunks) == math.ceil(9742 / 200)
    assert final_bytes < 512 * 1024
    assert cumulative_bytes < 10 * 1024 * 1024


def test_canonical_fingerprint_is_mapping_order_independent() -> None:
    left = canonical_fingerprint({"scope": "전국", "groups": ["13", "14"]})
    right = canonical_fingerprint({"groups": ["13", "14"], "scope": "전국"})
    assert left == right
