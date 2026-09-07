from pathlib import Path


def test_bootstrap_operational_note_marks_trigger_temporary() -> None:
    note = Path("docs/ops/README-size-peer-bootstrap-note.md").read_text(encoding="utf-8")
    assert "Temporary operational note" in note
    assert "Remove that trigger" in note
