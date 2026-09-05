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
    assert result.rows[0].worst_axis_gap == Decimal("1.01").ln()
    assert result.rows[1].worst_axis_gap == Decimal("1.02").ln()
    assert result.rows[2].worst_axis_gap == Decimal("1.3").ln()


def test_log_ratio_distance_is_symmetric_for_reciprocal_sizes():
    rows = (
        candidate("own", "Own", "100", "100"),
        candidate("double", "Double", "200", "100"),
        candidate("half", "Half", "50", "100"),
    )

    result = rank_size_peers(
        rows,
        eligible_ids=("own", "double", "half"),
        anchor_id="own",
        financial_as_of="2025-12",
        eligibility_as_of="2026-09-05",
        eligibility_mode="REMOTE",
    )

    by_id = {row.institution_id: row for row in result.rows}
    expected = Decimal("2").ln()
    assert by_id["double"].funding_gap == expected
    assert by_id["half"].funding_gap == expected
    assert by_id["double"].worst_axis_gap == by_id["half"].worst_axis_gap


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


def test_exact_tie_breaker_uses_stable_institution_id():
    rows = (
        candidate("own", "Own", "100", "100"),
        candidate("z", "Alpha", "200", "100"),
        candidate("b", "Zulu", "100", "200"),
        candidate("a", "Beta", "50", "100"),
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


def test_eligible_candidate_must_exist_in_financial_universe():
    rows = (candidate("own", "Own", "100", "100"),)

    with pytest.raises(SizePeerEligibilityEvidenceError, match="absent from financial"):
        rank_size_peers(
            rows,
            eligible_ids=("own", "missing"),
            anchor_id="own",
            financial_as_of="2025-12",
            eligibility_as_of="2026-09-05",
            eligibility_mode="REMOTE",
        )


def test_nonpositive_financial_axis_fails_closed():
    rows = (
        candidate("own", "Own", "100", "100"),
        candidate("peer", "Peer", "0", "101"),
    )

    with pytest.raises(SizePeerEligibilityEvidenceError, match="positive"):
        rank_size_peers(
            rows,
            eligible_ids=("own", "peer"),
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
