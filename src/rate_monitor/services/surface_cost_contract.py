"""Factual notional-based surface interest cost.

This contract is intentionally independent from inflow prediction. It answers
only: for a fixed notional and term, how much does simple surface interest
change when the quoted rate changes?
"""

from __future__ import annotations

from decimal import Decimal

from rate_monitor.services.public_structural_v2_market_position_service import normalize_rate

SURFACE_COST_CONTRACT_VERSION = "1"
STANDARD_NOTIONAL_KRW = Decimal("10000000000")  # 100억원


def _decimal(value: object, *, field: str) -> Decimal:
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError(f"{field} must be finite")
    return result


def surface_interest_delta(
    *,
    notional_krw: Decimal | int | str,
    current_rate_pct: Decimal | float | str,
    proposal_rate_pct: Decimal | float | str,
    term_months: int,
) -> Decimal:
    """Return simple-interest delta for a fixed notional.

    No inflow, rollover, forecast, or sensitivity coefficient is accepted.
    Rounding is intentionally left to the presentation layer.
    """

    notional = _decimal(notional_krw, field="notional_krw")
    if notional < 0:
        raise ValueError("notional_krw must be non-negative")
    months = int(term_months)
    if months <= 0:
        raise ValueError("term_months must be positive")

    current = normalize_rate(current_rate_pct)
    proposal = normalize_rate(proposal_rate_pct)
    return (
        notional
        * (proposal - current)
        / Decimal("100")
        * Decimal(months)
        / Decimal("12")
    )


def standardized_surface_interest_delta(
    *,
    current_rate_pct: Decimal | float | str,
    proposal_rate_pct: Decimal | float | str,
    term_months: int,
) -> Decimal:
    """Return the fixed 100억원 reference-notional cost delta."""

    return surface_interest_delta(
        notional_krw=STANDARD_NOTIONAL_KRW,
        current_rate_pct=current_rate_pct,
        proposal_rate_pct=proposal_rate_pct,
        term_months=term_months,
    )
