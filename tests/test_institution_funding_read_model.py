from decimal import Decimal

import pytest

from rate_monitor.services.institution_funding_read_model import (
    FundingPoint,
    build_institution_funding_read_model,
)


def point(institution_id: str, month: str, balance: str, **kwargs: str) -> FundingPoint:
    return FundingPoint(
        institution_id=institution_id,
        sector="credit_union",
        month=month,
        balance=Decimal(balance),
        **kwargs,
    )


def test_builds_exact_6m_12m_growth_and_peer_metrics() -> None:
    rows = build_institution_funding_read_model(
        [
            point("a", "2025-06", "80"),
            point("a", "2025-12", "100"),
            point("a", "2026-06", "120"),
            point("b", "2025-06", "100"),
            point("b", "2025-12", "100"),
            point("b", "2026-06", "100"),
        ],
        sector="credit_union",
        analysis_month="2026-06",
    )

    a, b = rows
    assert a.change_6m_amount == Decimal("20")
    assert a.change_6m_pct == Decimal("0.2")
    assert a.change_12m_pct == Decimal("0.5")
    assert a.sector_median_growth_6m == Decimal("0.1")
    assert a.relative_growth_6m_vs_peer_median == Decimal("0.1")
    assert a.sector_balance_percentile == Decimal("75")
    assert a.sector_growth_6m_percentile == Decimal("75")
    assert b.sector_balance_percentile == Decimal("25")
    assert b.sector_growth_6m_percentile == Decimal("25")


def test_missing_exact_prior_month_is_not_interpolated_or_zero_filled() -> None:
    rows = build_institution_funding_read_model(
        [
            point("a", "2025-11", "90"),
            point("a", "2026-06", "100"),
        ],
        sector="credit_union",
        analysis_month="2026-06",
    )

    row = rows[0]
    assert row.balance_6m_ago is None
    assert row.change_6m_amount is None
    assert row.change_6m_pct is None
    assert row.sector_growth_6m_percentile is None


def test_non_exact_and_unusable_rows_do_not_enter_population() -> None:
    rows = build_institution_funding_read_model(
        [
            point("a", "2025-12", "100"),
            point("a", "2026-06", "110"),
            point("b", "2025-12", "100", identity_status="unmapped"),
            point("b", "2026-06", "999", identity_status="unmapped"),
            point("c", "2026-06", "888", quality_status="source_collision"),
        ],
        sector="credit_union",
        analysis_month="2026-06",
    )

    assert [row.institution_id for row in rows] == ["a"]
    assert rows[0].sector_balance_percentile == Decimal("50")


def test_zero_prior_balance_fails_closed() -> None:
    rows = build_institution_funding_read_model(
        [point("a", "2025-12", "0"), point("a", "2026-06", "100")],
        sector="credit_union",
        analysis_month="2026-06",
    )

    assert rows[0].change_6m_pct is None
    assert rows[0].change_6m_amount is None


def test_duplicate_usable_institution_month_fails_closed() -> None:
    with pytest.raises(ValueError, match="duplicate usable exact funding point"):
        build_institution_funding_read_model(
            [
                point("a", "2025-12", "100"),
                point("a", "2026-06", "110"),
                point("a", "2026-06", "111"),
            ],
            sector="credit_union",
            analysis_month="2026-06",
        )
