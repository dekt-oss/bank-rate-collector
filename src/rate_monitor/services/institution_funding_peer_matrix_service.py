"""Rate × Funding Peer Matrix payload built from current canonical data.

The X axis reuses the Strategy comparison-rate contract rather than inventing a
new rate definition. The Y axis is exact 6M institution funding growth; 12M is
supporting context. Sector populations are never mixed because their funding
reporting months/cadences can differ.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from rate_monitor.services.dashboard_service import dedupe_sources
from rate_monitor.services.institution_funding_position_service import (
    build_institution_funding_positions,
)
from rate_monitor.services.strategy_contract_service import (
    NH_EJOY_APPLICABILITY_NOTE,
    NH_EJOY_PRODUCT,
    NH_EJOY_TERMS,
    NH_TERM_DEPOSIT_TARGETS,
    STRATEGY_PRODUCT_TYPE,
    STRATEGY_RATE_BASIS_COLLECTED_BASE,
    STRATEGY_RATE_BASIS_NH_EJOY,
    STRATEGY_RATE_BASIS_PRIORITY,
    STRATEGY_RATE_BASIS_SOURCE_MAX,
    STRATEGY_TERMS,
)

MATRIX_VERSION = "institution-funding-peer-matrix-v1"
RATE_AGGREGATION = "institution_max_strategy_rate_for_selected_term"
SPECIAL_SALE_POLICY = "included_if_present_in_current_strategy_universe"
RELATION_SEMANTICS = "descriptive_association_not_causal_effect"


@dataclass(frozen=True)
class _RateRow:
    source_id: str
    institution_id: str
    institution: str
    normalized_institution: str
    sector: str
    product_id: str
    product: str
    is_special_sale: bool
    product_type: str
    term_months: int
    outlet_id: str | None
    outlet: str | None
    region_sido: str | None
    region_sigungu: str | None
    geo_basis: str | None
    base_rate: Decimal | None
    source_max_rate: Decimal | None
    raw_preference_text: str
    source_effective_at: str | None


@dataclass(frozen=True)
class _StrategyRate:
    row: _RateRow
    rate: Decimal
    basis: str


def _decimal(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        result = Decimal(str(value))
    except Exception:  # pragma: no cover - sqlite values are scalar by contract
        return None
    return result if result.is_finite() else None


def _load_rate_rows(db_path: Path) -> list[_RateRow]:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT
                r.source_id,
                i.id,
                i.canonical_name,
                COALESCE(i.normalized_name, i.canonical_name),
                i.sector,
                p.id,
                p.name,
                p.is_special_sale,
                p.product_type,
                v.term_months,
                v.outlet_id,
                outlet.name,
                COALESCE(outlet.region_sido, i.region_sido),
                COALESCE(outlet.region_sigungu, i.region_sigungu),
                COALESCE(NULLIF(outlet.geo_basis, 'none'), i.geo_basis),
                o.base_rate,
                o.max_rate,
                o.raw_preference_text,
                o.source_effective_at
            FROM rate_observations o
            JOIN collection_runs r ON r.id = o.last_run_id
            JOIN product_variants v ON v.id = o.variant_id
            JOIN products p ON p.id = v.product_id
            JOIN institutions i ON i.id = p.institution_id
            LEFT JOIN outlets outlet ON outlet.id = v.outlet_id
            WHERE o.valid_to IS NULL
              AND o.validation_status != 'error'
              AND p.active = 1
              AND i.sector IN ('savings_bank', 'nh_local', 'cu')
              AND p.product_type = ?
              AND v.term_months IN (6, 12, 24, 36)
              AND (o.max_rate IS NOT NULL OR o.base_rate IS NOT NULL)
            """,
            (STRATEGY_PRODUCT_TYPE,),
        ).fetchall()
    finally:
        conn.close()

    return [
        _RateRow(
            source_id=str(row[0]),
            institution_id=str(row[1]),
            institution=str(row[2] or ""),
            normalized_institution=str(row[3] or ""),
            sector=str(row[4]),
            product_id=str(row[5]),
            product=str(row[6] or ""),
            is_special_sale=bool(row[7]),
            product_type=str(row[8]),
            term_months=int(row[9]),
            outlet_id=str(row[10]) if row[10] else None,
            outlet=str(row[11]) if row[11] else None,
            region_sido=str(row[12]) if row[12] else None,
            region_sigungu=str(row[13]) if row[13] else None,
            geo_basis=str(row[14]) if row[14] else None,
            base_rate=_decimal(row[15]),
            source_max_rate=_decimal(row[16]),
            raw_preference_text=str(row[17] or ""),
            source_effective_at=str(row[18]) if row[18] else None,
        )
        for row in rows
    ]


