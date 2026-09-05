from decimal import Decimal

import pytest

from rate_monitor.services.size_peer_current_eligibility import (
    EligibilityEvidenceFact,
    SizePeerEligibilityEvidenceError,
    TwoAxisFinancialCandidate,
    apply_current_eligibility,
    exclusion_reason_counts,
    relative_gap_distribution,
    threshold_counts,
)


def _financial(
    institution_id: str,
    sector: str,
    *,
    name: str | None = None,
    funding: str = "100",
    assets: str = "120",
) -> TwoAxisFinancialCandidate:
    return TwoAxisFinancialCandidate(
        institution_id=institution_id,
        canonical_name=name or institution_id,
        sector=sector,
        source_institution_key=f"key-{institution_id}",
        deposit_liabilities_total=Decimal(funding),
        total_assets=Decimal(assets),
    )


def test_current_eligibility_keeps_financial_and_eligibility_clocks_separate() -> None:
    result = apply_current_eligibility(
        [
            _financial("koryo", "savings_bank"),
            _financial("nh-remote", "nh_local"),
            _financial("nh-local", "nh_local"),
        ],
        [
            EligibilityEvidenceFact(
                institution_id="koryo",
                busan_districts=("동구",),
                locality_evidence_source_id="fsb-live-branch-plus-outlet",
            ),
            EligibilityEvidenceFact(
                institution_id="nh-remote",
                source_channels=("internet",),
                channel_evidence_source_id="nh-local-active-rate",
            ),
            EligibilityEvidenceFact(
                institution_id="nh-local",
                busan_districts=("해운대구",),
                locality_evidence_source_id="nh-local-active-outlet-rate",
            ),
        ],
        financial_as_of="2025-12",
        eligibility_as_of="2026-09-05",
        term_months=12,
    )
    assert result.financial_as_of == "2025-12"
    assert result.eligibility_as_of == "2026-09-05"
    assert result.remote.eligible_ids == ("koryo", "nh-remote")
    assert result.branch_busan.eligible_ids == ("koryo", "nh-local")


def test_missing_current_fact_does_not_exclude_savings_from_remote_policy() -> None:
    result = apply_current_eligibility(
        [_financial("savings", "savings_bank"), _financial("nh", "nh_local")],
        [],
        financial_as_of="2025-12",
        eligibility_as_of="2026-09-05",
        term_months=12,
    )
    assert result.remote.eligible_ids == ("savings",)
    assert result.branch_busan.eligible_ids == ()
    assert result.missing_fact_count == 2
    assert exclusion_reason_counts(result.remote) == {
        "remote_eligibility_unverified": 1
    }


def test_relative_gap_uses_worst_axis_then_sum_without_selecting_threshold() -> None:
    rows = relative_gap_distribution(
        [
            _financial("anchor", "savings_bank", funding="100", assets="100"),
            _financial("balanced", "nh_local", funding="103", assets="104"),
            _financial("one-axis", "nh_local", funding="100", assets="105"),
        ],
        eligible_ids=("anchor", "balanced", "one-axis"),
        anchor_id="anchor",
    )
    assert [row.institution_id for row in rows] == ["balanced", "one-axis"]
    assert rows[0].worst_axis_gap == Decimal("0.04")
    assert rows[1].worst_axis_gap == Decimal("0.05")
    assert threshold_counts(
        rows,
        thresholds=(Decimal("0.04"), Decimal("0.05")),
    ) == {"0.04": 1, "0.05": 2}


def test_eligible_id_missing_from_financial_distribution_fails_closed() -> None:
    with pytest.raises(SizePeerEligibilityEvidenceError, match="eligible institution absent"):
        relative_gap_distribution(
            [_financial("anchor", "savings_bank")],
            eligible_ids=("anchor", "missing"),
            anchor_id="anchor",
        )


def test_nonpositive_financial_axis_is_not_accepted() -> None:
    with pytest.raises(SizePeerEligibilityEvidenceError, match="finite and positive"):
        apply_current_eligibility(
            [_financial("bad", "savings_bank", funding="0")],
            [],
            financial_as_of="2025-12",
            eligibility_as_of="2026-09-05",
            term_months=12,
        )
