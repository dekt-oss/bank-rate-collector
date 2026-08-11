"""checkpoint recovery-decision CLI는 자연어가 아니라 JSON 계약을 낸다."""

import json
from datetime import UTC, datetime

from rate_monitor.checkpoint_cli import main
from rate_monitor.domain.schemas import RawArtifactData
from rate_monitor.services.resumable_acquisition import (
    AcquisitionSessionIdentity,
    CheckpointArtifact,
    ResumableAcquisitionService,
    canonical_fingerprint,
)
from rate_monitor.services.storage_service import LocalObjectStore

NOW = datetime(2026, 8, 11, 5, 0, tzinfo=UTC)


def test_recovery_decision_cli_writes_machine_readable_json(tmp_path, capsys) -> None:
    root = tmp_path / "objects"
    store = LocalObjectStore(root)
    fingerprint = canonical_fingerprint({"scope": "전국"})
    identity = AcquisitionSessionIdentity(
        source_id="nh_local",
        cycle_date_kst="2026-08-11",
        request_fingerprint=fingerprint,
    )
    service = ResumableAcquisitionService(store, identity, now=lambda: NOW)
    manifest = service.open()
    manifest = service.flush(
        manifest,
        [
            CheckpointArtifact(
                work_key="nh:1:screen",
                artifact=RawArtifactData(
                    artifact_type="html",
                    content=b"ok",
                    filename="one.html",
                    request_meta={"n": 1},
                    schema_fingerprint="fp",
                    source_role="primary_official",
                    trust_level="official_direct",
                ),
            )
        ],
    )
    service.mark_recoverable_failed(
        manifest,
        reason_code="RECOVERABLE_NETWORK",
        reason="test",
    )

    out = tmp_path / "decision.json"
    code = main(
        [
            "recovery-decision",
            "--source",
            "nh_local",
            "--cycle-date",
            "2026-08-11",
            "--request-fingerprint",
            fingerprint,
            "--local-root",
            str(root),
            "--json",
            str(out),
        ]
    )

    assert code == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["eligible"] is True
    assert payload["reason_code"] == "RECOVERABLE_NETWORK"
    assert payload["completed_work_count"] == 1
    assert json.loads(capsys.readouterr().out) == payload


def test_recovery_decision_cli_fails_when_r2_configuration_is_missing(monkeypatch, capsys) -> None:
    for key in (
        "R2_ACCOUNT_ID",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
        "R2_BUCKET",
        "R2_ENDPOINT",
        "R2_REGION",
    ):
        monkeypatch.delenv(key, raising=False)

    code = main(
        [
            "recovery-decision",
            "--source",
            "kfcc",
            "--cycle-date",
            "2026-08-11",
            "--request-fingerprint",
            "abc",
        ]
    )

    assert code == 1
    assert "R2 시크릿이 없다" in capsys.readouterr().err
