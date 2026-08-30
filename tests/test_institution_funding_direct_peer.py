from decimal import Decimal

import pytest

from rate_monitor.services.institution_funding_direct_peer import (
    DirectPeerPoint,
    calibrate_direct_peer_count,
    select_direct_peers,
)


def _point(
    institution_id: str,
    balance: str,
    *,
    growth: str | None = "0.05",
    sido: str | None = "부산",
    sigungu: str | None = "중구",
) -> DirectPeerPoint:
    return DirectPeerPoint(
        institution_id=institution_id,
        sector="nh_local",
        balance=Decimal(balance),
        growth_6m_pct=Decimal(growth) if growth is not None else None,
        region_sido=sido,
        region_sigungu=sigungu,
    )


def test_direct_peer_uses_sigungu_when_it_can_fill_requested_count() -> None:
    points = [
        _point("target", "100", growth="0.10"),
        _point("near", "101", growth="0.08"),
        _point("far", "150", growth="0.02"),
        _point("other-sigungu", "100.5", sigungu="서구"),
    ]

    result = select_direct_peers(
        points,
        sector="nh_local",
        institution_id="target",
        requested_count=2,
    )

    assert result.scope == "sigungu"
    assert result.candidate_count == 2
    assert result.peer_ids == ("near", "far")
    assert result.peer_median_growth_6m == Decimal("0.05")
    assert result.relative_growth_6m_vs_direct_peer == Decimal("0.05")
    assert result.shortfall is False


def test_direct_peer_falls_back_sigungu_to_sido_then_nationwide() -> None:
    points = [
        _point("target", "100"),
        _point("same-gu", "101"),
        _point("same-sido", "99", sigungu="서구"),
        _point("other-sido", "100.1", sido="서울", sigungu="중구"),
    ]

    sido = select_direct_peers(
        points,
        sector="nh_local",
        institution_id="target",
        requested_count=2,
    )
    assert sido.scope == "sido"
    assert set(sido.peer_ids) == {"same-gu", "same-sido"}

    nationwide = select_direct_peers(
        points,
        sector="nh_local",
        institution_id="target",
        requested_count=3,
    )
    assert nationwide.scope == "nationwide"
    assert nationwide.peer_ids[0] == "other-sido"
    assert set(nationwide.peer_ids) == {"same-gu", "same-sido", "other-sido"}


def test_direct_peer_shortfall_is_explicit_and_missing_growth_is_not_zero() -> None:
    points = [
        _point("target", "100", growth=None, sido=None, sigungu=None),
        _point("one", "90", growth=None, sido=None, sigungu=None),
    ]

    result = select_direct_peers(
        points,
        sector="nh_local",
        institution_id="target",
        requested_count=12,
    )

    assert result.scope == "nationwide"
    assert result.peer_ids == ("one",)
    assert result.shortfall is True
    assert result.peer_median_growth_6m is None
    assert result.target_growth_6m is None
    assert result.relative_growth_6m_vs_direct_peer is None


def test_direct_peer_rejects_duplicate_institution_population() -> None:
    points = [_point("dup", "100"), _point("dup", "101")]

    with pytest.raises(ValueError, match="duplicate direct-peer institution"):
        select_direct_peers(
            points,
            sector="nh_local",
            institution_id="dup",
            requested_count=1,
        )


def test_calibration_reports_scope_shortfall_distance_and_growth_without_score() -> None:
    points = [
        _point("a", "100", growth="0.01"),
        _point("b", "110", growth="0.02"),
        _point("c", "120", growth="0.03", sigungu="서구"),
    ]

    result = calibrate_direct_peer_count(
        points,
        sector="nh_local",
        requested_count=2,
    )

    assert result.target_count == 3
    assert result.full_count == 3
    assert result.shortfall_count == 0
    assert result.scope_counts == {"sido": 3}
    assert result.max_log_distance_p50 is not None
    assert result.max_log_distance_p90 is not None
    assert result.growth_comparison_count == 3
    assert not hasattr(result, "quality_score")
