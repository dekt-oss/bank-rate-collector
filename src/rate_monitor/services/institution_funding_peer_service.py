"""Direct-peer selection for institution funding competition analysis.

The peer population follows the user's existing Strategy geography rather than
introducing another independent scope selector. Size similarity uses logarithmic
balance distance so a 2x scale difference is treated consistently across small
and large institutions.

This module intentionally does not choose the target N/minimum sample constants.
Those values must be calibrated on production distributions (NH/agri-coop first)
and are explicit caller inputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class FundingPeerPoint:
    institution_id: str
    sector: str
    balance: Decimal
    region_sido: str | None
    region_sigungu: str | None


@dataclass(frozen=True)
class DirectPeer:
    institution_id: str
    balance: Decimal
    balance_ratio_to_target: Decimal
    log_balance_distance: Decimal
    region_sido: str | None
    region_sigungu: str | None


@dataclass(frozen=True)
class DirectPeerSelection:
    target_institution_id: str
    sector: str
    selected_scope: str
    selected_sido: str | None
    selected_sigungu: str | None
    candidate_count: int
    peer_count: int
    target_peer_count: int
    minimum_peer_count: int
    sample_status: str
    fallback_used: bool
    fallback_path: tuple[str, ...]
    peers: tuple[DirectPeer, ...]


def _scope_label(sido: str | None, sigungu: str | None) -> str:
    if sido and sigungu:
        return f"{sido} {sigungu}"
    if sido:
        return sido
    return "전국"


def _scope_chain(
    *,
    selected_sido: str | None,
    selected_sigungu: str | None,
) -> list[tuple[str | None, str | None]]:
    """Expand only through existing DB geography: sigungu -> sido -> nationwide."""
    scopes: list[tuple[str | None, str | None]] = []
    if selected_sido and selected_sigungu:
        scopes.append((selected_sido, selected_sigungu))
    if selected_sido:
        scopes.append((selected_sido, None))
    scopes.append((None, None))

    result: list[tuple[str | None, str | None]] = []
    for scope in scopes:
        if scope not in result:
            result.append(scope)
    return result


def _in_scope(
    point: FundingPeerPoint,
    *,
    sido: str | None,
    sigungu: str | None,
) -> bool:
    if sido is not None and point.region_sido != sido:
        return False
    return sigungu is None or point.region_sigungu == sigungu


def _usable_same_sector(
    points: list[FundingPeerPoint], *, sector: str
) -> list[FundingPeerPoint]:
    result: list[FundingPeerPoint] = []
    seen: set[str] = set()
    for point in points:
        if point.sector != sector or point.balance <= 0:
            continue
        if point.institution_id in seen:
            raise ValueError(
                "duplicate peer institution in usable population: "
                f"institution_id={point.institution_id}"
            )
        seen.add(point.institution_id)
        result.append(point)
    return result


def _size_distance(balance: Decimal, target_balance: Decimal) -> Decimal:
    return abs(balance.ln() - target_balance.ln())


def select_direct_funding_peers(
    points: list[FundingPeerPoint],
    *,
    target_institution_id: str,
    sector: str,
    selected_sido: str | None,
    selected_sigungu: str | None,
    target_peer_count: int,
    minimum_peer_count: int,
) -> DirectPeerSelection:
    """Select similar-sized peers while preserving explicit geography fallback.

    The initial population follows the current Strategy geography. If that
    population has fewer than ``minimum_peer_count`` peers, the function widens
    only through known geography levels and records every attempted scope. No
    silent fallback is allowed.
    """
    if target_peer_count < 1:
        raise ValueError("target_peer_count must be >= 1")
    if minimum_peer_count < 1:
        raise ValueError("minimum_peer_count must be >= 1")
    if minimum_peer_count > target_peer_count:
        raise ValueError("minimum_peer_count cannot exceed target_peer_count")
    if selected_sigungu and not selected_sido:
        raise ValueError("selected_sigungu requires selected_sido")

    usable = _usable_same_sector(points, sector=sector)
    target = next(
        (point for point in usable if point.institution_id == target_institution_id),
        None,
    )
    if target is None:
        raise ValueError(
            "target institution is not in usable same-sector funding population: "
            f"{target_institution_id}"
        )

    scopes = _scope_chain(
        selected_sido=selected_sido,
        selected_sigungu=selected_sigungu,
    )
    fallback_path: list[str] = []
    chosen_scope = scopes[-1]
    chosen_candidates: list[FundingPeerPoint] = []

    for index, (sido, sigungu) in enumerate(scopes):
        label = _scope_label(sido, sigungu)
        fallback_path.append(label)
        candidates = [
            point
            for point in usable
            if point.institution_id != target_institution_id
            and _in_scope(point, sido=sido, sigungu=sigungu)
        ]
        chosen_scope = (sido, sigungu)
        chosen_candidates = candidates
        if len(candidates) >= minimum_peer_count or index == len(scopes) - 1:
            break

    ranked = sorted(
        chosen_candidates,
        key=lambda point: (
            _size_distance(point.balance, target.balance),
            point.institution_id,
        ),
    )
    selected = ranked[:target_peer_count]
    peers = tuple(
        DirectPeer(
            institution_id=point.institution_id,
            balance=point.balance,
            balance_ratio_to_target=point.balance / target.balance,
            log_balance_distance=_size_distance(point.balance, target.balance),
            region_sido=point.region_sido,
            region_sigungu=point.region_sigungu,
        )
        for point in selected
    )
    sido, sigungu = chosen_scope
    initial_scope = scopes[0]
    return DirectPeerSelection(
        target_institution_id=target_institution_id,
        sector=sector,
        selected_scope=_scope_label(sido, sigungu),
        selected_sido=sido,
        selected_sigungu=sigungu,
        candidate_count=len(chosen_candidates),
        peer_count=len(peers),
        target_peer_count=target_peer_count,
        minimum_peer_count=minimum_peer_count,
        sample_status=(
            "sufficient" if len(chosen_candidates) >= minimum_peer_count else "insufficient"
        ),
        fallback_used=chosen_scope != initial_scope,
        fallback_path=tuple(fallback_path),
        peers=peers,
    )