def _precedence_key(row: _RateRow) -> tuple[str, str, int]:
    return (row.normalized_institution, row.product_type, row.term_months)


def _apply_source_precedence(rows: list[_RateRow]) -> list[_RateRow]:
    retreating = set(dedupe_sources())
    if not retreating:
        return rows
    covered = {_precedence_key(row) for row in rows if row.source_id not in retreating}
    return [
        row
        for row in rows
        if row.source_id not in retreating or _precedence_key(row) not in covered
    ]


def _location_key(row: _RateRow) -> tuple[object, ...]:
    return (
        row.source_id,
        row.institution_id,
        row.outlet_id,
        row.region_sido,
        row.region_sigungu,
    )


def _nh_options(rows: list[_RateRow]) -> dict[tuple[object, ...], dict[int, Decimal]]:
    grouped: dict[tuple[object, ...], dict[int, list[Decimal]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for row in rows:
        if row.sector != "nh_local" or row.product != NH_EJOY_PRODUCT:
            continue
        if row.raw_preference_text != NH_EJOY_APPLICABILITY_NOTE:
            continue
        if row.term_months not in NH_EJOY_TERMS or row.base_rate is None:
            continue
        grouped[_location_key(row)][row.term_months].append(row.base_rate)

    result: dict[tuple[object, ...], dict[int, Decimal]] = {}
    for key, by_term in grouped.items():
        if set(by_term) != set(NH_EJOY_TERMS):
            continue
        if any(len(by_term[term]) != 1 for term in NH_EJOY_TERMS):
            continue
        result[key] = {term: by_term[term][0] for term in NH_EJOY_TERMS}
    return result


def _nh_option(options: dict[int, Decimal], term: int) -> Decimal | None:
    lower = 1 if term < 12 else 12 if term < 24 else 24 if term < 36 else 36
    return options.get(lower)


def _strategy_rates(rows: list[_RateRow]) -> list[_StrategyRate]:
    visible = _apply_source_precedence(rows)
    nh_options = _nh_options(visible)
    candidates: list[_StrategyRate] = []
    for row in visible:
        if row.sector == "nh_local" and row.product == NH_EJOY_PRODUCT:
            continue
        if row.source_max_rate is not None:
            rate = row.source_max_rate
            basis = STRATEGY_RATE_BASIS_SOURCE_MAX
        elif (
            row.sector == "nh_local"
            and row.product in NH_TERM_DEPOSIT_TARGETS
            and row.base_rate is not None
        ):
            options = nh_options.get(_location_key(row))
            add_rate = _nh_option(options, row.term_months) if options else None
            if add_rate is not None:
                rate = row.base_rate + add_rate
                basis = STRATEGY_RATE_BASIS_NH_EJOY
            else:
                rate = row.base_rate
                basis = STRATEGY_RATE_BASIS_COLLECTED_BASE
        elif row.base_rate is not None:
            rate = row.base_rate
            basis = STRATEGY_RATE_BASIS_COLLECTED_BASE
        else:
            continue
        candidates.append(_StrategyRate(row=row, rate=rate, basis=basis))

    # Match Strategy contract's product-level representative intent first.
    product_best: dict[tuple[object, ...], _StrategyRate] = {}
    for candidate in candidates:
        row = candidate.row
        key = (
            row.sector,
            row.product_id,
            row.term_months,
            row.geo_basis,
            row.region_sido,
            row.region_sigungu,
        )
        old = product_best.get(key)
        if old is None or _rate_score(candidate) > _rate_score(old):
            product_best[key] = candidate
    return list(product_best.values())


def _rate_score(candidate: _StrategyRate) -> tuple[Decimal, int, str, str]:
    return (
        candidate.rate,
        STRATEGY_RATE_BASIS_PRIORITY.get(candidate.basis, 0),
        candidate.row.source_effective_at or "",
        candidate.row.product_id,
    )


def _institution_term_rates(rows: list[_StrategyRate]) -> dict[tuple[str, int], _StrategyRate]:
    """Highest current Strategy comparison rate for each institution and term."""
    result: dict[tuple[str, int], _StrategyRate] = {}
    for candidate in rows:
        key = (candidate.row.institution_id, candidate.row.term_months)
        old = result.get(key)
        if old is None or _rate_score(candidate) > _rate_score(old):
            result[key] = candidate
    return result


def _median(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / Decimal(2)


def _text(value: object) -> str | None:
    return None if value is None else str(value)


def build_institution_funding_peer_matrix(db_path: Path) -> dict[str, Any]:
    """Build all currently supportable sector/term matrix points.

    A plotted point requires an exact 6M funding growth value. Rows that have a
    current rate and funding balance but lack exact 6M history are counted as
    unavailable instead of being assigned 0% growth.
    """
    positions = build_institution_funding_positions(db_path)
    strategy_rates = _strategy_rates(_load_rate_rows(db_path))
    rates = _institution_term_rates(strategy_rates)

    sectors: dict[str, Any] = {}
    for sector, position in positions.get("sectors", {}).items():
        funding_by_id = {
            str(row["institution_id"]): row for row in position.get("rows", [])
        }
        terms: dict[str, Any] = {}
        for term in sorted(STRATEGY_TERMS):
            all_joined: list[dict[str, Any]] = []
            unavailable_growth = 0
            for institution_id, funding in funding_by_id.items():
                rate = rates.get((institution_id, term))
                if rate is None or rate.row.sector != sector:
                    continue
                growth_6m = _decimal(funding.get("growth_6m_pct"))
                item = {
                    "institution_id": institution_id,
                    "institution": funding.get("institution") or rate.row.institution,
                    "rate": str(rate.rate),
                    "rate_basis": rate.basis,
                    "rate_product": rate.row.product,
                    "rate_product_id": rate.row.product_id,
                    "rate_is_special_sale": rate.row.is_special_sale,
                    "rate_source_effective_at": rate.row.source_effective_at,
                    "balance_million_krw": funding.get("balance_million_krw"),
                    "growth_6m_pct": funding.get("growth_6m_pct"),
                    "growth_12m_pct": funding.get("growth_12m_pct"),
                    "growth_6m_percentile": funding.get("growth_6m_percentile"),
                    "balance_percentile": funding.get("balance_percentile"),
                    "region_sido": rate.row.region_sido,
                    "region_sigungu": rate.row.region_sigungu,
                    "geo_basis": rate.row.geo_basis,
                }
                if growth_6m is None:
                    unavailable_growth += 1
                else:
                    all_joined.append(item)

            rate_values = [_decimal(item["rate"]) for item in all_joined]
            growth_values = [_decimal(item["growth_6m_pct"]) for item in all_joined]
            valid_rates = [value for value in rate_values if value is not None]
            valid_growth = [value for value in growth_values if value is not None]
            terms[str(term)] = {
                "term_months": term,
                "points": all_joined,
                "point_count": len(all_joined),
                "missing_exact_6m_count": unavailable_growth,
                "rate_median": _text(_median(valid_rates)),
                "growth_6m_median": _text(_median(valid_growth)),
            }

        sectors[sector] = {
            "label": position.get("label"),
            "funding_analysis_month": position.get("analysis_month"),
            "funding_freshness": position.get("freshness"),
            "terms": terms,
        }

    return {
        "version": MATRIX_VERSION,
        "available": any(
            term["point_count"] > 0
            for sector in sectors.values()
            for term in sector["terms"].values()
        ),
        "sectors": sectors,
        "contract": {
            "x_axis": "current_strategy_comparison_rate",
            "rate_aggregation": RATE_AGGREGATION,
            "rate_policy": (
                "source_max_then_nh_ejoy_composition_then_collected_base"
            ),
            "special_sale_policy": SPECIAL_SALE_POLICY,
            "y_axis": "exact_6m_funding_growth",
            "supporting_growth": "exact_12m_funding_growth",
            "bubble_size": "funding_balance_million_krw",
            "mixed_sector_matrix": False,
            "missing_growth_is_zero": False,
            "relation_semantics": RELATION_SEMANTICS,
        },
    }
