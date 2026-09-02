from datetime import date
from decimal import Decimal

import pytest

from rate_monitor.services.relative_pricing_historical_service import (
    HISTORICAL_BLOCKED,
    HISTORICAL_READY,
    REASON_ANCHOR_REPRESENTATIVE_UNAVAILABLE,
    REASON_FUTURE_RATE,
    REASON_IDENTITY_UNPROVEN,
    REASON_SNAPSHOT_MISMATCH,
    REASON_SPECIAL_OFFER_UNPROVEN,
    HistoricalRateEvidenceRow,
    build_historical_relative_pricing_rates,
)

AS_OF = date(2026, 8, 31)
BUSAN_KEY = "fsb:term_deposit:area:YN_Busan"
BUSAN_SCOPE = "FSB 가입가능지역 부산"


def _row(
    *,
    institution_id: str = "anchor",
    product_id: str = "p-anchor",
    source_id: str = "fsb",
    rate: str = "3.70",
    snapshot_as_of: date = AS_OF,
    source_effective_at: date | None = date(2026, 8, 28),
    institution_identity_proven: bool = True,
    product_identity_proven: bool = True,
    special_offer_flag: bool | None = False,
    special_offer_evidence: str | None = "source-backed-test",
    match_key: str = BUSAN_KEY,
) -> HistoricalRateEvidenceRow:
    return HistoricalRateEvidenceRow(
        institution_id=institution_id,
        product_id=product_id,
        source_id=source_id,
        sector="savings_bank",
        product_type="term_deposit",
        term_months=12,
        join_channel="any",
        availability_scope=BUSAN_SCOPE,
        availability_match_key=match_key,
        rate_pct=Decimal(rate),
        snapshot_as_of=snapshot_as_of,
        source_effective_at=source_effective_at,
        institution_identity_proven=institution_identity_proven,
        product_identity_proven=product_identity_proven,
        special_offer_flag=special_offer_flag,
        special_offer_evidence=special_offer_evidence,
    )


def _build(rows, *, cohort=("anchor", "peer"), retreating_sources=()):
    return build_historical_relative_pricing_rates(
        rows,
        as_of=AS_OF,
        anchor_institution_id="anchor",
        cohort_institution_ids=cohort,
        sector="savings_bank",
        product_type="term_deposit",
        term_months=12,
        availability_match_key=BUSAN_KEY,
        retreating_sources=retreating_sources,
    )


def test_historical_special_offer_unknown_blocks_without_erasing_rate_coverage() -> None:
    result = _build(
        [
            _row(special_offer_flag=None, special_offer_evidence=None),
            _row(
                institution_id="peer",
                product_id="p-peer",
                rate="3.80",
                special_offer_flag=None,
                special_offer_evidence=None,
            ),
        ]
    )

    assert result.status == HISTORICAL_BLOCKED
    assert result.reason == REASON_SPECIAL_OFFER_UNPROVEN
    assert result.evidence_institution_ids == ("anchor", "peer")
    assert result.missing_rate_institution_ids == ()
    assert result.special_offer_unproven_product_ids == ("p-anchor", "p-peer")
    assert result.candidates == ()
    assert result.representatives == ()


def test_text_heuristic_does_not_promote_unknown_special_offer_to_normal() -> None:
    result = _build(
        [
            _row(
                special_offer_flag=None,
                special_offer_evidence="PRODUCT_NAME contains 한정",
            )
        ],
        cohort=("anchor",),
    )

    assert result.status == HISTORICAL_BLOCKED
    assert result.reason == REASON_SPECIAL_OFFER_UNPROVEN


def test_future_source_effective_date_blocks_snapshot() -> None:
    result = _build(
        [
            _row(
                source_effective_at=date(2026, 9, 1),
                special_offer_flag=False,
            )
        ],
        cohort=("anchor",),
    )

    assert result.status == HISTORICAL_BLOCKED
    assert result.reason == REASON_FUTURE_RATE
    assert result.future_rate_product_ids == ("p-anchor",)
    assert result.evidence_institution_ids == ()


