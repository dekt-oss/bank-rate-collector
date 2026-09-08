from __future__ import annotations

import ast
import re
from pathlib import Path

WORKFLOW = Path(".github/workflows/recover-size-peer-production-financial-axis.yml")


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _python_heredocs(text: str) -> list[str]:
    return re.findall(r"uv run python - <<'PY'\n(.*?)\n\s*PY", text, flags=re.DOTALL)


def test_recovery_is_single_serialized_authoritative_writer() -> None:
    text = _text()
    assert "group: rate-data-writer" in text
    assert "cancel-in-progress: false" in text
    assert "Restore authoritative R2 once" in text
    assert text.count("storage upload --db publish/rate_monitor.sqlite3") == 1
    assert "cmp -s publish/rate_monitor.sqlite3 work/size-peer-recovery-from-r2.sqlite3" in text


def test_pull_request_path_cannot_run_production_recovery() -> None:
    text = _text()
    assert "pull_request:" in text
    assert "if: ${{ github.event_name != 'pull_request' }}" in text
    assert "Recovery workflow contract tests" in text


def test_stale_main_is_rejected_before_restore_and_acquisition() -> None:
    text = _text()
    guard = text.index("Reject stale main before expensive acquisition")
    restore = text.index("Restore authoritative R2 once")
    collect = text.index("Recover savings-bank and NH-local total assets")
    assert guard < restore < collect
    assert "ensure_current_main_writer" in text


def test_recovery_restores_both_required_axes_without_touching_funding() -> None:
    text = _text()
    assert 'VALIDATED_COMMON_BAS_YM: "202512"' in text
    assert "funding-before-recovery.json" in text
    assert "collect-total-assets" in text
    assert "recovery-sa-nh-qc.json" in text
    assert "funding_sha256_unchanged" in text
    assert "source_institution_key='0010390'" in text


def test_recovery_uses_official_cu_same_disclosure_pair_and_idempotent_persistence() -> None:
    text = _text()
    assert "collect_cu_size_pair_evidence" in text
    assert "persist_cu_total_assets_pairs" in text
    assert "recovery-cu-evidence.json" in text
    assert "recovery-cu-persistence.json" in text
    assert 'assert second.stored == 0' in text
    assert 'assert second.revisions == 0' in text
    assert 'assert second.unchanged == len(pairs)' in text
    for field in (
        "institution_name",
        "disclosure_type",
        "deposit_source_text",
        "total_assets_source_text",
        "source_locator",
    ):
        assert field in text


def test_recovery_requires_positive_cross_sector_total_assets_and_exact_pairs() -> None:
    text = _text()
    assert '"savings_bank": "data_go_savings_bank_funding"' in text
    assert '"nh_local": "data_go_agri_coop_funding"' in text
    assert '"cu": "cu_disclosure_funding"' in text
    assert "total_assets_by_sector" in text
    assert "exact_pairs_by_sector" in text
    assert "assert all(total_assets_by_sector[sector] > 0" in text
    assert "assert all(pair_by_sector[sector] > 0" in text


def test_all_embedded_python_blocks_parse() -> None:
    blocks = _python_heredocs(_text())
    assert blocks
    for block in blocks:
        # YAML block indentation is preserved uniformly; dedent before parsing.
        lines = block.splitlines()
        non_empty = [line for line in lines if line.strip()]
        indent = min(len(line) - len(line.lstrip()) for line in non_empty)
        source = "\n".join(line[indent:] for line in lines)
        ast.parse(source)
