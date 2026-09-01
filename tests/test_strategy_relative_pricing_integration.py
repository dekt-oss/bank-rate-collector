from pathlib import Path

from rate_monitor.services import strategy_service


def test_strategy_summary_adds_relative_pricing_without_replacing_existing_sections(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        strategy_service._base,
        "build_strategy_summary",
        lambda _db: {"existing_section": {"status": "preserved"}},
    )
    monkeypatch.setattr(strategy_service, "build_product_history", lambda _db: {})
    monkeypatch.setattr(
        strategy_service,
        "build_savings_trend_display_policy",
        lambda _history: {"status": "ok"},
    )
    monkeypatch.setattr(strategy_service, "build_market_funding_strategy", lambda _db: {})
    monkeypatch.setattr(strategy_service, "build_institution_funding_positions", lambda _db: [])
    monkeypatch.setattr(
        strategy_service,
        "build_rate_funding_matrix",
        lambda _db, *, funding_positions: {"funding_positions": funding_positions},
    )

    summary = strategy_service.build_strategy_summary(Path("unused.sqlite3"))

    assert summary["existing_section"] == {"status": "preserved"}
    assert summary["relative_pricing"]["status"] == "insufficient_data"
    assert summary["relative_pricing"]["reason"] == "availability_match_key_unresolved"
    assert summary["relative_pricing"]["peers"] == []
    assert summary["relative_pricing"]["pricing_peer_position"] is None
    assert summary["relative_pricing"]["factual_cost"] is None
