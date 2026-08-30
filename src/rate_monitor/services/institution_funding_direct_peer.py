"""Pure direct-peer selection and calibration for institution funding metrics.

The canonical funding read model remains the source of truth. This module only
selects comparable peers from one exact sector/month population; it does not
impute missing history, merge identities, or infer geography.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal


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


@dataclass(frozen=True)
class DirectPeerCalibration:
    sector: str
    requested_count: int
    target_count: int
    full_count: int
    shortfall_count: int
    scope_counts: dict[str, int]
    max_log_distance_p50: Decimal | None
    max_log_distance_p90: Decimal | None
    growth_comparison_count: int


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


def _nearest_rank(values: list[Decimal], percentile: Decimal) -> Decimal | None:
    """Return an explicit nearest-rank percentile for calibration evidence."""
    if not values:
        return None
    ordered = sorted(values)
    rank = int(
        (percentile * Decimal(len(ordered)) / Decimal(100)).to_integral_value(
            rounding=ROUND_CEILING
        )
    )
    return ordered[max(0, min(len(ordered) - 1, rank - 1))]


def _distance(left: Decimal, right: Decimal) -> Decimal:
    if left <= 0 or right <= 0:
        raise ValueError("direct-peer balance must be positive")
    return abs(left.ln() - right.ln())


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


def _scope_candidates(
    target: DirectPeerPoint,
    peers: list[DirectPeerPoint],
    requested_count: int,
) -> tuple[str, list[DirectPeerPoint]]:
    if target.region_sido and target.region_sigungu:
        sigungu = [
            peer
            for peer in peers
            if peer.region_sido == target.region_sido
            and peer.region_sigungu == target.region_sigungu
        ]
        if len(sigungu) >= requested_count:
            return "sigungu", sigungu

    if target.region_sido:
        sido = [peer for peer in peers if peer.region_sido == target.region_sido]
        if len(sido) >= requested_count:
            return "sido", sido

    return "nationwide", peers


def select_direct_peers(
    points: Iterable[DirectPeerPoint],
    *,
    sector: str,
    institution_id: str,
    requested_count: int,
) -> DirectPeerSelection:
    """Select the nearest-size peers with deterministic geography fallback.

    The narrowest geographic tier is used only when it can supply the requested
    peer count. Otherwise selection falls back ``sigungu -> sido -> nationwide``.
    Within the chosen tier, proximity is absolute log-balance distance.
    """
    if requested_count < 1:
        raise ValueError("requested_count must be positive")

    population = _eligible_points(points, sector)
    target = next(
        (point for point in population if point.institution_id == institution_id),
        None,
    )
    if target is None:
        raise ValueError(f"direct-peer target not found: {institution_id}")

    peers = [point for point in population if point.institution_id != institution_id]
    scope, candidates = _scope_candidates(target, peers, requested_count)
    target_log = target.balance.ln()
    distance_by_id = {
        peer.institution_id: abs(target_log - peer.balance.ln()) for peer in candidates
    }
    ranked = sorted(
        candidates,
        key=lambda peer: (distance_by_id[peer.institution_id], peer.institution_id),
    )
    selected = ranked[:requested_count]
    growth_values = [
        peer.growth_6m_pct for peer in selected if peer.growth_6m_pct is not None
    ]
    peer_median = _median(growth_values)
    relative = (
        target.growth_6m_pct - peer_median
        if target.growth_6m_pct is not None and peer_median is not None
        else None
    )
    return DirectPeerSelection(
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


def calibrate_direct_peer_counts(
    points: Iterable[DirectPeerPoint],
    *,
    sector: str,
    requested_counts: Iterable[int],
) -> dict[int, DirectPeerCalibration]:
    """Measure several candidate N values with one distance ranking per target."""
    counts = tuple(sorted(set(requested_counts)))
    if not counts or any(count < 1 for count in counts):
        raise ValueError("requested_counts must contain positive integers")

    population = _eligible_points(points, sector)
    logs = {point.institution_id: point.balance.ln() for point in population}
    distances_by_count: dict[int, list[Decimal]] = {count: [] for count in counts}
    scopes_by_count: dict[int, Counter[str]] = {count: Counter() for count in counts}
    full_by_count = {count: 0 for count in counts}
    growth_by_count = {count: 0 for count in counts}

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
            [
                peer
                for peer in ranked_sido
                if peer.region_sigungu == target.region_sigungu
            ]
            if target.region_sido and target.region_sigungu
            else []
        )

        for count in counts:
            if len(ranked_sigungu) >= count:
                scope = "sigungu"
                candidates = ranked_sigungu
            elif len(ranked_sido) >= count:
                scope = "sido"
                candidates = ranked_sido
            else:
                scope = "nationwide"
                candidates = ranked_all

            selected = candidates[:count]
            scopes_by_count[count][scope] += 1
            if len(selected) == count:
                full_by_count[count] += 1
            if selected:
                distances_by_count[count].append(
                    max(distance_by_id[peer.institution_id] for peer in selected)
                )
            peer_median = _median(
                [
                    peer.growth_6m_pct
                    for peer in selected
                    if peer.growth_6m_pct is not None
                ]
            )
            if target.growth_6m_pct is not None and peer_median is not None:
                growth_by_count[count] += 1

    return {
        count: DirectPeerCalibration(
            sector=sector,
            requested_count=count,
            target_count=len(population),
            full_count=full_by_count[count],
            shortfall_count=len(population) - full_by_count[count],
            scope_counts=dict(sorted(scopes_by_count[count].items())),
            max_log_distance_p50=_nearest_rank(
                distances_by_count[count], Decimal(50)
            ),
            max_log_distance_p90=_nearest_rank(
                distances_by_count[count], Decimal(90)
            ),
            growth_comparison_count=growth_by_count[count],
        )
        for count in counts
    }


def calibrate_direct_peer_count(
    points: Iterable[DirectPeerPoint],
    *,
    sector: str,
    requested_count: int,
) -> DirectPeerCalibration:
    """Measure one candidate N without assigning an arbitrary quality score."""
    return calibrate_direct_peer_counts(
        points,
        sector=sector,
        requested_counts=(requested_count,),
    )[requested_count]
