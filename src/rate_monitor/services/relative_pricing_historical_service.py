"""Point-in-time Relative Pricing R2 historical rate foundation.

R2 must not reuse current product metadata as if it had existed at a historical
``as_of``. This module therefore consumes explicit point-in-time evidence rows
and refuses to produce institution representative rates until the historical
special-offer state is proven for every otherwise-eligible product row.

The module is deliberately pure: it does not query FSB, read mutable Product
flags from SQLite, choose geography from current institution fields, or write a
snapshot. Upstream evidence adapters remain responsible for proving exact
institution/product identity and official availability at the requested date.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from rate_monitor.services.dashboard_service import dedupe_sources
from rate_monitor.services.institution_rate_reduction import (
    InstitutionRateCandidate,
    InstitutionRepresentativeRate,
    reduce_institution_rates,
)
from rate_monitor.services.public_structural_v2_market_position_service import normalize_rate

HISTORICAL_RATE_POLICY_ID = "relative-pricing-historical-rate-snapshot"
HISTORICAL_RATE_POLICY_VERSION = "1"

HISTORICAL_READY = "ready"
HISTORICAL_BLOCKED = "blocked"

REASON_SNAPSHOT_MISMATCH = "historical_rate_snapshot_mismatch"
REASON_IDENTITY_UNPROVEN = "historical_identity_unproven"
REASON_FUTURE_RATE = "future_rate_evidence_detected"
REASON_SPECIAL_OFFER_UNPROVEN = "historical_special_offer_scope_unproven"
REASON_RATE_UNAVAILABLE = "historical_rate_unavailable"
REASON_ANCHOR_REPRESENTATIVE_UNAVAILABLE = (
    "historical_anchor_representative_rate_unavailable"
)

EXACT_IDENTITY_METHOD = "exact_code"
SPECIAL_OFFER_EVIDENCE_EXPLICIT_SOURCE = "explicit_source_field"
SPECIAL_OFFER_EVIDENCE_VERSIONED_SCOPE = "versioned_product_scope_observation"
SPECIAL_OFFER_EVIDENCE_KINDS = frozenset(
    {
        SPECIAL_OFFER_EVIDENCE_EXPLICIT_SOURCE,
        SPECIAL_OFFER_EVIDENCE_VERSIONED_SCOPE,
    }
)

_UNKNOWN_MATCH_KEYS = frozenset(
    {"", "unknown", "none", "unavailable", "미상", "자료없음"}
)


@dataclass(frozen=True)
class HistoricalRateEvidenceRow:
    """One source-backed rate row effective in a historical source snapshot.

    ``snapshot_as_of`` is the official source query date whose screen promises
    the products/rates for that date. ``source_effective_at`` remains separate:
    when the source supplies an individual disclosure/effective date we retain
    it and reject any value later than the snapshot.

    Historical identity is accepted only when both mapping methods are
    ``exact_code``. ``special_offer_flag=None`` means *unproven*, not false.
    A boolean special-offer value is accepted only with an approved, versioned
    evidence kind; free-text heuristics cannot promote an unknown state.
    """

    institution_id: str
    product_id: str
    source_id: str
    sector: str
    product_type: str
    term_months: int
    join_channel: str
    availability_scope: str
    availability_match_key: str
    rate_pct: Decimal
    snapshot_as_of: date
    source_effective_at: date | None
    institution_identity_method: str | None
    product_identity_method: str | None
    special_offer_flag: bool | None
    special_offer_evidence_kind: str | None = None
    special_offer_evidence_ref: str | None = None


@dataclass(frozen=True)
class HistoricalRelativePricingBuild:
    status: str
    reason: str | None
    policy_id: str
    policy_version: str
    as_of: date
    anchor_institution_id: str
    availability_match_key: str
    cohort_institution_ids: tuple[str, ...]
    evidence_institution_ids: tuple[str, ...]
    missing_rate_institution_ids: tuple[str, ...]
    retreating_sources: tuple[str, ...]
    snapshot_mismatch_product_ids: tuple[str, ...]
    identity_unproven_product_ids: tuple[str, ...]
    future_rate_product_ids: tuple[str, ...]
    special_offer_unproven_product_ids: tuple[str, ...]
    candidates: tuple[InstitutionRateCandidate, ...]
    representatives: tuple[InstitutionRepresentativeRate, ...]

    def as_payload(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "as_of": self.as_of.isoformat(),
            "anchor_institution_id": self.anchor_institution_id,
            "availability_match_key": self.availability_match_key,
            "cohort_institution_ids": list(self.cohort_institution_ids),
            "evidence_institution_ids": list(self.evidence_institution_ids),
            "missing_rate_institution_ids": list(self.missing_rate_institution_ids),
            "retreating_sources": list(self.retreating_sources),
            "snapshot_mismatch_product_ids": list(self.snapshot_mismatch_product_ids),
            "identity_unproven_product_ids": list(self.identity_unproven_product_ids),
            "future_rate_product_ids": list(self.future_rate_product_ids),
            "special_offer_unproven_product_ids": list(
                self.special_offer_unproven_product_ids
            ),
            "candidate_count": len(self.candidates),
            "representative_count": len(self.representatives),
        }


def _required_text(value: object, *, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    return text


def _required_match_key(value: object) -> str:
    key = _required_text(value, field="availability_match_key")
    if key.casefold() in _UNKNOWN_MATCH_KEYS:
        raise ValueError("availability_match_key must be evidence-backed")
    return key


def _build_result(
    *,
    status: str,
    reason: str | None,
    as_of: date,
    anchor_institution_id: str,
    availability_match_key: str,
    cohort_institution_ids: tuple[str, ...],
    evidence_institution_ids: tuple[str, ...],
    retreating_sources: tuple[str, ...],
    snapshot_mismatch_product_ids: tuple[str, ...],
    identity_unproven_product_ids: tuple[str, ...],
    future_rate_product_ids: tuple[str, ...],
    special_offer_unproven_product_ids: tuple[str, ...],
    candidates: tuple[InstitutionRateCandidate, ...] = (),
    representatives: tuple[InstitutionRepresentativeRate, ...] = (),
) -> HistoricalRelativePricingBuild:
    return HistoricalRelativePricingBuild(
        status=status,
        reason=reason,
        policy_id=HISTORICAL_RATE_POLICY_ID,
        policy_version=HISTORICAL_RATE_POLICY_VERSION,
        as_of=as_of,
        anchor_institution_id=anchor_institution_id,
        availability_match_key=availability_match_key,
        cohort_institution_ids=cohort_institution_ids,
        evidence_institution_ids=evidence_institution_ids,
        missing_rate_institution_ids=tuple(
            sorted(set(cohort_institution_ids) - set(evidence_institution_ids))
        ),
        retreating_sources=retreating_sources,
        snapshot_mismatch_product_ids=snapshot_mismatch_product_ids,
        identity_unproven_product_ids=identity_unproven_product_ids,
        future_rate_product_ids=future_rate_product_ids,
        special_offer_unproven_product_ids=special_offer_unproven_product_ids,
        candidates=candidates,
        representatives=representatives,
    )


def _has_exact_identity(row: HistoricalRateEvidenceRow) -> bool:
    return (
        str(row.institution_identity_method or "").strip() == EXACT_IDENTITY_METHOD
        and str(row.product_identity_method or "").strip() == EXACT_IDENTITY_METHOD
    )


def _has_special_offer_provenance(row: HistoricalRateEvidenceRow) -> bool:
    kind = str(row.special_offer_evidence_kind or "").strip()
    return row.special_offer_flag is not None and kind in SPECIAL_OFFER_EVIDENCE_KINDS


def build_historical_relative_pricing_rates(
    rows: Iterable[HistoricalRateEvidenceRow],
    *,
    as_of: date,
    anchor_institution_id: str,
    cohort_institution_ids: Iterable[str],
    sector: str,
    product_type: str,
    term_months: int,
    availability_match_key: str,
    retreating_sources: Iterable[str] | None = None,
) -> HistoricalRelativePricingBuild:
    """Build historical representatives only from fully proven PIT evidence.

    The function intentionally blocks the whole representative-rate result when
    any otherwise-eligible row has unknown historical special-offer state. A
    higher-rate unknown row could otherwise alter which product becomes the
    institution representative, so silently dropping it is not safe.
    """

    if not isinstance(as_of, date):
        raise ValueError("as_of must be a date")
    anchor_id = _required_text(anchor_institution_id, field="anchor_institution_id")
    target_sector = _required_text(sector, field="sector")
    target_product_type = _required_text(product_type, field="product_type")
    target_match_key = _required_match_key(availability_match_key)
    target_term = int(term_months)
    if target_term <= 0:
        raise ValueError("term_months must be positive")

    cohort = tuple(
        sorted(
            {
                _required_text(value, field="cohort institution_id")
                for value in cohort_institution_ids
            }
        )
    )
    if not cohort:
        raise ValueError("historical availability cohort must not be empty")
    if anchor_id not in cohort:
        raise ValueError("historical availability cohort must contain anchor institution")
    cohort_set = set(cohort)
    resolved_retreating = tuple(
        sorted(
            set(
                retreating_sources
                if retreating_sources is not None
                else dedupe_sources()
            )
        )
    )

    eligible: list[HistoricalRateEvidenceRow] = []
    rate_evidence_institution_ids: set[str] = set()
    snapshot_mismatch: set[str] = set()
    identity_unproven: set[str] = set()
    future_rate: set[str] = set()
    special_unproven: set[str] = set()

    for row in rows:
        institution_id = _required_text(row.institution_id, field="institution_id")
        if institution_id not in cohort_set:
            continue
        if _required_text(row.sector, field="row sector") != target_sector:
            continue
        if _required_text(row.product_type, field="row product_type") != target_product_type:
            continue
        if int(row.term_months) != target_term:
            continue

        product_id = _required_text(row.product_id, field="product_id")
        row_match_key = _required_match_key(row.availability_match_key)
        if row_match_key != target_match_key:
            raise ValueError(
                "historical cohort row has a different availability_match_key: "
                f"product_id={product_id}"
            )
        if row.snapshot_as_of != as_of:
            snapshot_mismatch.add(product_id)
            continue
        if not _has_exact_identity(row):
            identity_unproven.add(product_id)
            continue
        if row.source_effective_at is not None and row.source_effective_at > as_of:
            future_rate.add(product_id)
            continue

        # Validate the rate even when product-scope provenance is unresolved.
        # A malformed/high-risk rate must not hide behind the later special-offer gate.
        normalize_rate(row.rate_pct)
        rate_evidence_institution_ids.add(institution_id)
        if not _has_special_offer_provenance(row):
            special_unproven.add(product_id)
            continue
        eligible.append(row)

    evidence_ids = tuple(sorted(rate_evidence_institution_ids))
    common = dict(
        as_of=as_of,
        anchor_institution_id=anchor_id,
        availability_match_key=target_match_key,
        cohort_institution_ids=cohort,
        evidence_institution_ids=evidence_ids,
        retreating_sources=resolved_retreating,
        snapshot_mismatch_product_ids=tuple(sorted(snapshot_mismatch)),
        identity_unproven_product_ids=tuple(sorted(identity_unproven)),
        future_rate_product_ids=tuple(sorted(future_rate)),
        special_offer_unproven_product_ids=tuple(sorted(special_unproven)),
    )

    if snapshot_mismatch:
        return _build_result(
            status=HISTORICAL_BLOCKED,
            reason=REASON_SNAPSHOT_MISMATCH,
            **common,
        )
    if identity_unproven:
        return _build_result(
            status=HISTORICAL_BLOCKED,
            reason=REASON_IDENTITY_UNPROVEN,
            **common,
        )
    if future_rate:
        return _build_result(
            status=HISTORICAL_BLOCKED,
            reason=REASON_FUTURE_RATE,
            **common,
        )
    if special_unproven:
        return _build_result(
            status=HISTORICAL_BLOCKED,
            reason=REASON_SPECIAL_OFFER_UNPROVEN,
            **common,
        )
    if not eligible:
        return _build_result(
            status=HISTORICAL_BLOCKED,
            reason=REASON_RATE_UNAVAILABLE,
            **common,
        )

    candidates = tuple(
        InstitutionRateCandidate(
            institution_id=_required_text(row.institution_id, field="institution_id"),
            product_id=_required_text(row.product_id, field="product_id"),
            source_id=_required_text(row.source_id, field="source_id"),
            sector=target_sector,
            product_type=target_product_type,
            term_months=target_term,
            join_channel=_required_text(row.join_channel, field="join_channel"),
            availability_scope=_required_text(
                row.availability_scope,
                field="availability_scope",
            ),
            availability_match_key=target_match_key,
            special_offer_flag=bool(row.special_offer_flag),
            rate_pct=normalize_rate(row.rate_pct),
            # The official historical query date is the point-in-time snapshot.
            # Individual source disclosure dates are retained above only for
            # future-leak validation and are never replaced by collection time.
            rate_as_of=as_of,
        )
        for row in eligible
    )
    representatives = tuple(
        reduce_institution_rates(
            candidates,
            sector=target_sector,
            product_type=target_product_type,
            term_months=target_term,
            availability_match_key=target_match_key,
            include_special_offer=False,
            retreating_sources=resolved_retreating,
        )
    )
    if anchor_id not in {row.institution_id for row in representatives}:
        return _build_result(
            status=HISTORICAL_BLOCKED,
            reason=REASON_ANCHOR_REPRESENTATIVE_UNAVAILABLE,
            candidates=candidates,
            representatives=representatives,
            **common,
        )
    return _build_result(
        status=HISTORICAL_READY,
        reason=None,
        candidates=candidates,
        representatives=representatives,
        **common,
    )
