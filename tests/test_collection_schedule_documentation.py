"""Production collection schedule documentation must stay aligned with cron workflows."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = (ROOT / "docs/ops/collection-schedule.md").read_text(encoding="utf-8")

SCHEDULES = {
    ".github/workflows/collect-nh.yml": (
        ("30 8 * * 0-4", "전날 17:30"),
    ),
    ".github/workflows/collect.yml": (
        ("40 8 * * 0-4", "전날 17:40"),
        ("17 16 * * 0-4", "01:17"),
    ),
    ".github/workflows/collect-institution-funding.yml": (
        ("15 15 * * 0-4", "00:15"),
    ),
    ".github/workflows/collect-savings-fast.yml": (
        ("0 1 * * 1-5", "10:00"),
        ("0 6 * * 1-5", "15:00"),
    ),
    ".github/workflows/collect-size-peer-total-assets.yml": (
        ("17 16 1 * *", "매월 2일 01:17"),
    ),
}


def test_schedule_document_matches_production_workflow_crons() -> None:
    for relative_path, schedules in SCHEDULES.items():
        workflow = (ROOT / relative_path).read_text(encoding="utf-8")
        assert relative_path in DOC
        for cron, kst_label in schedules:
            assert f'- cron: "{cron}"' in workflow
            assert f"`{cron}`" in DOC
            assert kst_label in DOC


def test_schedule_document_locks_maintenance_contract() -> None:
    assert "같은 PR" in DOC
    assert "web/api/health.js" in DOC
    assert "rate-data-writer" in DOC
    assert "GitHub Actions의 cron은 예약 목표 시각이지 실제 시작 보장이 아니다" in DOC
