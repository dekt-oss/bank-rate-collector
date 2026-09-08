from pathlib import Path

COLLECT = Path(".github/workflows/collect.yml")


def test_main_push_does_not_enter_canonical_collection_writer() -> None:
    text = COLLECT.read_text(encoding="utf-8")
    trigger_block = text.split("concurrency:", 1)[0]
    assert "\n  push:\n" not in trigger_block
    assert "github.event_name == 'push'" not in text


def test_publication_gates_run_before_authoritative_r2_upload() -> None:
    text = COLLECT.read_text(encoding="utf-8")
    stage = text.index("      - name: Stage rate-data payload")
    size_gate = text.index("      - name: Size gate")
    volume_gate = text.index("      - name: Volume gate")
    r2_upload = text.index("      - name: Upload state to R2")
    rate_data_publish = text.index("      - name: Publish to rate-data branch")

    assert stage < size_gate < volume_gate < r2_upload < rate_data_publish


def test_r2_upload_remains_after_validation_and_p1a_gate() -> None:
    text = COLLECT.read_text(encoding="utf-8")
    assert text.index("      - name: Validate stored data") < text.index(
        "      - name: Upload state to R2"
    )
    assert text.index("      - name: Verify P1-A gate") < text.index(
        "      - name: Upload state to R2"
    )
