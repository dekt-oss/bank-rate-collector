"""Strategy 요약 호환 wrapper + 상품군/기간 이력 확장."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from rate_monitor.services import strategy_service_base as _base
from rate_monitor.services.institution_funding_position_service import (
    build_institution_funding_positions,
)
from rate_monitor.services.market_funding_strategy_service import (
    build_market_funding_strategy,
)
from rate_monitor.services.rate_funding_matrix_service import build_rate_funding_matrix
from rate_monitor.services.relative_pricing_availability_resolver import (
    RESOLUTION_RESOLVED,
    RelativePricingAvailabilityResolution,
    resolve_fsb_relative_pricing_availability,
)
from rate_monitor.services.relative_pricing_strategy_payload import (
    build_relative_pricing_unavailable_payload,
)
from rate_monitor.services.strategy_product_history_service import build_product_history
from rate_monitor.services.strategy_savings_trend_policy import (
    build_savings_trend_display_policy,
)
from rate_monitor.services.strategy_service_base import *  # noqa: F403


def __getattr__(name: str) -> Any:
    return getattr(_base, name)


def _our_canonical_institution_id(db_path: Path) -> str | None:
    """Resolve the configured Strategy anchor by exact canonical identity only.

    This is not an identity matcher: normalized/fuzzy names, address and geography
    are deliberately excluded. Multiple exact active rows are an integrity error.
    """

    uri = db_path.resolve().as_uri() + "?mode=ro&immutable=1"
    conn = sqlite3.connect(uri, uri=True)
    try:
        if (
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='institutions' LIMIT 1"
            ).fetchone()
            is None
        ):
            return None
        rows = conn.execute(
            """
            SELECT id
            FROM institutions
            WHERE sector = 'savings_bank'
              AND canonical_name = ?
              AND active = 1
            ORDER BY id
            """,
            (_base.OUR_INSTITUTION_NAME,),
        ).fetchall()
    finally:
        conn.close()
    if len(rows) > 1:
        raise ValueError(
            "Strategy anchor canonical identity resolved more than once: "
            + _base.OUR_INSTITUTION_NAME
        )
    return str(rows[0][0]) if rows else None


def _relative_pricing_availability(
    db_path: Path,
) -> RelativePricingAvailabilityResolution | None:
    anchor_id = _our_canonical_institution_id(db_path)
    if anchor_id is None:
        return None
    return resolve_fsb_relative_pricing_availability(
        db_path,
        anchor_institution_id=anchor_id,
    )


def build_strategy_summary(db_path: Path) -> dict[str, Any]:
    summary = _base.build_strategy_summary(db_path)
    product_history = build_product_history(db_path)
    product_history["savings_trend_display_policy"] = (
        build_savings_trend_display_policy(product_history)
    )
    summary["product_history"] = product_history
    summary["market_funding"] = build_market_funding_strategy(db_path)
    funding_positions = build_institution_funding_positions(db_path)
    summary["institution_funding_positions"] = funding_positions
    summary["rate_funding_matrix"] = build_rate_funding_matrix(
        db_path,
        funding_positions=funding_positions,
    )

    availability = _relative_pricing_availability(db_path)
    if availability is None:
        summary["relative_pricing_availability"] = {
            "status": "unresolved",
            "reason": "anchor_institution_id_unresolved",
            "anchor_institution_id": None,
            "availability_match_key": None,
            "active_match_keys": [],
            "cohort_institution_ids": [],
            "as_of": None,
            "source_id": "fsb",
            "product_type": "term_deposit",
        }
        # Preserve the existing public fail-closed reason until canonical anchor
        # identity and official availability evidence both exist.
        relative_reason = "availability_match_key_unresolved"
    else:
        summary["relative_pricing_availability"] = availability.as_payload()
        if availability.status == RESOLUTION_RESOLVED:
            # Availability is now factual, but current Strategy still lacks the
            # production candidate/reconciliation adapter required by R1 contract v3.
            relative_reason = "relative_pricing_rate_candidates_unresolved"
        else:
            relative_reason = availability.reason or "availability_match_key_unresolved"

    summary["relative_pricing"] = build_relative_pricing_unavailable_payload(
        reason=relative_reason
    )
    return summary
