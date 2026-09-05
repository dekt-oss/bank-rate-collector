"""Two-axis evidence model for Strategy size peers.

This module is intentionally persistence-free. It joins production-observed
deposit liabilities with source-validated total assets only when both metrics
refer to the exact same official institution key and reporting month.

It does not select peers. It only produces the evidence distribution required
before a similarity policy may be locked.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal

from rate_monitor.services.institution_funding_read_model_db import (
    VERIFIED_IDENTITY_STATUSES,
)

TWO_AXIS_POLICY_ID = "strategy-size-peer-two-axis-evidence"
TWO_AXIS_POLICY_VERSION = "1"


class SizePeerTwoAxisError(ValueError):
    """Two-axis evidence violates an identity, temporal, or uniqueness contract."""


@dataclass(frozen=True)
class FundingAxisEvidence:
    source_id: str
    sector: str
    source_institution_key: str
    source_institution_name: str
    source_crno: str | None
    institution_id: str | None
    canonical_name: str | None
    identity_status: str
    source_effective_month: str
    value: Decimal


@dataclass(frozen=True)
class AssetsAxisEvidence:
    source_id: str
    sector: str
    source_institution_key: str
    source_institution_name: str
    source_crno: str | None
    source_effective_month: str
    value: Decimal


@dataclass(frozen=True)
class SizePeerTwoAxisCandidate:
    institution_id: str
    canonical_name: str
    source_id: str
    sector: str
    source_institution_key: str
    source_institution_name: str
    source_crno: str | None
    source_effective_month: str
    deposit_liabilities_total: Decimal
    total_assets: Decimal


@dataclass(frozen=True)
class SizePeerTwoAxisMissing:
    source_id: str
    sector: str
    source_institution_key: str
    source_institution_name: str
    source_effective_month: str
    reason: str


@dataclass(frozen=True)
class SizePeerTwoAxisDistribution:
    policy_id: str
    policy_version: str
    source_effective_month: str
    candidates: tuple[SizePeerTwoAxisCandidate, ...]
    missing: tuple[SizePeerTwoAxisMissing, ...]
    missing_reason_counts: tuple[tuple[str, int], ...]
    fatal_conflict_count: int

    @property
    def evidence_ready(self) -> bool:
        return bool(self.candidates) and self.fatal_conflict_count == 0


def _required_text(value: object, *, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise SizePeerTwoAxisError(f"{field} is required")
    return text


def _month(value: object) -> str:
    text = _required_text(value, field="source_effective_month")
    if len(text) != 7 or text[4] != "-" or not text[:4].isdigit() or not text[5:].isdigit():
        raise SizePeerTwoAxisError(f"invalid source_effective_month: {value!r}")
    month = int(text[5:])
    if not 1 <= month <= 12:
        raise SizePeerTwoAxisError(f"invalid source_effective_month: {value!r}")
    return text


def _nonnegative(value: Decimal, *, field: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise SizePeerTwoAxisError(f"{field} must be Decimal")
    if not value.is_finite() or value < 0:
        raise SizePeerTwoAxisError(f"{field} must be finite and nonnegative")
    return value


def common_reporting_month_candidates(
    months_by_source: Mapping[str, Iterable[str]],
    *,
    required_source_ids: Iterable[str],
) -> tuple[str, ...]:
    """Return exact common reporting months, newest first.

    Missing sources and empty month sets fail closed to an empty result. No
    nearest-month or lag inference is performed here.
    """

    required = tuple(
        dict.fromkeys(
            _required_text(source_id, field="required_source_id")
            for source_id in required_source_ids
        )
    )
    if not required:
        raise SizePeerTwoAxisError("required_source_ids must not be empty")

    month_sets: list[set[str]] = []
    for source_id in required:
        values = months_by_source.get(source_id)
        if values is None:
            return ()
        normalized = {_month(value) for value in values}
        if not normalized:
            return ()
        month_sets.append(normalized)

    common = set.intersection(*month_sets)
    return tuple(sorted(common, reverse=True))


def _funding_key(point: FundingAxisEvidence, *, expected_month: str) -> tuple[str, str]:
    source_id = _required_text(point.source_id, field="funding.source_id")
    key = _required_text(point.source_institution_key, field="funding.source_institution_key")
    if _month(point.source_effective_month) != expected_month:
        raise SizePeerTwoAxisError(
            "funding point month mismatch: "
            f"source={source_id} key={key} point={point.source_effective_month} "
            f"expected={expected_month}"
        )
    _required_text(point.sector, field="funding.sector")
    _required_text(point.source_institution_name, field="funding.source_institution_name")
    _nonnegative(point.value, field="funding.value")
    return source_id, key


def _asset_key(point: AssetsAxisEvidence, *, expected_month: str) -> tuple[str, str]:
    source_id = _required_text(point.source_id, field="assets.source_id")
    key = _required_text(point.source_institution_key, field="assets.source_institution_key")
    if _month(point.source_effective_month) != expected_month:
        raise SizePeerTwoAxisError(
            "assets point month mismatch: "
            f"source={source_id} key={key} point={point.source_effective_month} "
            f"expected={expected_month}"
        )
    _required_text(point.sector, field="assets.sector")
    _required_text(point.source_institution_name, field="assets.source_institution_name")
    _nonnegative(point.value, field="assets.value")
    return source_id, key


def build_two_axis_distribution(
    funding_points: Iterable[FundingAxisEvidence],
    asset_points: Iterable[AssetsAxisEvidence],
    *,
    source_effective_month: str,
) -> SizePeerTwoAxisDistribution:
    """Join exact source identities at one exact reporting month.

    The official source key is the natural join key. Canonical institution
    mapping is taken only from the already-verified production funding record;
    asset rows never create a name-only identity mapping.
    """

    month = _month(source_effective_month)

    funding_by_key: dict[tuple[str, str], FundingAxisEvidence] = {}
    for point in funding_points:
        key = _funding_key(point, expected_month=month)
        if key in funding_by_key:
            raise SizePeerTwoAxisError(
                f"duplicate funding natural key: source={key[0]} key={key[1]} month={month}"
            )
        funding_by_key[key] = point

    assets_by_key: dict[tuple[str, str], AssetsAxisEvidence] = {}
    for point in asset_points:
        key = _asset_key(point, expected_month=month)
        if key in assets_by_key:
            raise SizePeerTwoAxisError(
                f"duplicate assets natural key: source={key[0]} key={key[1]} month={month}"
            )
        assets_by_key[key] = point

    candidates: list[SizePeerTwoAxisCandidate] = []
    missing: list[SizePeerTwoAxisMissing] = []
    fatal_conflict_count = 0

    for natural_key in sorted(funding_by_key):
        funding = funding_by_key[natural_key]
        asset = assets_by_key.get(natural_key)

        if not funding.institution_id or funding.identity_status not in VERIFIED_IDENTITY_STATUSES:
            missing.append(
                SizePeerTwoAxisMissing(
                    source_id=funding.source_id,
                    sector=funding.sector,
                    source_institution_key=funding.source_institution_key,
                    source_institution_name=funding.source_institution_name,
                    source_effective_month=month,
                    reason="institution_identity_unmapped",
                )
            )
            continue

        canonical_name = str(funding.canonical_name or "").strip()
        if not canonical_name:
            missing.append(
                SizePeerTwoAxisMissing(
                    source_id=funding.source_id,
                    sector=funding.sector,
                    source_institution_key=funding.source_institution_key,
                    source_institution_name=funding.source_institution_name,
                    source_effective_month=month,
                    reason="canonical_name_missing",
                )
            )
            fatal_conflict_count += 1
            continue

        if asset is None:
            missing.append(
                SizePeerTwoAxisMissing(
                    source_id=funding.source_id,
                    sector=funding.sector,
                    source_institution_key=funding.source_institution_key,
                    source_institution_name=funding.source_institution_name,
                    source_effective_month=month,
                    reason="total_assets_missing",
                )
            )
            continue

        if funding.sector != asset.sector:
            missing.append(
                SizePeerTwoAxisMissing(
                    source_id=funding.source_id,
                    sector=funding.sector,
                    source_institution_key=funding.source_institution_key,
                    source_institution_name=funding.source_institution_name,
                    source_effective_month=month,
                    reason="sector_mismatch",
                )
            )
            fatal_conflict_count += 1
            continue

        funding_crno = str(funding.source_crno or "").strip()
        asset_crno = str(asset.source_crno or "").strip()
        if funding_crno and asset_crno and funding_crno != asset_crno:
            missing.append(
                SizePeerTwoAxisMissing(
                    source_id=funding.source_id,
                    sector=funding.sector,
                    source_institution_key=funding.source_institution_key,
                    source_institution_name=funding.source_institution_name,
                    source_effective_month=month,
                    reason="identity_crno_conflict",
                )
            )
            fatal_conflict_count += 1
            continue

        candidates.append(
            SizePeerTwoAxisCandidate(
                institution_id=funding.institution_id,
                canonical_name=canonical_name,
                source_id=funding.source_id,
                sector=funding.sector,
                source_institution_key=funding.source_institution_key,
                source_institution_name=funding.source_institution_name,
                source_crno=funding_crno or asset_crno or None,
                source_effective_month=month,
                deposit_liabilities_total=funding.value,
                total_assets=asset.value,
            )
        )

    for natural_key in sorted(set(assets_by_key) - set(funding_by_key)):
        asset = assets_by_key[natural_key]
        missing.append(
            SizePeerTwoAxisMissing(
                source_id=asset.source_id,
                sector=asset.sector,
                source_institution_key=asset.source_institution_key,
                source_institution_name=asset.source_institution_name,
                source_effective_month=month,
                reason="funding_missing",
            )
        )

    canonical_ids: dict[str, tuple[str, str]] = {}
    for candidate in candidates:
        prior = canonical_ids.get(candidate.institution_id)
        current = (candidate.source_id, candidate.source_institution_key)
        if prior is not None and prior != current:
            raise SizePeerTwoAxisError(
                "duplicate canonical institution after exact source-key join: "
                f"institution_id={candidate.institution_id} first={prior} second={current}"
            )
        canonical_ids[candidate.institution_id] = current

    counts = Counter(item.reason for item in missing)
    return SizePeerTwoAxisDistribution(
        policy_id=TWO_AXIS_POLICY_ID,
        policy_version=TWO_AXIS_POLICY_VERSION,
        source_effective_month=month,
        candidates=tuple(
            sorted(
                candidates,
                key=lambda item: (item.sector, item.canonical_name, item.source_institution_key),
            )
        ),
        missing=tuple(
            sorted(
                missing,
                key=lambda item: (
                    item.reason,
                    item.sector,
                    item.source_institution_name,
                    item.source_institution_key,
                ),
            )
        ),
        missing_reason_counts=tuple(sorted(counts.items())),
        fatal_conflict_count=fatal_conflict_count,
    )
