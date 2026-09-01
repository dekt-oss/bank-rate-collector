from decimal import Decimal

import pytest

from rate_monitor.services.institution_rate_reduction import (
    INSTITUTION_RATE_REDUCTION_POLICY_ID,
    InstitutionRateCandidate,
    reduce_institution_rates,
)


def _row(
    institution_id: str,
    product_id: str,
    rate: str,
    *,
    source_id: str = "fsb",
    special: bool = False,
    scope: str = "전국",
    match_key: str = "nationwide",
    channel: str = "online",
) -> InstitutionRateCandidate:
    return InstitutionRateCandidate(
        institution_id=institution_id,
        product_id=product_id,
        source_id=source_id,
        sector="savings_bank",
        product_type="term_deposit",
        term_months=12,
        join_channel=channel,
        availability_scope=scope,
        availability_match_key=match_key,
        special_offer_flag=special,
        rate_pct=Decimal(rate),
    )


def _reduce(rows, **kwargs):
    return reduce_institution_rates(
        rows,
        sector="savings_bank",
        product_type="term_deposit",
        term_months=12,
        availability_match_key="nationwide",
        join_channel="online",
        retreating_sources={"finlife_savings_bank"},
        **kwargs,
    )


def test_reduction_returns_one_institution_row_and_excludes_special_offer_by_default() -> None:
    rows = [
        _row("a", "p-low", "3.40"),
        _row("a", "p-core", "3.60"),
        _row("a", "p-special", "4.20", special=True),
        _row("b", "p-b", "3.50"),
    ]

    result = _reduce(rows)

    assert [row.institution_id for row in result] == ["a", "b"]
    assert result[0].representative_product_id == "p-core"
    assert result[0].rate_pct == Decimal("3.6000")
    assert result[0].availability_scope == "전국"
    assert result[0].availability_match_key == "nationwide"
    assert result[0].special_offer_flag is False
    assert result[0].policy_id == INSTITUTION_RATE_REDUCTION_POLICY_ID
    assert result[0].precedence_applied is True


def test_reduction_can_include_special_offer_explicitly() -> None:
    result = _reduce(
        [
            _row("a", "p-core", "3.60"),
            _row("a", "p-special", "4.20", special=True),
        ],
        include_special_offer=True,
    )

    assert result[0].representative_product_id == "p-special"
    assert result[0].rate_pct == Decimal("4.2000")
    assert result[0].special_offer_flag is True


def test_retreating_source_cannot_override_primary_source() -> None:
    result = _reduce(
        [
            _row("a", "fsb-product", "3.50", source_id="fsb"),
            _row(
                "a",
                "finlife-product",
                "4.50",
                source_id="finlife_savings_bank",
            ),
        ]
    )

    assert result[0].source_id == "fsb"
    assert result[0].rate_pct == Decimal("3.5000")


def test_retreating_source_is_retained_when_no_primary_row_exists() -> None:
    result = _reduce(
        [
            _row(
                "a",
                "finlife-only",
                "4.10",
                source_id="finlife_savings_bank",
            )
        ]
    )

    assert result[0].source_id == "finlife_savings_bank"
    assert result[0].rate_pct == Decimal("4.1000")


def test_tie_break_is_stable_product_id_ascending() -> None:
    result = _reduce(
        [
            _row("a", "p-z", "3.60"),
            _row("a", "p-a", "3.60"),
        ]
    )

    assert result[0].representative_product_id == "p-a"


def test_unknown_availability_match_key_fails_closed() -> None:
    with pytest.raises(ValueError, match="availability_match_key"):
        reduce_institution_rates(
            [_row("a", "p", "3.50")],
            sector="savings_bank",
            product_type="term_deposit",
            term_months=12,
            availability_match_key="미상",
            retreating_sources=set(),
        )


def test_same_raw_local_label_does_not_merge_different_match_keys() -> None:
    result = reduce_institution_rates(
        [
            _row("busan", "p-busan", "3.50", scope="지역금고", match_key="local:busan"),
            _row("seoul", "p-seoul", "4.60", scope="지역금고", match_key="local:seoul"),
        ],
        sector="savings_bank",
        product_type="term_deposit",
        term_months=12,
        availability_match_key="local:busan",
        join_channel="online",
        retreating_sources=set(),
    )

    assert [row.institution_id for row in result] == ["busan"]


def test_join_channel_is_a_hard_filter() -> None:
    result = _reduce(
        [
            _row("a", "online-national", "3.50"),
            _row("b", "branch-national", "4.50", channel="branch"),
        ]
    )

    assert [row.institution_id for row in result] == ["a"]
