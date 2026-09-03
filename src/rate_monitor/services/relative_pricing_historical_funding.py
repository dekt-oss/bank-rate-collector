"""Point-in-time funding alignment for Relative Pricing R2.

The current Strategy funding reader intentionally uses the latest active revision
for each source month. Historical analogue recomputation has a stricter contract:
a correction or identity remap learned after the historical analysis date must
not leak backward. This module therefore reconstructs both the funding revision
and source-key identity evidence that were known at an explicit cutoff, then
reuses the canonical exact-month funding read model.

No nearest-month interpolation is performed. The caller must name the exact
funding month to align with a historical rate snapshot, and the payload preserves
rate and funding dates separately when they differ.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any

from rate_monitor.services.institution_funding_read_model import (
    FundingPoint,
    InstitutionFundingReadRow,
    build_institution_funding_read_model,
)
from rate_monitor.services.institution_funding_read_model_db import FUNDING_METRIC_CODE
from rate_monitor.services.relative_pricing_historical_funding_identity import (
    DATA_GO_SAVINGS_BANK_SOURCE_ID,
    SAVINGS_BANK_SECTOR,
    HistoricalFundingIdentityInput,
    resolve_historical_savings_bank_funding_identities,
)

HISTORICAL_FUNDING_POLICY_ID = "relative-pricing-historical-funding"
HISTORICAL_FUNDING_POLICY_VERSION = "1"

FUNDING_READY = "ready"
FUNDING_PARTIAL = "partial"
FUNDING_UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class HistoricalFundingBuild:
    status: str
    policy_id: str
    policy_version: str
    rate_as_of: date
    knowledge_as_of: datetime
    funding_as_of: str
    sector: str
    metric_code: str
    cohort_institution_ids: tuple[str, ...]
    funding_known_institution_ids: tuple[str, ...]
    funding_missing_institution_ids: tuple[str, ...]
    rows: tuple[InstitutionFundingReadRow, ...]

    @property
    def funding_join_count(self) -> int:
        return len(self.funding_known_institution_ids)

    @property
    def funding_unjoined_count(self) -> int:
        return len(self.funding_missing_institution_ids)

    @property
    def funding_join_ratio(self) -> Decimal:
        if not self.cohort_institution_ids:
            return Decimal(0)
        return Decimal(self.funding_join_count) / Decimal(
            len(self.cohort_institution_ids)
        )

    def as_payload(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "rate_as_of": self.rate_as_of.isoformat(),
            "knowledge_as_of": self.knowledge_as_of.isoformat(sep=" "),
            "funding_as_of": self.funding_as_of,
            "sector": self.sector,
            "metric_code": self.metric_code,
            "cohort_institution_ids": list(self.cohort_institution_ids),
            "funding_known_institution_ids": list(
                self.funding_known_institution_ids
            ),
            "funding_missing_institution_ids": list(
                self.funding_missing_institution_ids
            ),
            "funding_join_count": self.funding_join_count,
            "funding_unjoined_count": self.funding_unjoined_count,
            "funding_join_ratio": str(self.funding_join_ratio),
            "time_alignment": (
                "same_month"
                if self.funding_as_of == self.rate_as_of.strftime("%Y-%m")
                else "lagged_funding_month"
            ),
            "nearest_month_interpolation": False,
            "missing_as_zero": False,
            "mutable_observation_identity_trusted": False,
        }


def _required_text(value: object, *, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    return text


def _validate_month(value: str, *, field: str) -> str:
    text = _required_text(value, field=field)
    try:
        parsed = datetime.strptime(text, "%Y-%m")
    except ValueError as exc:
        raise ValueError(f"{field} must be YYYY-MM") from exc
    return parsed.strftime("%Y-%m")


def _normalized_cutoff(value: date | datetime | str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, time.max)
    else:
        text_value = _required_text(value, field="knowledge_as_of")
        try:
            parsed = datetime.fromisoformat(text_value.replace("Z", "+00:00"))
        except ValueError:
            try:
                parsed_date = date.fromisoformat(text_value)
            except ValueError as exc:
                raise ValueError("knowledge_as_of must be ISO date/datetime") from exc
            parsed = datetime.combine(parsed_date, time.max)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


def _parse_db_datetime(value: object, *, field: str) -> datetime:
    text_value = _required_text(value, field=field)
    try:
        parsed = datetime.fromisoformat(text_value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid persisted {field}: {text_value}") from exc
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


def _optional_db_datetime(value: object, *, field: str) -> datetime | None:
    text_value = str(value or "").strip()
    if not text_value:
        return None
    return _parse_db_datetime(text_value, field=field)


def _shift_month(month: str, delta: int) -> str:
    year, mon = (int(part) for part in month.split("-"))
    absolute = year * 12 + (mon - 1) + delta
    shifted_year, shifted_mon0 = divmod(absolute, 12)
    return f"{shifted_year:04d}-{shifted_mon0 + 1:02d}"


def _open_immutable_snapshot(db_path: Path) -> sqlite3.Connection:
    uri = db_path.resolve().as_uri() + "?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def load_historical_funding_points_as_known_at(
    db_path: Path,
    *,
    sector: str,
    analysis_month: str,
    knowledge_as_of: date | datetime | str,
    metric_code: str = FUNDING_METRIC_CODE,
) -> list[FundingPoint]:
    """Load exact-month funding and identity evidence known at the cutoff.

    Value revision validity is evaluated using ``valid_from``/``valid_to`` and
    ``observed_at``. Mutable observation identity fields are ignored for mapping;
    savings-bank identity is reconstructed from source links recorded by the same
    cutoff. If two value revisions of one source natural key are simultaneously
    valid, or reconstructed identity conflicts with a populated current mapping,
    the read fails closed.
    """

    target_sector = _required_text(sector, field="sector")
    if target_sector != SAVINGS_BANK_SECTOR:
        raise ValueError(
            "historical funding identity reconstruction currently supports "
            "savings_bank only"
        )
    target_month = _validate_month(analysis_month, field="analysis_month")
    target_metric = _required_text(metric_code, field="metric_code")
    cutoff = _normalized_cutoff(knowledge_as_of)
    if target_month > cutoff.strftime("%Y-%m"):
        raise ValueError("analysis_month cannot be later than knowledge_as_of")

    months = sorted(
        {target_month, _shift_month(target_month, -6), _shift_month(target_month, -12)}
    )
    placeholders = ",".join("?" for _ in months)
    connection = _open_immutable_snapshot(db_path)
    try:
        rows = connection.execute(
            f"""
            SELECT institution_id,
                   source_id,
                   source_institution_key,
                   source_institution_name,
                   source_crno,
                   sector,
                   source_effective_month,
                   value,
                   identity_status,
                   observed_at,
                   valid_from,
                   valid_to,
                   revision
            FROM institution_funding_observations
            WHERE sector = ?
              AND metric_code = ?
              AND source_effective_month IN ({placeholders})
            ORDER BY source_id, source_institution_key,
                     source_effective_month, revision
            """,
            (target_sector, target_metric, *months),
        ).fetchall()
    finally:
        connection.close()

    active_by_natural_key: dict[tuple[str, str, str], list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        valid_from = _parse_db_datetime(row["valid_from"], field="valid_from")
        valid_to = _optional_db_datetime(row["valid_to"], field="valid_to")
        observed_at = _parse_db_datetime(row["observed_at"], field="observed_at")
        if valid_from > cutoff or observed_at > cutoff:
            continue
        if valid_to is not None and valid_to <= cutoff:
            continue
        natural_key = (
            str(row["source_id"]),
            str(row["source_institution_key"]),
            str(row["source_effective_month"]),
        )
        active_by_natural_key[natural_key].append(row)

    selected: list[sqlite3.Row] = []
    for natural_key, revisions in sorted(active_by_natural_key.items()):
        if len(revisions) != 1:
            raise ValueError(
                "multiple funding revisions valid at historical cutoff: "
                f"natural_key={natural_key} revisions={len(revisions)}"
            )
        selected.append(revisions[0])

    unsupported_sources = sorted(
        {
            str(row["source_id"])
            for row in selected
            if str(row["source_id"]) != DATA_GO_SAVINGS_BANK_SOURCE_ID
        }
    )
    if unsupported_sources:
        raise ValueError(
            "unexpected historical savings-bank funding source(s): "
            + ",".join(unsupported_sources)
        )

    resolutions = resolve_historical_savings_bank_funding_identities(
        db_path,
        inputs=(
            HistoricalFundingIdentityInput(
                source_institution_key=str(row["source_institution_key"]),
                source_institution_name=str(row["source_institution_name"]),
                source_crno=str(row["source_crno"] or "").strip() or None,
            )
            for row in selected
        ),
        knowledge_as_of=cutoff,
    )

    points: list[FundingPoint] = []
    for row in selected:
        source_key = str(row["source_institution_key"])
        resolution = resolutions.get(source_key)
        if resolution is None or resolution.institution_id is None:
            continue
        current_institution_id = str(row["institution_id"] or "").strip() or None
        if (
            current_institution_id is not None
            and current_institution_id != resolution.institution_id
        ):
            raise ValueError(
                "historical funding identity conflicts with current observation: "
                f"source_key={source_key} historical={resolution.institution_id} "
                f"current={current_institution_id}"
            )
        points.append(
            FundingPoint(
                institution_id=resolution.institution_id,
                sector=str(row["sector"]),
                month=str(row["source_effective_month"]),
                balance=Decimal(str(row["value"])),
                identity_status="exact",
                quality_status="usable_exact",
            )
        )
    return sorted(points, key=lambda point: (point.institution_id, point.month))


def build_historical_relative_pricing_funding(
    db_path: Path,
    *,
    sector: str,
    cohort_institution_ids: Iterable[str],
    rate_as_of: date,
    funding_month: str,
    knowledge_as_of: date | datetime | str | None = None,
    metric_code: str = FUNDING_METRIC_CODE,
) -> HistoricalFundingBuild:
    """Build historical funding enrichment without changing pricing-peer eligibility."""

    if not isinstance(rate_as_of, date):
        raise ValueError("rate_as_of must be a date")
    target_sector = _required_text(sector, field="sector")
    target_month = _validate_month(funding_month, field="funding_month")
    if target_month > rate_as_of.strftime("%Y-%m"):
        raise ValueError("funding_month cannot be later than rate_as_of")
    cutoff = _normalized_cutoff(knowledge_as_of or rate_as_of)
    if cutoff.date() > rate_as_of:
        raise ValueError("knowledge_as_of cannot be later than rate_as_of")

    cohort = tuple(
        sorted(
            {
                _required_text(value, field="cohort institution_id")
                for value in cohort_institution_ids
            }
        )
    )
    if not cohort:
        raise ValueError("cohort_institution_ids must not be empty")

    points = load_historical_funding_points_as_known_at(
        db_path,
        sector=target_sector,
        analysis_month=target_month,
        knowledge_as_of=cutoff,
        metric_code=metric_code,
    )
    sector_rows = build_institution_funding_read_model(
        points,
        sector=target_sector,
        analysis_month=target_month,
    )
    cohort_set = set(cohort)
    rows = tuple(row for row in sector_rows if row.institution_id in cohort_set)
    known = tuple(sorted(row.institution_id for row in rows))
    missing = tuple(sorted(cohort_set - set(known)))

    if not known:
        status = FUNDING_UNAVAILABLE
    elif missing:
        status = FUNDING_PARTIAL
    else:
        status = FUNDING_READY

    return HistoricalFundingBuild(
        status=status,
        policy_id=HISTORICAL_FUNDING_POLICY_ID,
        policy_version=HISTORICAL_FUNDING_POLICY_VERSION,
        rate_as_of=rate_as_of,
        knowledge_as_of=cutoff,
        funding_as_of=target_month,
        sector=target_sector,
        metric_code=metric_code,
        cohort_institution_ids=cohort,
        funding_known_institution_ids=known,
        funding_missing_institution_ids=missing,
        rows=rows,
    )
