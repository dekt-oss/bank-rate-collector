from decimal import Decimal

import pytest

from rate_monitor.services.size_peer_current_eligibility import (
    SizePeerEligibilityEvidenceError,
    TwoAxisFinancialCandidate,
)
from rate_monitor.services.size_peer_similarity import (
    SIZE_PEER_RANKING_POLICY_ID,
    nearest_for_display,
    rank_size_peers,
)


def candidate(
    institution_id: str,
    name: str,
    funding: str,
    assets: str,
    *,
    sector: str = "savings_bank",
) -> TwoAxisFinancialCandidate:
    return TwoAxisFinancialCandidate(
        institution_id=institution_id,
        canonical_name=name,
        sector=sector,
        source_institution_key=f"source-{institution_id}",
        deposit_liabilities_total=Decimal(funding),
        total_assets=Decimal(assets),
    )


def test_ranking_uses_worst_axis_then_sum_gap_and_keeps_full_universe():
    rows = (
        candidate("own", "고려저축은행", "100", "100"),
        candidate("a", "A", "101", "101"),
        candidate("b", "B", "99", "102"),
        candidate("c", "C", "130", "100"),
    )

    result = rank_size_peers(
        rows,
        eligible_ids=("own", "a", "b", "c"),
        anchor_id="own",
        financial_as_of="2025-12",
        eligibility_as_of="2026-09-05",
        eligibility_mode="REMOTE",
    )

    assert result.policy_id == SIZE_PEER_RANKING_POLICY_ID
    assert result.eligible_count_including_anchor == 4
    assert result.ranked_count_excluding_anchor == 3
    assert [row.institution_id for row in result.rows] == ["a", "b", "c"]
    assert result.rows[0].worst_axis_gap == Decimal("0.01")
    assert result.rows[1].worst_axis_gap == Decimal("0.02")
    assert result.rows[2].worst_axis_gap == Decimal("0.3")


def test_ranking_has_no_hidden_cutoff_or_semantic_target_n():
    rows = [candidate("own", "Own", "100", "100")]
    rows.extend(
        candidate(f"p{i}", f"Peer {i:02d}", str(100 + i), str(100 + i * 2))
        for i in range(1, 31)
    )

    result = rank_size_peers(
        rows,
        eligible_ids=[row.institution_id for row in rows],
        anchor_id="own",
        financial_as_of="2025-12",
        eligibility_as_of="2026-09-05",
        eligibility_mode="REMOTE",
    )

    assert result.ranked_count_excluding_anchor == 30
    assert len(result.rows) == 30
    assert [row.rank for row in result.rows] == list(range(1, 31))
    assert len(nearest_for_display(result, limit=5)) == 5
    assert result.ranked_count_excluding_anchor == 30


def test_tie_breaker_is_sum_gap_then_name_then_id():
    rows = (
        candidate("own", "Own", "100", "100"),
        candidate("z", "Zulu", "110", "100"),
        candidate("b", "Beta", "100", "110"),
        candidate("a", "Alpha", "90", "100"),
    )

    result = rank_size_peers(
        rows,
        eligible_ids=("own", "z", "b", "a"),
        anchor_id="own",
        financial_as_of="2025-12",
        eligibility_as_of="2026-09-05",
        eligibility_mode="BRANCH_BUSAN",
    )

    assert [row.institution_id for row in result.rows] == ["a", "b", "z"]


def test_anchor_must_be_in_eligible_universe():
    rows = (
        candidate("own", "Own", "100", "100"),
        candidate("peer", "Peer", "101", "101"),
    )

    with pytest.raises(SizePeerEligibilityEvidenceError, match="anchor is absent"):
        rank_size_peers(
            rows,
            eligible_ids=("peer",),
            anchor_id="own",
            financial_as_of="2025-12",
            eligibility_as_of="2026-09-05",
            eligibility_mode="REMOTE",
        )


def test_display_limit_is_positive():
    result = rank_size_peers(
        (
            candidate("own", "Own", "100", "100"),
            candidate("peer", "Peer", "101", "101"),
        ),
        eligible_ids=("own", "peer"),
        anchor_id="own",
        financial_as_of="2025-12",
        eligibility_as_of="2026-09-05",
        eligibility_mode="REMOTE",
    )

    with pytest.raises(ValueError, match="positive"):
        nearest_for_display(result, limit=0)
