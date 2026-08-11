"""KFCC checkpoint context CLI contract."""

import json

from rate_monitor import checkpoint_cli
from rate_monitor.checkpoint_cli import main


def test_prepare_kfcc_context_with_explicit_cycle_is_machine_readable(capsys) -> None:
    code = main(
        [
            "prepare-context",
            "--source",
            "kfcc",
            "--scope",
            "부산",
            "--cycle-date",
            "2026-08-11",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["source_id"] == "kfcc"
    assert payload["cycle_date_kst"] == "2026-08-11"
    assert len(payload["request_fingerprint"]) == 64
    assert payload["acquisition_contract_version"] == 1


def test_prepare_kfcc_context_without_cycle_uses_workflow_run_start(
    monkeypatch, capsys
) -> None:
    monkeypatch.setattr(checkpoint_cli, "resolve_cycle_date_kst", lambda: "2026-08-12")
    assert main(["prepare-context", "--source", "kfcc", "--scope", "전국"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["cycle_date_kst"] == "2026-08-12"


def test_prepare_kfcc_context_accepts_explicit_regions(capsys) -> None:
    assert (
        main(
            [
                "prepare-context",
                "--source",
                "kfcc",
                "--regions",
                "부산",
                "경남",
                "--cycle-date",
                "2026-08-11",
            ]
        )
        == 0
    )
    explicit = json.loads(capsys.readouterr().out)

    assert (
        main(
            [
                "prepare-context",
                "--source",
                "kfcc",
                "--scope",
                "부산",
                "--cycle-date",
                "2026-08-11",
            ]
        )
        == 0
    )
    busan = json.loads(capsys.readouterr().out)
    assert explicit["request_fingerprint"] != busan["request_fingerprint"]


def test_nh_prepare_context_still_rejects_regions(capsys) -> None:
    assert (
        main(
            [
                "prepare-context",
                "--source",
                "nh_local",
                "--regions",
                "부산",
                "--cycle-date",
                "2026-08-11",
            ]
        )
        == 1
    )
    assert "--regions" in capsys.readouterr().err
