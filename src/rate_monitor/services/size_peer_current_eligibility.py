"""Current-eligibility overlay for historical size-peer financial evidence.

Financial size and product availability intentionally have different clocks:
financial evidence is point-in-time, while this overlay answers whether an
institution is currently eligible for the selected product scenario. The two
clocks must be surfaced separately and never described as one historical state.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal

from rate_monitor.services.size_peer_universe import (
    BRANCH_BUSAN,
    REMOTE,
    SizePeerUniverseCandidate,
    SizePeerUniverseSelection,
    select_size_peer_universe,
)

ELIGIBILITY_OVERLAY_POLICY_ID = "strategy-size-peer-current-eligibility"
ELIGIBILITY_OVERLAY_POLICY_VERSION = "1"


class SizePeerEligibilityEvidenceError(ValueError):
    """Current eligibility evidence cannot be applied safely."""


@dataclass(frozen=True)
class TwoAxisFinancialCandidate:
    institution_id: str
    canonical_name: str
    sector: str
    source_institution_key: str
    deposit_liabilities_total: Decimal
    total_assets: Decimal


@dataclass(frozen=True)
class EligibilityEvidenceFact:
    institution_id: str
    source_channels: tuple[str, ...] = ()
    busan_districts: tuple[str, ...] = ()
    channel_evidence_source_id: str | None = None
    locality_evidence_source_id: str | None = None


@dataclass(frozen=True)
class RelativeGapEvidence:
    institution_id: str
    canonical_name: str
    sector: str
    funding_gap: Decimal
    assets_gap: Decimal
    worst_axis_gap: Decimal
    sum_gap: Decimal


@dataclass(frozen=True)
class EligibilityOverlayResult:
    policy_id: str
    policy_version: str
    financial_as_of: str
    eligibility_as_of: str
    term_months: int
    remote: SizePeerUniverseSelection
    branch_busan: SizePeerUniverseSelection
    missing_fact_count: int


def _required(value: object, *, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise SizePeerEligibilityEvidenceError(f"{field} is required")
    return text


def _positive_decimal(value: Decimal, *, field: str) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
        raise SizePeerEligibilityEvidenceError(f"{field} must be finite and positive")
    return value


def apply_current_eligibility(
    financial_candidates: Iterable[TwoAxisFinancialCandidate],
    evidence_facts: Iterable[EligibilityEvidenceFact],
    *,
    financial_as_of: str,
    eligibility_as_of: str,
    term_months: int,
) -> EligibilityOverlayResult:
    """Apply current scenario evidence without mutating historical financial facts."""

    financial_date = _required(financial_as_of, field="financial_as_of")
    eligibility_date = _required(eligibility_as_of, field="eligibility_as_of")
    if term_months <= 0:
        raise SizePeerEligibilityEvidenceError("term_months must be positive")

    by_id: dict[str, TwoAxisFinancialCandidate] = {}
    for candidate in financial_candidates:
        institution_id = _required(candidate.institution_id, field="candidate.institution_id")
        if institution_id in by_id:
            raise SizePeerEligibilityEvidenceError(
                f"duplicate financial candidate: {institution_id}"
            )
        _required(candidate.canonical_name, field="candidate.canonical_name")
        _required(candidate.sector, field="candidate.sector")
        _required(candidate.source_institution_key, field="candidate.source_institution_key")
        _positive_decimal(
            candidate.deposit_liabilities_total,
            field="candidate.deposit_liabilities_total",
        )
        _positive_decimal(candidate.total_assets, field="candidate.total_assets")
        by_id[institution_id] = candidate

    facts_by_id: dict[str, EligibilityEvidenceFact] = {}
    for fact in evidence_facts:
        institution_id = _required(fact.institution_id, field="fact.institution_id")
        if institution_id in facts_by_id:
            raise SizePeerEligibilityEvidenceError(
                f"duplicate eligibility fact: {institution_id}"
            )
        facts_by_id[institution_id] = fact

    universe_candidates = []
    missing_fact_count = 0
    for institution_id in sorted(by_id):
        financial = by_id[institution_id]
        fact = facts_by_id.get(institution_id)
        if fact is None:
            fact = EligibilityEvidenceFact(institution_id=institution_id)
            missing_fact_count += 1
        universe_candidates.append(
            SizePeerUniverseCandidate(
                institution_id=institution_id,
                sector=financial.sector,
                source_channels=fact.source_channels,
                outlet_sigungu=fact.busan_districts,
                channel_evidence_source_id=fact.channel_evidence_source_id,
                locality_evidence_source_id=fact.locality_evidence_source_id,
            )
        )

    return EligibilityOverlayResult(
        policy_id=ELIGIBILITY_OVERLAY_POLICY_ID,
        policy_version=ELIGIBILITY_OVERLAY_POLICY_VERSION,
        financial_as_of=financial_date,
        eligibility_as_of=eligibility_date,
        term_months=term_months,
        remote=select_size_peer_universe(universe_candidates, mode=REMOTE),
        branch_busan=select_size_peer_universe(universe_candidates, mode=BRANCH_BUSAN),
        missing_fact_count=missing_fact_count,
    )


def relative_gap_distribution(
    financial_candidates: Iterable[TwoAxisFinancialCandidate],
    *,
    eligible_ids: Iterable[str],
    anchor_id: str,
) -> tuple[RelativeGapEvidence, ...]:
    """Measure transparent two-axis relative gaps; this does not select peers."""

    candidates = {candidate.institution_id: candidate for candidate in financial_candidates}
    anchor_key = _required(anchor_id, field="anchor_id")
    try:
        anchor = candidates[anchor_key]
    except KeyError as exc:
        raise SizePeerEligibilityEvidenceError("anchor is absent from financial candidates") from exc
    anchor_funding = _positive_decimal(
        anchor.deposit_liabilities_total,
        field="anchor.deposit_liabilities_total",
    )
    anchor_assets = _positive_decimal(anchor.total_assets, field="anchor.total_assets")

    rows: list[RelativeGapEvidence] = []
    for institution_id in sorted(set(eligible_ids)):
        if institution_id == anchor_key:
            continue
        candidate = candidates.get(institution_id)
        if candidate is None:
            raise SizePeerEligibilityEvidenceError(
                f"eligible institution absent from financial candidates: {institution_id}"
            )
        funding_gap = abs(candidate.deposit_liabilities_total / anchor_funding - Decimal("1"))
        assets_gap = abs(candidate.total_assets / anchor_assets - Decimal("1"))
        rows.append(
            RelativeGapEvidence(
                institution_id=institution_id,
                canonical_name=candidate.canonical_name,
                sector=candidate.sector,
                funding_gap=funding_gap,
                assets_gap=assets_gap,
                worst_axis_gap=max(funding_gap, assets_gap),
                sum_gap=funding_gap + assets_gap,
            )
        )
    return tuple(
        sorted(
            rows,
            key=lambda row: (
                row.worst_axis_gap,
                row.sum_gap,
                row.canonical_name,
                row.institution_id,
            ),
        )
    )


def exclusion_reason_counts(selection: SizePeerUniverseSelection) -> dict[str, int]:
    counts = Counter(
        decision.reason for decision in selection.decisions if not decision.eligible
    )
    return dict(sorted(counts.items()))


def threshold_counts(
    rows: Iterable[RelativeGapEvidence],
    *,
    thresholds: Iterable[Decimal],
) -> Mapping[str, int]:
    materialized = tuple(rows)
    result: dict[str, int] = {}
    for threshold in thresholds:
        if threshold < 0:
            raise SizePeerEligibilityEvidenceError("threshold must be nonnegative")
        result[str(threshold)] = sum(
            1 for row in materialized if row.worst_axis_gap <= threshold
        )
    return result
