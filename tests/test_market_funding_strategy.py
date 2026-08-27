from rate_monitor.services.market_funding_strategy_service import (
    _growth_rankings,
    _pct_change,
    _prior_year,
    _quadrant,
)


def test_market_funding_yoy_helpers():
    assert _prior_year("2026-06") == "2025-06"
    assert _pct_change(110.0, 100.0) == 10.0
    assert _pct_change(10.0, 0.0) is None


def test_growth_ranking_is_within_sector_and_verified_only():
    rows = [
        {
            "institution_id": "a",
            "institution": "A",
            "source_institution_key": "1",
            "sector": "savings_bank",
            "month": "2026-06",
            "value_million_krw": 120.0,
            "identity_status": "mapped_exact_fss_code",
        },
        {
            "institution_id": "a",
            "institution": "A",
            "source_institution_key": "1",
            "sector": "savings_bank",
            "month": "2025-06",
            "value_million_krw": 100.0,
            "identity_status": "mapped_exact_fss_code",
        },
        {
            "institution_id": "b",
            "institution": "B",
            "source_institution_key": "2",
            "sector": "savings_bank",
            "month": "2026-06",
            "value_million_krw": 105.0,
            "identity_status": "mapped_exact_fss_code",
        },
        {
            "institution_id": "b",
            "institution": "B",
            "source_institution_key": "2",
            "sector": "savings_bank",
            "month": "2025-06",
            "value_million_krw": 100.0,
            "identity_status": "mapped_exact_fss_code",
        },
        {
            "institution_id": None,
            "institution": None,
            "source_institution_key": "3",
            "sector": "savings_bank",
            "month": "2026-06",
            "value_million_krw": 999.0,
            "identity_status": "unmapped_no_exact_cross_source_code",
        },
    ]
    rankings, coverage = _growth_rankings(rows)
    assert [item["institution"] for item in rankings["savings_bank"]] == ["A", "B"]
    assert rankings["savings_bank"][0]["yoy_pct"] == 20.0
    assert rankings["savings_bank"][0]["sector_percentile"] == 100.0
    assert rankings["savings_bank"][1]["sector_percentile"] == 0.0
    assert coverage["savings_bank"]["verified_identity_count"] == 2
    assert coverage["savings_bank"]["unverified_identity_count"] == 1


def test_quadrant_uses_rate_position_not_causal_claim():
    ranking = [
        {
            "institution_id": "a",
            "institution": "A",
            "sector": "savings_bank",
            "latest_month": "2026-06",
            "previous_month": "2025-06",
            "balance_trillion_krw": 1.2,
            "yoy_pct": 10.0,
            "rank": 1,
            "sector_count": 2,
            "sector_percentile": 100.0,
        },
        {
            "institution_id": "b",
            "institution": "B",
            "sector": "savings_bank",
            "latest_month": "2026-06",
            "previous_month": "2025-06",
            "balance_trillion_krw": 1.0,
            "yoy_pct": -5.0,
            "rank": 2,
            "sector_count": 2,
            "sector_percentile": 0.0,
        },
    ]
    rates = {
        "a": {"max_rate": 3.5},
        "b": {"max_rate": 3.0},
    }
    result = _quadrant(ranking, rates)
    assert result["available"] is True
    assert result["causality"] == "descriptive_position_only"
    items = {item["institution"]: item for item in result["items"]}
    assert items["A"]["quadrant"] == "고금리 · 성장"
    assert items["B"]["quadrant"] == "저금리 · 감소"