def test_unproven_point_in_time_identity_blocks_snapshot() -> None:
    result = _build(
        [_row(product_identity_proven=False)],
        cohort=("anchor",),
    )

    assert result.status == HISTORICAL_BLOCKED
    assert result.reason == REASON_IDENTITY_UNPROVEN
    assert result.identity_unproven_product_ids == ("p-anchor",)


def test_mixed_snapshot_date_blocks_instead_of_carrying_row_across_time() -> None:
    result = _build(
        [_row(snapshot_as_of=date(2026, 9, 1))],
        cohort=("anchor",),
    )

    assert result.status == HISTORICAL_BLOCKED
    assert result.reason == REASON_SNAPSHOT_MISMATCH
    assert result.snapshot_mismatch_product_ids == ("p-anchor",)


def test_outside_cohort_rows_do_not_widen_official_historical_scope() -> None:
    result = _build(
        [
            _row(),
            _row(institution_id="peer", product_id="p-peer", rate="3.80"),
            _row(institution_id="outside", product_id="p-out", rate="9.99"),
        ]
    )

    assert result.status == HISTORICAL_READY
    assert {row.institution_id for row in result.representatives} == {"anchor", "peer"}
    assert all(row.institution_id != "outside" for row in result.candidates)


def test_cohort_row_with_different_match_key_is_hard_contract_error() -> None:
    with pytest.raises(ValueError, match="different availability_match_key"):
        _build(
            [_row(match_key="fsb:term_deposit:area:YN_Seoul")],
            cohort=("anchor",),
        )


def test_ready_snapshot_reuses_reducer_and_excludes_proven_special_offer() -> None:
    result = _build(
        [
            _row(product_id="anchor-normal", rate="3.70", special_offer_flag=False),
            _row(product_id="anchor-special", rate="4.50", special_offer_flag=True),
            _row(
                institution_id="peer",
                product_id="peer-normal",
                rate="3.80",
                special_offer_flag=False,
            ),
        ]
    )

    assert result.status == HISTORICAL_READY
    assert result.reason is None
    representatives = {row.institution_id: row for row in result.representatives}
    assert representatives["anchor"].representative_product_id == "anchor-normal"
    assert representatives["anchor"].rate_pct == Decimal("3.7000")
    assert representatives["anchor"].rate_as_of == AS_OF
    assert representatives["peer"].rate_pct == Decimal("3.8000")


def test_historical_source_precedence_keeps_primary_fsb_when_retreating_source_exists() -> None:
    result = _build(
        [
            _row(product_id="anchor-fsb", source_id="fsb", rate="3.70"),
            _row(
                product_id="anchor-finlife",
                source_id="finlife_savings_bank",
                rate="4.00",
            ),
            _row(institution_id="peer", product_id="peer-fsb", rate="3.80"),
        ],
        retreating_sources=("finlife_savings_bank",),
    )

    assert result.status == HISTORICAL_READY
    anchor = next(row for row in result.representatives if row.institution_id == "anchor")
    assert anchor.source_id == "fsb"
    assert anchor.rate_pct == Decimal("3.7000")
    assert anchor.precedence_applied is True


def test_anchor_with_only_proven_special_offer_fails_closed() -> None:
    result = _build(
        [
            _row(special_offer_flag=True),
            _row(
                institution_id="peer",
                product_id="p-peer",
                rate="3.80",
                special_offer_flag=False,
            ),
        ]
    )

    assert result.status == HISTORICAL_BLOCKED
    assert result.reason == REASON_ANCHOR_REPRESENTATIVE_UNAVAILABLE
    assert {row.institution_id for row in result.representatives} == {"peer"}


def test_historical_result_is_deterministic_across_input_order() -> None:
    rows = [
        _row(product_id="anchor-b", rate="3.70"),
        _row(product_id="anchor-a", rate="3.70"),
        _row(institution_id="peer", product_id="peer", rate="3.80"),
    ]

    forward = _build(rows)
    reverse = _build(list(reversed(rows)))

    assert forward.as_payload() == reverse.as_payload()
    assert forward.representatives == reverse.representatives
    anchor = next(row for row in forward.representatives if row.institution_id == "anchor")
    assert anchor.representative_product_id == "anchor-a"
