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
    ranked = sorted(
        candidates,
        key=lambda peer: (
            _distance(target.balance, peer.balance),
            peer.institution_id,
        ),
    )
    selected = ranked[:requested_count]
    distances = [_distance(target.balance, peer.balance) for peer in selected]
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
        max_log_balance_distance=max(distances) if distances else None,
        peer_median_growth_6m=peer_median,
        target_growth_6m=target.growth_6m_pct,
        relative_growth_6m_vs_direct_peer=relative,
        shortfall=len(selected) < requested_count,
    )


def calibrate_direct_peer_count(
    points: Iterable[DirectPeerPoint],
    *,
    sector: str,
    requested_count: int,
) -> DirectPeerCalibration:
    """Measure one candidate N without assigning an arbitrary quality score."""
    population = _eligible_points(points, sector)
    selections = [
        select_direct_peers(
            population,
            sector=sector,
            institution_id=point.institution_id,
            requested_count=requested_count,
        )
        for point in population
    ]
    distances = [
        selection.max_log_balance_distance
        for selection in selections
        if selection.max_log_balance_distance is not None
    ]
    scope_counts = Counter(selection.scope for selection in selections)
    return DirectPeerCalibration(
        sector=sector,
        requested_count=requested_count,
        target_count=len(selections),
        full_count=sum(not selection.shortfall for selection in selections),
        shortfall_count=sum(selection.shortfall for selection in selections),
        scope_counts=dict(sorted(scope_counts.items())),
        max_log_distance_p50=_nearest_rank(distances, Decimal(50)),
        max_log_distance_p90=_nearest_rank(distances, Decimal(90)),
        growth_comparison_count=sum(
            selection.relative_growth_6m_vs_direct_peer is not None
            for selection in selections
        ),
    )
