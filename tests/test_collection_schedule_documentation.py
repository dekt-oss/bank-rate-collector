"""Production collection schedule documentation must stay aligned with cron workflows."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = (ROOT / "docs/ops/collection-schedule.md").read_text(encoding="utf-8")

SCHEDULES = {
    ".github/workflows/collect-morning-cycle.yml": (
        ("50 5 * * 0-4", "전날 14:50"),
    ),
    ".github/workflows/collect-savings-fast.yml": (
        ("0 1 * * 1-5", "10:00"),
        ("0 6 * * 1-5", "15:00"),
    ),
    ".github/workflows/collect-size-peer-total-assets.yml": (
        ("17 16 1 * *", "매월 2일 01:17"),
    ),
}

RETIRED_CHILD_SCHEDULES = {
    ".github/workflows/collect-nh.yml": (
        "30 8 * * 0-4",
    ),
    ".github/workflows/collect.yml": (
        "40 8 * * 0-4",
        "17 16 * * 0-4",
    ),
    ".github/workflows/collect-institution-funding.yml": (
        "15 15 * * 0-4",
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


def test_retired_child_crons_cannot_drift_back_in() -> None:
    for relative_path, retired_crons in RETIRED_CHILD_SCHEDULES.items():
        workflow = (ROOT / relative_path).read_text(encoding="utf-8")
        assert relative_path in DOC
        for cron in retired_crons:
            assert f'- cron: "{cron}"' not in workflow
        assert "morning" in DOC.lower()


def test_schedule_document_distinguishes_reservation_from_collection_runtime() -> None:
    assert "Action 예약 시각" in DOC
    assert "실제 수집 시각" in DOC
    assert "예약 시각 ≠ 실제 수집 시각" in DOC
    assert "created_at" in DOC
    assert "run_started_at" in DOC
    assert "실제 수집 시작 시각" in DOC
    assert "실제 수집 종료 시각" in DOC
    assert "canonical 반영 완료 시각" in DOC
    assert "실제 수집 시작 하한" in DOC
    assert "20:45" in DOC


def test_schedule_document_records_reverse_calculation_and_residual_risk() -> None:
    assert "6시간 41분" in DOC
    assert "8시간 54분" in DOC
    assert "50분" in DOC
    assert "07:15" in DOC
    assert "07:30" in DOC
    assert "08:00" in DOC
    assert "10시간" in DOC
    assert "독립 scheduler" in DOC
    assert "2026-09-17" in DOC
    assert "06:38" in DOC


def test_schedule_document_locks_maintenance_contract() -> None:
    assert "같은 PR" in DOC
    assert "web/api/health.js" in DOC
    assert "rate-data-writer" in DOC
    assert "GitHub Actions의 cron은 Action 예약 목표 시각이지 실제 수집 시작 보장이 아니다" in DOC
