"""Pure direct-peer selection for institution funding metrics.

The canonical funding read model remains the source of truth. This module only
selects comparable peers from one exact sector/month population; it does not
impute missing history, merge identities, or infer geography.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class DirectPeerPoint:
    institution_id: str
    sector: str
    balance: Decimal
    growth_6m_pct: Decimal | None
    region_sido: str | None = None
    region_sigungu: str | None = None


@dataclass(frozen=True)
class DirectPeerSelection:
    institution_id: str
    sector: str
    requested_count: int
    scope: str
    candidate_count: int
    peer_ids: tuple[str, ...]
    max_log_balance_distance: Decimal | None
    peer_median_growth_6m: Decimal | None
    target_growth_6m: Decimal | None
    relative_growth_6m_vs_direct_peer: Decimal | None
    shortfall: bool


def _normalized_region(value: str | None) -> str | None:
    text = str(value or "").strip()
    return text or None


def _median(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / Decimal(2)


def _eligible_points(
    points: Iterable[DirectPeerPoint], sector: str
) -> list[DirectPeerPoint]:
    result: list[DirectPeerPoint] = []
    seen: set[str] = set()
    for point in points:
        if point.sector != sector or point.balance <= 0:
            continue
        if point.institution_id in seen:
            raise ValueError(
                "duplicate direct-peer institution in exact sector/month population: "
                f"{point.institution_id}"
            )
        seen.add(point.institution_id)
        result.append(
            DirectPeerPoint(
                institution_id=point.institution_id,
                sector=point.sector,
                balance=point.balance,
                growth_6m_pct=point.growth_6m_pct,
                region_sido=_normalized_region(point.region_sido),
                region_sigungu=_normalized_region(point.region_sigungu),
            )
        )
    return result


def select_direct_peers_for_population(
    points: Iterable[DirectPeerPoint],
    *,
    sector: str,
    requested_count: int,
) -> dict[str, DirectPeerSelection]:
    """Select peers for every institution with one ranking pass per target.

    The narrowest geographic tier is used only when it can supply the requested
    count. Otherwise the deterministic fallback is ``sigungu -> sido -> nationwide``.
    Within the chosen tier, proximity is absolute log-balance distance.
    """
    if requested_count < 1:
        raise ValueError("requested_count must be positive")

    population = _eligible_points(points, sector)
    logs = {point.institution_id: point.balance.ln() for point in population}
    selections: dict[str, DirectPeerSelection] = {}

    for target in population:
        peers = [point for point in population if point.institution_id != target.institution_id]
        target_log = logs[target.institution_id]
        distance_by_id = {
            peer.institution_id: abs(target_log - logs[peer.institution_id]) for peer in peers
        }
        ranked_all = sorted(
            peers,
            key=lambda peer: (distance_by_id[peer.institution_id], peer.institution_id),
        )
        ranked_sido = (
            [peer for peer in ranked_all if peer.region_sido == target.region_sido]
            if target.region_sido
            else []
        )
        ranked_sigungu = (
            [peer for peer in ranked_sido if peer.region_sigungu == target.region_sigungu]
            if target.region_sido and target.region_sigungu
            else []
        )

        if len(ranked_sigungu) >= requested_count:
            scope = "sigungu"
            candidates = ranked_sigungu
        elif len(ranked_sido) >= requested_count:
            scope = "sido"
            candidates = ranked_sido
        else:
            scope = "nationwide"
            candidates = ranked_all

        selected = candidates[:requested_count]
        peer_median = _median(
            [peer.growth_6m_pct for peer in selected if peer.growth_6m_pct is not None]
        )
        relative = (
            target.growth_6m_pct - peer_median
            if target.growth_6m_pct is not None and peer_median is not None
            else None
        )
        selections[target.institution_id] = DirectPeerSelection(
            institution_id=target.institution_id,
            sector=sector,
            requested_count=requested_count,
            scope=scope,
            candidate_count=len(candidates),
            peer_ids=tuple(peer.institution_id for peer in selected),
            max_log_balance_distance=(
                max(distance_by_id[peer.institution_id] for peer in selected)
                if selected
                else None
            ),
            peer_median_growth_6m=peer_median,
            target_growth_6m=target.growth_6m_pct,
            relative_growth_6m_vs_direct_peer=relative,
            shortfall=len(selected) < requested_count,
        )

    return selections


def select_direct_peers(
    points: Iterable[DirectPeerPoint],
    *,
    sector: str,
    institution_id: str,
    requested_count: int,
) -> DirectPeerSelection:
    """Return one target's selection using the same population contract."""
    selections = select_direct_peers_for_population(
        points,
        sector=sector,
        requested_count=requested_count,
    )
    try:
        return selections[institution_id]
    except KeyError as exc:
        raise ValueError(f"direct-peer target not found: {institution_id}") from exc
