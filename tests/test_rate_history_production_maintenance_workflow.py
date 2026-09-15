from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "rate-history-production-maintenance.yml"


def test_canonical_maintenance_is_manual_and_fail_closed() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "workflow_dispatch:" in text
    assert "expected_main_sha:" in text
    assert "expected_current_object_key:" in text
    assert "confirmation:" in text
    assert "push:" not in text
    assert "group: rate-data-writer" in text
    assert 'test "$CONFIRMATION" = "COMPACT_CANONICAL_R2"' in text
    assert 'test "$GITHUB_SHA" = "$EXPECTED_MAIN_SHA"' in text
    assert "git ls-remote origin refs/heads/main" in text
    assert "expected current object mismatch" in text


def test_canonical_maintenance_preserves_and_can_restore_rollback_pointer() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "r2-current-before.json" in text
    assert "ROLLBACK_PREFIX" in text
    assert "store.put(rollback_key" in text
    assert "Rollback current pointer after a failed post-upload check" in text
    assert "store.put(CURRENT_KEY, before.to_json()" in text
    assert "prune_snapshots" not in text
    assert "store.delete(" not in text
    assert "--preserve-snapshot \"$EXPECTED_CURRENT_OBJECT_KEY\"" in text


def test_canonical_maintenance_validates_candidate_and_readback() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "--vacuum-into work/rate_monitor_compacted.sqlite3" in text
    assert "storage upload" in text
    assert "--db work/rate_monitor_compacted.sqlite3" in text
    assert "storage restore --dest work/rate_monitor_r2_readback.sqlite3" in text
    assert (
        "cmp -s work/rate_monitor_compacted.sqlite3 work/rate_monitor_r2_readback.sqlite3"
        in text
    )
    assert 'audit["semantic_redundant_rows"] == 0' in text
    assert 'audit["integrity_check"] == "ok"' in text
    assert 'audit["foreign_key_check_violations"] == 0' in text
    assert 'apply["after_current_observations"] == apply["before_current_observations"]' in text
    assert "candidate_sha256" in text
    assert "readback_sha256" in text
