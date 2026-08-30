from decimal import Decimal

import pytest

from rate_monitor.services.institution_funding_peer_service import (
    FundingPeerPoint,
    select_direct_funding_peers,
)


def point(
    institution_id: str,
    balance: str,
    *,
    sido: str | None = "부산",
    sigungu: str | None = "중구",
    sector: str = "nh_local",
) -> FundingPeerPoint:
    return FundingPeerPoint(
        institution_id=institution_id,
        sector=sector,
        balance=Decimal(balance),
        region_sido=sido,
        region_sigungu=sigungu,
    )


def test_selects_nearest_size_peers_with_log_distance() -> None:
    result = select_direct_funding_peers(
        [
            point("target", "1000"),
            point("half", "500"),
            point("double", "2000"),
            point("near", "1100"),
            point("far", "10000"),
        ],
        target_institution_id="target",
        sector="nh_local",
        selected_sido="부산",
        selected_sigungu="중구",
        target_peer_count=3,
        minimum_peer_count=3,
    )

    assert result.selected_scope == "부산 중구"
    assert result.fallback_used is False
    assert result.sample_status == "sufficient"
    assert [peer.institution_id for peer in result.peers] == ["near", "half", "double"]
    assert result.peers[1].log_balance_distance == result.peers[2].log_balance_distance
    assert result.peers[0].balance_ratio_to_target == Decimal("1.1")


def test_fallback_is_explicit_sigungu_to_sido() -> None:
    result = select_direct_funding_peers(
        [
            point("target", "1000", sigungu="중구"),
            point("same-district", "900", sigungu="중구"),
            point("other-1", "950", sigungu="동구"),
            point("other-2", "1100", sigungu="서구"),
            point("other-3", "1200", sigungu="남구"),
        ],
        target_institution_id="target",
        sector="nh_local",
        selected_sido="부산",
        selected_sigungu="중구",
        target_peer_count=3,
        minimum_peer_count=3,
    )

    assert result.selected_scope == "부산"
    assert result.fallback_used is True
    assert result.fallback_path == ("부산 중구", "부산")
    assert result.candidate_count == 4
    assert result.peer_count == 3


def test_fallback_can_reach_nationwide_but_reports_insufficient_sample() -> None:
    result = select_direct_funding_peers(
        [
            point("target", "1000", sido="부산", sigungu="중구"),
            point("seoul", "900", sido="서울", sigungu="중구"),
            point("daegu", "1100", sido="대구", sigungu="중구"),
        ],
        target_institution_id="target",
        sector="nh_local",
        selected_sido="부산",
        selected_sigungu="중구",
        target_peer_count=4,
        minimum_peer_count=3,
    )

    assert result.selected_scope == "전국"
    assert result.fallback_path == ("부산 중구", "부산", "전국")
    assert result.sample_status == "insufficient"
    assert result.peer_count == 2


def test_rejects_duplicate_usable_institution() -> None:
    with pytest.raises(ValueError, match="duplicate peer institution"):
        select_direct_funding_peers(
            [point("target", "1000"), point("dup", "900"), point("dup", "950")],
            target_institution_id="target",
            sector="nh_local",
            selected_sido="부산",
            selected_sigungu="중구",
            target_peer_count=2,
            minimum_peer_count=1,
        )


def test_requires_sido_when_sigungu_is_selected() -> None:
    with pytest.raises(ValueError, match="selected_sigungu requires selected_sido"):
        select_direct_funding_peers(
            [point("target", "1000"), point("peer", "900")],
            target_institution_id="target",
            sector="nh_local",
            selected_sido=None,
            selected_sigungu="중구",
            target_peer_count=1,
            minimum_peer_count=1,
        )
