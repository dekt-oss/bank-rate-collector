"""NH checkpoint context CLI contract."""

import json

from rate_monitor import checkpoint_cli
from rate_monitor.checkpoint_cli import main


def test_prepare_context_with_explicit_cycle_is_machine_readable(capsys) -> None:
    code = main(
        [
            "prepare-context",
            "--source",
            "nh_local",
            "--scope",
            "부산",
            "--cycle-date",
            "2026-08-11",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["source_id"] == "nh_local"
    assert payload["cycle_date_kst"] == "2026-08-11"
    assert len(payload["request_fingerprint"]) == 64
    assert payload["acquisition_contract_version"] == 1


def test_prepare_context_without_cycle_uses_exact_workflow_run_start(monkeypatch, capsys) -> None:
    calls = 0

    def fake_resolve() -> str:
        nonlocal calls
        calls += 1
        return "2026-08-12"

    monkeypatch.setattr(checkpoint_cli, "resolve_cycle_date_kst", fake_resolve)
    assert main(["prepare-context", "--source", "nh_local", "--scope", "전국"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert calls == 1
    assert payload["cycle_date_kst"] == "2026-08-12"


def test_prepare_context_can_persist_the_same_json(tmp_path, capsys) -> None:
    out = tmp_path / "context.json"
    assert (
        main(
            [
                "prepare-context",
                "--source",
                "nh_local",
                "--cycle-date",
                "2026-08-11",
                "--json",
                str(out),
            ]
        )
        == 0
    )
    stdout_payload = json.loads(capsys.readouterr().out)
    file_payload = json.loads(out.read_text(encoding="utf-8"))
    assert stdout_payload == file_payload
