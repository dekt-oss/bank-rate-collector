from pathlib import Path

WORKFLOW = Path(".github/workflows/recover-stale-collections.yml")


def test_stale_recovery_serializes_existing_current_main_workflows():
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "[recover-stale]" in text
    assert "stale-collection-recovery-control-plane" in text
    assert "group: rate-data-writer" not in text
    assert "recover_general:" in text
    assert "recover_kfcc:" in text
    assert "needs: recover_general" in text
    assert "recover_nh:" in text
    assert "needs: recover_kfcc" in text
    assert text.count("timeout-minutes: 360") == 3
    assert 'manual_target="일반 전체"' in text
    assert 'manual_target="새마을금고만"' in text
    assert 'kfcc_resume_mode=auto' in text
    assert 'gh workflow run collect-nh.yml' in text
    assert 'nh_resume_mode=auto' in text
    assert text.index('manual_target="일반 전체"') < text.index(
        'manual_target="새마을금고만"'
    ) < text.index('gh workflow run collect-nh.yml')
    assert text.count('gh run watch "$run_id"') == 3
    assert text.count("--exit-status") == 3
    assert text.count("--limit 1") == 6
    assert "--limit 5" not in text
    assert text.count("databaseId != $before") == 3
