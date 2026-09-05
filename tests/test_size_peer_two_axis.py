from decimal import Decimal

import pytest

from rate_monitor.services.size_peer_two_axis import (
    AssetsAxisEvidence,
    FundingAxisEvidence,
    SizePeerTwoAxisError,
    build_two_axis_distribution,
    common_reporting_month_candidates,
)


def _funding(
    key: str,
    *,
    source_id: str = "data_go_savings_bank_funding",
    sector: str = "savings_bank",
    institution_id: str | None = "inst-1",
    canonical_name: str | None = "고려저축은행",
    identity_status: str = "mapped_exact_fss_code",
    crno: str | None = "1801110015304",
    month: str = "2025-12",
    value: str = "1000",
) -> FundingAxisEvidence:
    return FundingAxisEvidence(
        source_id=source_id,
        sector=sector,
        source_institution_key=key,
        source_institution_name=canonical_name or "원천기관",
        source_crno=crno,
        institution_id=institution_id,
        canonical_name=canonical_name,
        identity_status=identity_status,
        source_effective_month=month,
        value=Decimal(value),
    )


def _assets(
    key: str,
    *,
    source_id: str = "data_go_savings_bank_funding",
    sector: str = "savings_bank",
    crno: str | None = "1801110015304",
    month: str = "2025-12",
    value: str = "1500",
) -> AssetsAxisEvidence:
    return AssetsAxisEvidence(
        source_id=source_id,
        sector=sector,
        source_institution_key=key,
        source_institution_name="고려저축은행",
        source_crno=crno,
        source_effective_month=month,
        value=Decimal(value),
    )


def test_common_reporting_month_candidates_use_exact_intersection_only() -> None:
    result = common_reporting_month_candidates(
        {
            "savings": ("2026-03", "2025-12", "2025-09", "2025-06"),
            "nh": ("2025-12", "2025-06", "2024-12"),
        },
        required_source_ids=("savings", "nh"),
    )
    assert result == ("2025-12", "2025-06")


def test_common_reporting_month_candidates_fail_closed_for_missing_source() -> None:
    assert (
        common_reporting_month_candidates(
            {"savings": ("2025-12",)},
            required_source_ids=("savings", "nh"),
        )
        == ()
    )


def test_two_axis_distribution_joins_only_exact_source_key_and_month() -> None:
    result = build_two_axis_distribution(
        [_funding("0010390", value="1900000")],
        [_assets("0010390", value="2100000")],
        source_effective_month="2025-12",
    )
    assert result.evidence_ready is True
    assert result.fatal_conflict_count == 0
    assert result.missing_reason_counts == ()
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.institution_id == "inst-1"
    assert candidate.deposit_liabilities_total == Decimal("1900000")
    assert candidate.total_assets == Decimal("2100000")
    assert candidate.source_effective_month == "2025-12"


def test_unmapped_funding_is_excluded_without_name_only_fallback() -> None:
    result = build_two_axis_distribution(
        [
            _funding(
                "0010390",
                institution_id=None,
                canonical_name=None,
                identity_status="unmapped_no_exact_cross_source_code",
            )
        ],
        [_assets("0010390")],
        source_effective_month="2025-12",
    )
    assert result.candidates == ()
    assert result.missing_reason_counts == (("institution_identity_unmapped", 1),)
    assert result.fatal_conflict_count == 0


def test_missing_axis_is_reported_not_imputed_to_zero() -> None:
    result = build_two_axis_distribution(
        [_funding("0010390")],
        [],
        source_effective_month="2025-12",
    )
    assert result.candidates == ()
    assert result.missing_reason_counts == (("total_assets_missing", 1),)


def test_asset_without_funding_is_reported_separately() -> None:
    result = build_two_axis_distribution(
        [],
        [_assets("0010390")],
        source_effective_month="2025-12",
    )
    assert result.candidates == ()
    assert result.missing_reason_counts == (("funding_missing", 1),)


def test_crno_conflict_is_fatal_and_never_joins() -> None:
    result = build_two_axis_distribution(
        [_funding("0010390", crno="111")],
        [_assets("0010390", crno="222")],
        source_effective_month="2025-12",
    )
    assert result.candidates == ()
    assert result.missing_reason_counts == (("identity_crno_conflict", 1),)
    assert result.fatal_conflict_count == 1
    assert result.evidence_ready is False


def test_duplicate_source_key_fails_closed() -> None:
    with pytest.raises(SizePeerTwoAxisError, match="duplicate funding natural key"):
        build_two_axis_distribution(
            [_funding("0010390"), _funding("0010390")],
            [_assets("0010390")],
            source_effective_month="2025-12",
        )


def test_duplicate_canonical_institution_across_source_keys_fails_closed() -> None:
    with pytest.raises(SizePeerTwoAxisError, match="duplicate canonical institution"):
        build_two_axis_distribution(
            [
                _funding("001", institution_id="same", canonical_name="A"),
                _funding("002", institution_id="same", canonical_name="A"),
            ],
            [
                _assets("001", crno=None),
                _assets("002", crno=None),
            ],
            source_effective_month="2025-12",
        )


def test_point_month_mismatch_fails_closed() -> None:
    with pytest.raises(SizePeerTwoAxisError, match="funding point month mismatch"):
        build_two_axis_distribution(
            [_funding("0010390", month="2025-06")],
            [_assets("0010390", month="2025-12")],
            source_effective_month="2025-12",
        )
