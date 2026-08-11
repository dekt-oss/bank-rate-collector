"""Terminal checkpoint 사유는 active 제거 뒤에도 감사/복구 판정에 남는다."""

from datetime import UTC, datetime

import pytest

from rate_monitor.services.resumable_acquisition import (
    AcquisitionSessionIdentity,
    CheckpointRepository,
    ResumableAcquisitionService,
    canonical_fingerprint,
    decide_recovery,
)
from rate_monitor.services.storage_service import LocalObjectStore

NOW = datetime(2026, 8, 11, 5, 0, tzinfo=UTC)


def _identity() -> AcquisitionSessionIdentity:
    return AcquisitionSessionIdentity(
        source_id="nh_local",
        cycle_date_kst="2026-08-11",
        request_fingerprint=canonical_fingerprint({"scope": "전국"}),
    )


def _service(tmp_path):
    store = LocalObjectStore(tmp_path / "objects")
    service = ResumableAcquisitionService(store, _identity(), now=lambda: NOW)
    return store, service


@pytest.mark.parametrize(
    ("status", "reason_code", "decision_code"),
    [
        ("guard_tripped", "GUARD_TRIPPED", "GUARD_TRIPPED"),
        ("blocked", "SOURCE_BLOCKED", "SOURCE_BLOCKED"),
        (
            "contract_failed",
            "ACQUISITION_CONTRACT_CHANGED",
            "ACQUISITION_CONTRACT_CHANGED",
        ),
    ],
)
def test_terminal_seal_remains_machine_readable_after_active_is_removed(
    tmp_path, status: str, reason_code: str, decision_code: str
) -> None:
    store, service = _service(tmp_path)
    manifest = service.open()
    terminal = service.mark_terminal(
        manifest,
        status=status,
        reason_code=reason_code,
        reason="review regression",
    )

    repo = CheckpointRepository(store)
    assert repo.load_active_manifest("nh_local", "2026-08-11") is None
    assert repo.load_sealed_manifest("nh_local", "2026-08-11") == terminal

    decision = decide_recovery(store, _identity())
    assert decision.eligible is False
    assert decision.reason_code == decision_code
    assert decision.manifest_status == status


def test_canonical_commit_seal_is_reported_as_already_committed(tmp_path) -> None:
    store, service = _service(tmp_path)
    complete = service.mark_complete(service.open())
    committed = service.mark_canonical_committed(complete)

    repo = CheckpointRepository(store)
    assert repo.load_active_manifest("nh_local", "2026-08-11") is None
    assert repo.load_sealed_manifest("nh_local", "2026-08-11") == committed

    decision = decide_recovery(store, _identity())
    assert decision.eligible is False
    assert decision.reason_code == "ALREADY_COMMITTED"


def test_fresh_preserves_abandoned_audit_while_new_active_takes_precedence(tmp_path) -> None:
    store, service = _service(tmp_path)
    old = service.open()
    fresh = service.open("fresh")

    repo = CheckpointRepository(store)
    sealed = repo.load_sealed_manifest("nh_local", "2026-08-11")
    active = repo.load_active_manifest("nh_local", "2026-08-11")

    assert sealed is not None
    assert sealed.session_id == old.session_id
    assert sealed.status == "abandoned"
    assert sealed.terminal_reason_code == "OPERATOR_FRESH"
    assert active == fresh

    # Recovery 판정은 superseded audit보다 현재 active session을 우선한다.
    decision = decide_recovery(store, _identity())
    assert decision.eligible is False
    assert decision.reason_code == "NO_DURABLE_PROGRESS"
    assert decision.session_id == fresh.session_id

def test_contract_failed_preserves_specific_terminal_reason_code(tmp_path) -> None:
    store, service = _service(tmp_path)
    manifest = service.open()
    service.mark_terminal(
        manifest,
        status="contract_failed",
        reason_code="SOURCE_SCHEMA_CHANGED",
        reason="directory schema changed",
    )

    decision = decide_recovery(store, _identity())
    assert decision.eligible is False
    assert decision.reason_code == "SOURCE_SCHEMA_CHANGED"
    assert decision.manifest_status == "contract_failed"

