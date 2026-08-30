from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from rate_monitor.services import institution_funding_direct_peer_db as peer_db


def test_calibration_report_uses_latest_position_month_without_choosing_n(
    tmp_path: Path, monkeypatch
) -> None:
    db = tmp_path / "db.sqlite3"
    db.touch()

    monkeypatch.setattr(
        peer_db,
        "build_institution_funding_positions",
        lambda _db: {
            "display_order": ["nh_local"],
            "sectors": {"nh_local": {"analysis_month": "2025-12"}},
        },
    )
    monkeypatch.setattr(
        peer_db,
        "load_direct_peer_points",
        lambda _db, *, sector, analysis_month: [
            peer_db.DirectPeerPoint(
                institution_id="a",
                sector=sector,
                balance=Decimal("100"),
                growth_6m_pct=Decimal("0.01"),
                region_sido="부산",
                region_sigungu="중구",
            ),
            peer_db.DirectPeerPoint(
                institution_id="b",
                sector=sector,
                balance=Decimal("110"),
                growth_6m_pct=Decimal("0.02"),
                region_sido="부산",
                region_sigungu=None,
            ),
        ]
        if analysis_month == "2025-12"
        else [],
    )
    monkeypatch.setattr(
        peer_db,
        "calibrate_direct_peer_count",
        lambda _points, *, sector, requested_count: SimpleNamespace(
            sector=sector,
            requested_count=requested_count,
            target_count=2,
            full_count=0,
            shortfall_count=2,
            scope_counts={"nationwide": 2},
            max_log_distance_p50=Decimal("0.10"),
            max_log_distance_p90=Decimal("0.20"),
            growth_comparison_count=2,
        ),
    )

    report = peer_db.build_direct_peer_calibration_report(
        db,
        candidate_counts=(12, 16, 20),
    )

    nh = report["sectors"]["nh_local"]
    assert nh["analysis_month"] == "2025-12"
    assert nh["population_count"] == 2
    assert nh["growth_6m_available"] == 2
    assert nh["region_sido_known"] == 2
    assert nh["region_sigungu_known"] == 1
    assert nh["candidates"]["12"]["max_log_distance_p50"] == "0.10"
    assert set(nh["candidates"]) == {"12", "16", "20"}
    assert report["selection_contract"]["chosen_count"] is None
    assert report["selection_contract"]["quality_score"] is None
    assert report["selection_contract"]["missing_growth_as_zero"] is False
