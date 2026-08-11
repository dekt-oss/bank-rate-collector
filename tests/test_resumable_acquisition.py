"""공통 resumable acquisition checkpoint 계약 — 외부 R2 없이 검증한다."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from rate_monitor.domain.schemas import RawArtifactData
from rate_monitor.services.resumable_acquisition import (
    AcquisitionSessionIdentity,
    CheckpointArtifact,
    CheckpointCorruptError,
    CheckpointError,
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

    active = CheckpointRepository(store).load_active_manifest("nh_local", "2026-08-11")
    assert active == manifest


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


def test_immutable_manifest_revision_rejects_overwrite(tmp_path) -> None:
    store, service = _service(tmp_path)
    manifest = service.open()
    repo = CheckpointRepository(store)

    with pytest.raises(CheckpointError, match="immutable manifest"):
        repo.write_manifest(manifest)


def test_crash_before_active_pointer_update_keeps_previous_revision_valid(tmp_path) -> None:
    store, service = _service(tmp_path)
    first = service.open()
    repo = CheckpointRepository(store)

    chunk = repo.write_chunk(first, [_artifact(1)], created_at="2026-08-11T05:01:00Z")
    second = replace(
        first,
        revision=2,
        completed_work_count=1,
        completed_work_keys=("work:1",),
        chunks=(chunk,),
        updated_at="2026-08-11T05:01:00Z",
    )
    repo.commit_manifest(second, update_active=False)

    assert repo.load_active_manifest("nh_local", "2026-08-11") == first
    assert repo.materialize(first) == []
    assert repo.materialize(second)[0].filename == "rate_1.html"


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

    assert decide_recovery(store, _identity()).eligible is False

    manifest = service.flush(manifest, [_artifact(1)])
    collecting = decide_recovery(store, _identity())
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


def test_canonical_fingerprint_is_mapping_order_independent() -> None:
    left = canonical_fingerprint({"scope": "전국", "groups": ["13", "14"]})
    right = canonical_fingerprint({"groups": ["13", "14"], "scope": "전국"})
    assert left == right
