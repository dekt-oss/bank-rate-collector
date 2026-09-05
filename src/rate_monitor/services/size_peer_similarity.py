"""Deterministic two-axis ranking contract for Strategy size-peer references.

This module locks *ordering*, not peer membership. Eligibility is resolved
upstream and every eligible, non-anchor institution remains in the ranked
result. A UI may show the first N rows as a presentation convenience, but N is
not a financial-policy cutoff and must not be described as the peer universe.

The distance is deliberately transparent and weight-free:

- funding_gap = abs(peer_funding / anchor_funding - 1)
- assets_gap = abs(peer_assets / anchor_assets - 1)
- worst_axis_gap = max(funding_gap, assets_gap)
- tie breaker = funding_gap + assets_gap, then stable name/id

The policy is based on the authenticated production-copy distribution recorded
in ``docs/source-recon/20260905-size-peer-current-eligibility-evidence.md``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from rate_monitor.services.size_peer_current_eligibility import (
    RelativeGapEvidence,
    SizePeerEligibilityEvidenceError,
    TwoAxisFinancialCandidate,
    relative_gap_distribution,
)

SIZE_PEER_RANKING_POLICY_ID = "strategy-size-peer-worst-axis-relative-gap"
SIZE_PEER_RANKING_POLICY_VERSION = "1"


@dataclass(frozen=True)
class RankedSizePeer:
    rank: int
    institution_id: str
    canonical_name: str
    sector: str
    deposit_liabilities_total: Decimal
    total_assets: Decimal
    funding_gap: Decimal
    assets_gap: Decimal
    worst_axis_gap: Decimal
    sum_gap: Decimal


@dataclass(frozen=True)
class SizePeerRanking:
    policy_id: str
    policy_version: str
    financial_as_of: str
    eligibility_as_of: str
    eligibility_mode: str
    anchor_id: str
    eligible_count_including_anchor: int
    ranked_count_excluding_anchor: int
    rows: tuple[RankedSizePeer, ...]


def _required(value: object, *, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise SizePeerEligibilityEvidenceError(f"{field} is required")
    return text


def rank_size_peers(
    financial_candidates: Iterable[TwoAxisFinancialCandidate],
    *,
    eligible_ids: Iterable[str],
    anchor_id: str,
    financial_as_of: str,
    eligibility_as_of: str,
    eligibility_mode: str,
) -> SizePeerRanking:
    """Rank the full eligible universe without applying a cutoff or target N."""
    financial_date = _required(financial_as_of, field="financial_as_of")
    eligibility_date = _required(eligibility_as_of, field="eligibility_as_of")
    mode = _required(eligibility_mode, field="eligibility_mode")
    anchor_key = _required(anchor_id, field="anchor_id")

    candidates = tuple(financial_candidates)
    by_id = {candidate.institution_id: candidate for candidate in candidates}
    if len(by_id) != len(candidates):
        raise SizePeerEligibilityEvidenceError("duplicate financial candidate")

    eligible = tuple(sorted(set(eligible_ids)))
    if anchor_key not in eligible:
        raise SizePeerEligibilityEvidenceError("anchor is absent from eligible universe")

    gaps = relative_gap_distribution(
        candidates,
        eligible_ids=eligible,
        anchor_id=anchor_key,
    )
    rows = tuple(
        _ranked_row(rank, gap, by_id)
        for rank, gap in enumerate(gaps, start=1)
    )
    return SizePeerRanking(
        policy_id=SIZE_PEER_RANKING_POLICY_ID,
        policy_version=SIZE_PEER_RANKING_POLICY_VERSION,
        financial_as_of=financial_date,
        eligibility_as_of=eligibility_date,
        eligibility_mode=mode,
        anchor_id=anchor_key,
        eligible_count_including_anchor=len(eligible),
        ranked_count_excluding_anchor=len(rows),
        rows=rows,
    )


def _ranked_row(
    rank: int,
    gap: RelativeGapEvidence,
    candidates: dict[str, TwoAxisFinancialCandidate],
) -> RankedSizePeer:
    candidate = candidates[gap.institution_id]
    return RankedSizePeer(
        rank=rank,
        institution_id=gap.institution_id,
        canonical_name=gap.canonical_name,
        sector=gap.sector,
        deposit_liabilities_total=candidate.deposit_liabilities_total,
        total_assets=candidate.total_assets,
        funding_gap=gap.funding_gap,
        assets_gap=gap.assets_gap,
        worst_axis_gap=gap.worst_axis_gap,
        sum_gap=gap.sum_gap,
    )


def nearest_for_display(
    ranking: SizePeerRanking,
    *,
    limit: int,
) -> tuple[RankedSizePeer, ...]:
    """Return a UI slice only; this never changes membership or ranking policy."""
    if limit < 1:
        raise ValueError("limit must be positive")
    return ranking.rows[:limit]
