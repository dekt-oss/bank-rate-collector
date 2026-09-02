"""Read current Matrix representative-rate evidence without changing Matrix policy.

The production Rate x Funding Matrix keeps its existing representative-rate
contract. This adapter calls that exact reducer for the numeric rate and only
adds provenance needed by Relative Pricing reconciliation. It never invents an
observation date when multiple selected-rate rows disagree.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from rate_monitor.services.dashboard_service import dedupe_sources
from rate_monitor.services.rate_funding_matrix_service import (
    RATE_REPRESENTATIVE,
    _representative_rates,
)


@dataclass(frozen=True)
class MatrixRepresentativeEvidence:
    institution_id: str
    rate_pct: Decimal
    policy_id: str
    rate_as_of: date | None
    rate_as_of_status: str
    selected_product_ids: tuple[str, ...]
    selected_source_ids: tuple[str, ...]
    pricing_core_difference_reason: str | None

    def as_payload(self) -> dict[str, object]:
        return {
            "rate_pct": self.rate_pct,
            "policy_id": self.policy_id,
            "rate_as_of": self.rate_as_of,
            "rate_as_of_status": self.rate_as_of_status,
            "selected_product_ids": list(self.selected_product_ids),
            "selected_source_ids": list(self.selected_source_ids),
            "pricing_core_difference_reason": self.pricing_core_difference_reason,
        }


def _observation_date(row: sqlite3.Row) -> date | None:
    raw = row["source_effective_at"] or row["as_of"]
    if raw is None:
        return None
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def _precedence_rows(rows: list[sqlite3.Row]) -> list[sqlite3.Row]:
    retreating = set(dedupe_sources())
    covered_by_primary = {
        str(row["institution_id"])
        for row in rows
        if str(row["source_id"] or "") not in retreating
    }
    return [
        row
        for row in rows
        if not (
            str(row["source_id"] or "") in retreating
            and str(row["institution_id"]) in covered_by_primary
        )
    ]


def _pricing_core_exclusion_reason(rows: list[sqlite3.Row]) -> str | None:
    """Explain a Matrix-only selected rate only when every selected row is excluded.

    Relative Pricing core currently excludes special offers and inactive products.
    If even one Matrix-selected row is eligible under those two factual gates, the
    difference remains unexplained and the caller must fail closed.
    """
    if not rows:
        return None
    reasons_by_row: list[set[str]] = []
    for row in rows:
        reasons: set[str] = set()
        if bool(row["is_special_sale"]):
            reasons.add("special_offer")
        if not bool(row["product_active"]):
            reasons.add("inactive_product")
        reasons_by_row.append(reasons)
    if any(not reasons for reasons in reasons_by_row):
        return None
    reasons = sorted(set().union(*reasons_by_row))
    return "matrix_selection_outside_pricing_core:" + ",".join(reasons)


def build_current_matrix_representative_evidence(
    db_path: Path,
    *,
    institution_ids: tuple[str, ...] | list[str] | set[str],
    product_type: str = "term_deposit",
    term_months: int = 12,
) -> dict[str, MatrixRepresentativeEvidence]:
    """Return current Matrix-policy representative rates with conservative dates."""
    ids = tuple(sorted({str(value).strip() for value in institution_ids if str(value).strip()}))
    if not ids:
        return {}
    target_term = int(term_months)
    if target_term <= 0:
        raise ValueError("term_months must be positive")
    placeholders = ",".join("?" for _ in ids)
    uri = db_path.resolve().as_uri() + "?mode=ro&immutable=1"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            f"""
            SELECT p.institution_id,
                   p.id AS product_id,
                   cr.source_id,
                   CAST(ro.max_rate AS REAL) AS rate_value,
                   ro.source_effective_at,
                   ro.as_of,
                   p.is_special_sale,
                   p.active AS product_active
            FROM products p
            JOIN product_variants pv ON pv.product_id = p.id
            JOIN rate_observations ro ON ro.variant_id = pv.id
            JOIN collection_runs cr ON cr.id = ro.run_id
            WHERE p.institution_id IN ({placeholders})
              AND p.product_type = ?
              AND pv.term_months = ?
              AND ro.valid_to IS NULL
              AND ro.validation_status != 'error'
              AND ro.max_rate IS NOT NULL
            ORDER BY p.institution_id, p.id, pv.id, cr.source_id
            """,
            (*ids, product_type, target_term),
        ).fetchall()
    finally:
        conn.close()

    matrix_rates = _representative_rates(rows)
    surviving = _precedence_rows(rows)
    evidence: dict[str, MatrixRepresentativeEvidence] = {}
    for institution_id, rate in matrix_rates.items():
        selected_rows = [
            row
            for row in surviving
            if str(row["institution_id"]) == institution_id
            and Decimal(str(row["rate_value"])) == rate
        ]
        dates = {_observation_date(row) for row in selected_rows}
        if len(dates) == 1 and None not in dates:
            rate_as_of = next(iter(dates))
            rate_as_of_status = "resolved"
        elif None in dates:
            rate_as_of = None
            rate_as_of_status = "unresolved"
        else:
            rate_as_of = None
            rate_as_of_status = "ambiguous"
        evidence[institution_id] = MatrixRepresentativeEvidence(
            institution_id=institution_id,
            rate_pct=rate,
            policy_id=RATE_REPRESENTATIVE,
            rate_as_of=rate_as_of,
            rate_as_of_status=rate_as_of_status,
            selected_product_ids=tuple(
                sorted({str(row["product_id"]) for row in selected_rows})
            ),
            selected_source_ids=tuple(
                sorted({str(row["source_id"]) for row in selected_rows})
            ),
            pricing_core_difference_reason=_pricing_core_exclusion_reason(selected_rows),
        )
    return evidence
