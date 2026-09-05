"""Deterministic two-axis ranking contract for Strategy size-peer references.

This module locks *ordering*, not peer membership. Eligibility is resolved
upstream and every eligible, non-anchor institution remains in the ranked
result. A UI may show the first N rows as a presentation convenience, but N is
not a financial-policy cutoff and must not be described as the peer universe.

The final v1 distance is a symmetric log-ratio distance on both financial axes:

- funding_gap = abs(ln(peer_funding / anchor_funding))
- assets_gap = abs(ln(peer_assets / anchor_assets))
- worst_axis_gap = max(funding_gap, assets_gap)
- tie breaker = funding_gap + assets_gap, then stable canonical institution id

This deliberately differs from the simple relative-gap distribution used in
#310 to inspect empirical threshold counts. That diagnostic distribution did
not lock the final ranking policy.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from rate_monitor.services.size_peer_current_eligibility import (
    SizePeerEligibilityEvidenceError,
    TwoAxisFinancialCandidate,
)

SIZE_PEER_RANKING_POLICY_ID = "strategy-size-peer-worst-axis-log-ratio"
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


def _positive_decimal(value: Decimal, *, field: str) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
        raise SizePeerEligibilityEvidenceError(f"{field} must be finite and positive")
    return value


def _log_ratio_gap(value: Decimal, anchor: Decimal, *, field: str) -> Decimal:
    numerator = _positive_decimal(value, field=field)
    denominator = _positive_decimal(anchor, field=f"anchor.{field}")
    return abs((numerator / denominator).ln())


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
    by_id: dict[str, TwoAxisFinancialCandidate] = {}
    for candidate in candidates:
        institution_id = _required(candidate.institution_id, field="candidate.institution_id")
        if institution_id in by_id:
            raise SizePeerEligibilityEvidenceError("duplicate financial candidate")
        _required(candidate.canonical_name, field="candidate.canonical_name")
        _required(candidate.sector, field="candidate.sector")
        _positive_decimal(
            candidate.deposit_liabilities_total,
            field="candidate.deposit_liabilities_total",
        )
        _positive_decimal(candidate.total_assets, field="candidate.total_assets")
        by_id[institution_id] = candidate

    eligible = tuple(sorted(set(eligible_ids)))
    if anchor_key not in eligible:
        raise SizePeerEligibilityEvidenceError("anchor is absent from eligible universe")
    try:
        anchor = by_id[anchor_key]
    except KeyError as exc:
        raise SizePeerEligibilityEvidenceError(
            "anchor is absent from financial candidates"
        ) from exc

    ranked: list[RankedSizePeer] = []
    for institution_id in eligible:
        if institution_id == anchor_key:
            continue
        try:
            candidate = by_id[institution_id]
        except KeyError as exc:
            raise SizePeerEligibilityEvidenceError(
                f"eligible institution absent from financial candidates: {institution_id}"
            ) from exc

        funding_gap = _log_ratio_gap(
            candidate.deposit_liabilities_total,
            anchor.deposit_liabilities_total,
            field="deposit_liabilities_total",
        )
        assets_gap = _log_ratio_gap(
            candidate.total_assets,
            anchor.total_assets,
            field="total_assets",
        )
        ranked.append(
            RankedSizePeer(
                rank=0,
                institution_id=institution_id,
                canonical_name=candidate.canonical_name,
                sector=candidate.sector,
                deposit_liabilities_total=candidate.deposit_liabilities_total,
                total_assets=candidate.total_assets,
                funding_gap=funding_gap,
                assets_gap=assets_gap,
                worst_axis_gap=max(funding_gap, assets_gap),
                sum_gap=funding_gap + assets_gap,
            )
        )

    ordered = sorted(
        ranked,
        key=lambda row: (
            row.worst_axis_gap,
            row.sum_gap,
            row.institution_id,
        ),
    )
    rows = tuple(
        RankedSizePeer(
            rank=index,
            institution_id=row.institution_id,
            canonical_name=row.canonical_name,
            sector=row.sector,
            deposit_liabilities_total=row.deposit_liabilities_total,
            total_assets=row.total_assets,
            funding_gap=row.funding_gap,
            assets_gap=row.assets_gap,
            worst_axis_gap=row.worst_axis_gap,
            sum_gap=row.sum_gap,
        )
        for index, row in enumerate(ordered, start=1)
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


def nearest_for_display(
    ranking: SizePeerRanking,
    *,
    limit: int,
) -> tuple[RankedSizePeer, ...]:
    """Return a UI slice only; this never changes membership or ranking policy."""
    if limit < 1:
        raise ValueError("limit must be positive")
    return ranking.rows[:limit]
