"""Resolve Relative Pricing availability keys from official temporal memberships.

This module is intentionally narrower than pricing candidate construction. It only
consumes the authoritative ``institution_availability_memberships`` table created
from the FSB ``ratedepo`` AREA census. Raw institution geography, display
``availability_scope`` and institution names are never used as fallbacks.

R1 currently accepts one exact ``availability_match_key``. An institution may be
available in multiple FSB AREA values at the same time, so this resolver fails
closed for that case until Strategy exposes an explicit AREA scope selector.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from rate_monitor.services.fsb_availability_service import (
    AREA_LABELS,
    PRODUCT_TYPE,
    SOURCE_ID,
    availability_match_key,
)

RESOLUTION_RESOLVED = "resolved"
RESOLUTION_UNRESOLVED = "unresolved"
RESOLUTION_AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class RelativePricingAvailabilityResolution:
    status: str
    reason: str | None
    anchor_institution_id: str
    availability_match_key: str | None
    active_match_keys: tuple[str, ...]
    cohort_institution_ids: tuple[str, ...]
    as_of: str | None
    source_id: str = SOURCE_ID
    product_type: str = PRODUCT_TYPE

    def as_payload(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "anchor_institution_id": self.anchor_institution_id,
            "availability_match_key": self.availability_match_key,
            "active_match_keys": list(self.active_match_keys),
            "cohort_institution_ids": list(self.cohort_institution_ids),
            "as_of": self.as_of,
            "source_id": self.source_id,
            "product_type": self.product_type,
        }


def _normalized_as_of(value: date | datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return f"{value.isoformat()} 23:59:59"
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed_date = date.fromisoformat(text[:10])
        except ValueError as exc:
            raise ValueError("relative pricing availability as_of must be ISO date/datetime") from exc
        return f"{parsed_date.isoformat()} 23:59:59"
    return parsed.isoformat(sep=" ")


def _table_exists(conn: sqlite3.Connection) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='institution_availability_memberships' LIMIT 1"
        ).fetchone()
        is not None
    )


def _active_predicate(as_of: str | None) -> tuple[str, tuple[str, ...]]:
    if as_of is None:
        return "valid_to IS NULL", ()
    source_date = as_of[:10]
    return (
        "valid_from <= ? AND (valid_to IS NULL OR valid_to > ?) "
        "AND source_effective_date <= ?",
        (as_of, as_of, source_date),
    )


def _validated_key(area_code: str, stored_key: str) -> str:
    if area_code not in AREA_LABELS:
        raise ValueError(f"unsupported persisted FSB AREA: {area_code}")
    expected = availability_match_key(area_code)
    if stored_key != expected:
        raise ValueError(
            "persisted availability_match_key does not match authoritative AREA: "
            f"area={area_code}, stored={stored_key}, expected={expected}"
        )
    return expected


def resolve_fsb_relative_pricing_availability(
    db_path: Path,
    *,
    anchor_institution_id: str,
    as_of: date | datetime | str | None = None,
) -> RelativePricingAvailabilityResolution:
    """Resolve exactly one official FSB AREA key for the anchor institution.

    ``as_of=None`` means the currently active membership set. Historical callers
    must pass their factual snapshot time; current memberships are never carried
    backward implicitly.
    """

    anchor_id = str(anchor_institution_id or "").strip()
    if not anchor_id:
        raise ValueError("anchor_institution_id is required")
    normalized_as_of = _normalized_as_of(as_of)

    uri = db_path.resolve().as_uri() + "?mode=ro&immutable=1"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        if not _table_exists(conn):
            return RelativePricingAvailabilityResolution(
                status=RESOLUTION_UNRESOLVED,
                reason="availability_membership_table_unavailable",
                anchor_institution_id=anchor_id,
                availability_match_key=None,
                active_match_keys=(),
                cohort_institution_ids=(),
                as_of=normalized_as_of,
            )

        active_sql, active_params = _active_predicate(normalized_as_of)
        rows = conn.execute(
            f"""
            SELECT area_code, availability_match_key
            FROM institution_availability_memberships
            WHERE source_id = ?
              AND product_type = ?
              AND institution_id = ?
              AND {active_sql}
            ORDER BY area_code
            """,
            (SOURCE_ID, PRODUCT_TYPE, anchor_id, *active_params),
        ).fetchall()
        keys = tuple(
            sorted(
                {
                    _validated_key(str(row["area_code"]), str(row["availability_match_key"]))
                    for row in rows
                }
            )
        )
        if not keys:
            return RelativePricingAvailabilityResolution(
                status=RESOLUTION_UNRESOLVED,
                reason="availability_match_key_unresolved",
                anchor_institution_id=anchor_id,
                availability_match_key=None,
                active_match_keys=(),
                cohort_institution_ids=(),
                as_of=normalized_as_of,
            )
        if len(keys) != 1:
            return RelativePricingAvailabilityResolution(
                status=RESOLUTION_AMBIGUOUS,
                reason="availability_match_key_ambiguous",
                anchor_institution_id=anchor_id,
                availability_match_key=None,
                active_match_keys=keys,
                cohort_institution_ids=(),
                as_of=normalized_as_of,
            )

        match_key = keys[0]
        cohort_rows = conn.execute(
            f"""
            SELECT DISTINCT institution_id, area_code, availability_match_key
            FROM institution_availability_memberships
            WHERE source_id = ?
              AND product_type = ?
              AND availability_match_key = ?
              AND {active_sql}
            ORDER BY institution_id
            """,
            (SOURCE_ID, PRODUCT_TYPE, match_key, *active_params),
        ).fetchall()
        cohort: list[str] = []
        for row in cohort_rows:
            persisted = _validated_key(
                str(row["area_code"]), str(row["availability_match_key"])
            )
            if persisted != match_key:
                raise ValueError("availability cohort contains a mismatched key")
            cohort.append(str(row["institution_id"]))
        cohort_ids = tuple(sorted(set(cohort)))
        if anchor_id not in cohort_ids:
            raise ValueError("resolved availability cohort does not contain anchor institution")
        return RelativePricingAvailabilityResolution(
            status=RESOLUTION_RESOLVED,
            reason=None,
            anchor_institution_id=anchor_id,
            availability_match_key=match_key,
            active_match_keys=keys,
            cohort_institution_ids=cohort_ids,
            as_of=normalized_as_of,
        )
    finally:
        conn.close()
