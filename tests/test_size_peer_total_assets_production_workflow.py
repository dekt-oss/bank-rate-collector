from pathlib import Path


WORKFLOW = Path(".github/workflows/collect-size-peer-total-assets.yml")


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_total_assets_writer_uses_existing_serialized_rate_data_writer_lane() -> None:
    text = _text()
    assert "group: rate-data-writer" in text
    assert "cancel-in-progress: false" in text
    assert "storage restore --dest work/rate_monitor.sqlite3" in text
    assert "storage upload --db publish/rate_monitor.sqlite3" in text
    assert "cmp -s publish/rate_monitor.sqlite3 work/size-peer-assets-from-r2.sqlite3" in text


def test_total_assets_writer_keeps_financial_vintage_explicit_and_common() -> None:
    text = _text()
    assert 'VALIDATED_COMMON_BAS_YM: "202512"' in text
    assert '--bas-ym "$TOTAL_ASSETS_BAS_YM"' in text
    assert "exact common financial month=$BAS_YM" in text
    assert "source_effective_month=?" in text


def test_total_assets_writer_seals_funding_and_requires_pair_complete_anchor() -> None:
    text = _text()
    assert "Seal existing funding rows" in text
    assert "funding-before-assets.json" in text
    assert "funding_sha256_unchanged" in text
    assert "pair_complete_mapped" in text
    assert "source_institution_key='0010390'" in text
    assert '"deposit_liabilities_total", "total_assets"' in text


def test_pull_request_gate_cannot_publish_authoritative_state() -> None:
    text = _text()
    guard = "if: ${{ github.event_name != 'pull_request' }}"
    assert "pull_request:" in text
    assert text.count(guard) >= 3

    upload_pos = text.index("- name: Upload authoritative state to R2")
    upload_tail = text[upload_pos:]
    assert guard in upload_tail.split("run:", 1)[0]


def test_total_assets_rerun_is_required_to_be_idempotent_before_snapshot() -> None:
    text = _text()
    rerun_pos = text.index("- name: Idempotent total-assets rerun")
    snapshot_pos = text.index("- name: Snapshot and validate")
    assert rerun_pos < snapshot_pos
    assert 'assert result["stored"] == 0' in text
    assert 'assert result["revisions"] == 0' in text
    assert 'assert result["unchanged"] == result["institution_rows"]' in text
