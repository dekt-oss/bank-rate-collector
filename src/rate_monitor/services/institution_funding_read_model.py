"""Derived institution-funding read model.

The canonical observation table remains the source of truth.  This module keeps
6M/12M growth and peer-relative metrics recomputable and deliberately refuses
nearest-month interpolation or missing-as-zero fallbacks.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable


@dataclass(frozen=True)
class FundingPoint:
    institution_id: str
    sector: str
    month: str
    balance: Decimal
    identity_status: str = "exact"
    quality_status: str = "usable_exact"


@dataclass(frozen=True)
class InstitutionFundingReadRow:
    institution_id: str
    sector: str
    analysis_month: str
    balance: Decimal
    balance_6m_ago: Decimal | None
    balance_12m_ago: Decimal | None
    change_6m_amount: Decimal | None
    change_6m_pct: Decimal | None
    change_12m_amount: Decimal | None
    change_12m_pct: Decimal | None
    sector_balance_percentile: Decimal
    sector_growth_6m_percentile: Decimal | None
    sector_growth_12m_percentile: Decimal | None
    sector_median_growth_6m: Decimal | None
    relative_growth_6m_vs_peer_median: Decimal | None


def _shift_month(month: str, delta: int) -> str:
    year, mon = (int(part) for part in month.split("-"))
    absolute = year * 12 + (mon - 1) + delta
    shifted_year, shifted_mon0 = divmod(absolute, 12)
    return f"{shifted_year:04d}-{shifted_mon0 + 1:02d}"


def _growth(current: Decimal, prior: Decimal | None) -> tuple[Decimal | None, Decimal | None]:
    if prior is None or prior <= 0:
        return None, None
    return current - prior, current / prior - Decimal(1)


def _percentile_rank(value: Decimal, population: list[Decimal]) -> Decimal:
    """Average-rank percentile where larger values receive larger percentiles."""
    below = sum(item < value for item in population)
    equal = sum(item == value for item in population)
    rank = Decimal(below) + Decimal(equal + 1) / Decimal(2)
    return rank / Decimal(len(population)) * Decimal(100)


def _median(values: list[Decimal]) -> Decimal:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / Decimal(2)


def build_institution_funding_read_model(
    points: Iterable[FundingPoint], *, sector: str, analysis_month: str
) -> list[InstitutionFundingReadRow]:
    """Build exact-month peer metrics for one sector and analysis month.

    Only ``usable_exact`` / exact-identity observations enter the ranking
    population.  Missing prior periods remain ``None`` and are not imputed.
    """
    usable = [
        point
        for point in points
        if point.sector == sector
        and point.identity_status == "exact"
        and point.quality_status == "usable_exact"
    ]
    by_key = {(point.institution_id, point.month): point.balance for point in usable}
    current = [point for point in usable if point.month == analysis_month]
    if not current:
        return []

    balance_population = [point.balance for point in current]
    month_6m = _shift_month(analysis_month, -6)
    month_12m = _shift_month(analysis_month, -12)

    interim: dict[str, dict[str, Decimal | None]] = {}
    growth_6m_population: list[Decimal] = []
    growth_12m_population: list[Decimal] = []

    for point in current:
        prior_6m = by_key.get((point.institution_id, month_6m))
        prior_12m = by_key.get((point.institution_id, month_12m))
        amount_6m, pct_6m = _growth(point.balance, prior_6m)
        amount_12m, pct_12m = _growth(point.balance, prior_12m)
        interim[point.institution_id] = {
            "prior_6m": prior_6m,
            "prior_12m": prior_12m,
            "amount_6m": amount_6m,
            "pct_6m": pct_6m,
            "amount_12m": amount_12m,
            "pct_12m": pct_12m,
        }
        if pct_6m is not None:
            growth_6m_population.append(pct_6m)
        if pct_12m is not None:
            growth_12m_population.append(pct_12m)

    median_6m = _median(growth_6m_population) if growth_6m_population else None
    rows: list[InstitutionFundingReadRow] = []
    for point in current:
        metrics = interim[point.institution_id]
        pct_6m = metrics["pct_6m"]
        pct_12m = metrics["pct_12m"]
        rows.append(
            InstitutionFundingReadRow(
                institution_id=point.institution_id,
                sector=sector,
                analysis_month=analysis_month,
                balance=point.balance,
                balance_6m_ago=metrics["prior_6m"],
                balance_12m_ago=metrics["prior_12m"],
                change_6m_amount=metrics["amount_6m"],
                change_6m_pct=pct_6m,
                change_12m_amount=metrics["amount_12m"],
                change_12m_pct=pct_12m,
                sector_balance_percentile=_percentile_rank(point.balance, balance_population),
                sector_growth_6m_percentile=(
                    _percentile_rank(pct_6m, growth_6m_population)
                    if pct_6m is not None
                    else None
                ),
                sector_growth_12m_percentile=(
                    _percentile_rank(pct_12m, growth_12m_population)
                    if pct_12m is not None
                    else None
                ),
                sector_median_growth_6m=median_6m,
                relative_growth_6m_vs_peer_median=(
                    pct_6m - median_6m
                    if pct_6m is not None and median_6m is not None
                    else None
                ),
            )
        )
    return sorted(rows, key=lambda row: row.institution_id)
