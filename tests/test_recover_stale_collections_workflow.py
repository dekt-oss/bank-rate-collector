from __future__ import annotations

from pathlib import Path


WORKFLOW = Path(".github/workflows/recover-stale-collections.yml")


def test_stale_recovery_serializes_existing_current_main_workflows():
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "[recover-stale]" in text
    assert "stale-collection-recovery-control-plane" in text
    assert "group: rate-data-writer" not in text
    assert 'dispatch_and_wait collect.yml' in text
    assert 'manual_target="일반 전체"' in text
    assert 'manual_target="새마을금고만"' in text
    assert 'kfcc_resume_mode=auto' in text
    assert 'dispatch_and_wait collect-nh.yml' in text
    assert 'nh_resume_mode=auto' in text
    assert text.index('manual_target="일반 전체"') < text.index(
        'manual_target="새마을금고만"'
    ) < text.index('dispatch_and_wait collect-nh.yml')
    assert 'gh run watch "$run_id"' in text
    assert "--exit-status" in text
