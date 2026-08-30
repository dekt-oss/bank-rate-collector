from decimal import Decimal

import pytest

from rate_monitor.services.institution_funding_direct_peer import (
    DirectPeerPoint,
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


def test_direct_peer_uses_narrowest_region_that_can_fill_requested_count() -> None:
    points = [
        _point("target", "100", growth="0.10"),
        _point("a", "101", growth="0.08"),
        _point("b", "120", growth="0.02"),
        _point("other", "100.1", sigungu="서구"),
    ]
    result = select_direct_peers(
        points,
        sector="nh_local",
        institution_id="target",
        requested_count=2,
    )
    assert result.scope == "sigungu"
    assert result.peer_ids == ("a", "b")
    assert result.peer_median_growth_6m == Decimal("0.05")
    assert result.relative_growth_6m_vs_direct_peer == Decimal("0.05")
    assert result.shortfall is False


def test_direct_peer_falls_back_to_sido_then_nationwide() -> None:
    points = [
        _point("target", "100"),
        _point("same-gu", "101"),
        _point("same-sido", "99", sigungu="서구"),
        _point("other-sido", "100.1", sido="서울"),
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
    assert set(nationwide.peer_ids) == {"same-gu", "same-sido", "other-sido"}


def test_direct_peer_preserves_missing_growth_and_reports_shortfall() -> None:
    points = [
        _point("target", "100", growth=None, sido=None, sigungu=None),
        _point("one", "90", growth=None, sido=None, sigungu=None),
    ]
    result = select_direct_peers(
        points,
        sector="nh_local",
        institution_id="target",
        requested_count=16,
    )
    assert result.peer_ids == ("one",)
    assert result.shortfall is True
    assert result.peer_median_growth_6m is None
    assert result.relative_growth_6m_vs_direct_peer is None


def test_direct_peer_rejects_duplicate_exact_population() -> None:
    with pytest.raises(ValueError, match="duplicate direct-peer institution"):
        select_direct_peers(
            [_point("dup", "100"), _point("dup", "101")],
            sector="nh_local",
            institution_id="dup",
            requested_count=1,
        )
