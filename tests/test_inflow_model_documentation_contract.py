from __future__ import annotations

from pathlib import Path

from rate_monitor.services.inflow_prediction_service import SCENARIOS, predict_range

ROOT = Path(__file__).resolve().parents[1]
CALC_GUIDE = ROOT / "docs" / "specs" / "20260822-inflow-structural-v1-calculation-guide.md"
EVIDENCE = ROOT / "docs" / "specs" / "20260822-inflow-structural-v1-evidence-registry.md"


def test_calculation_guide_tracks_current_model_version_and_coefficients() -> None:
    text = CALC_GUIDE.read_text(encoding="utf-8")

    assert "`inflow-structural-v1`" in text
    assert "Calibration status: **uncalibrated**" in text
    for scenario in SCENARIOS:
        expected_row = (
            f"| {scenario.label if scenario.key == 'base' else scenario.label} "
        )
        assert expected_row in text
        assert f"| {scenario.new_money_log_change_per_10bp:.2f} |" in text
        assert f"| {scenario.rollover_log_odds_change_per_10bp:.2f} |" in text


def test_worked_example_numbers_are_generated_by_current_engine() -> None:
    text = CALC_GUIDE.read_text(encoding="utf-8")
    result = predict_range(
        baseline_new_money=100.0,
        maturity_amount=200.0,
        current_rollover_rate_pct=60.0,
        current_own_rate=3.50,
        proposed_rate=3.60,
        market_top10_rate=3.60,
        term_months=12,
    )

    for key in ("low", "base", "high"):
        scenario = result["scenarios"][key]
        assert f"{scenario['predicted_new_money']:.4f}" in text
        assert f"{scenario['predicted_rollover_rate_pct']:.4f}%" in text
        assert f"{scenario['predicted_rollover']:.4f}" in text
        assert f"{scenario['predicted_total']:.4f}" in text
        assert f"{scenario['incremental_total']:+.4f}" in text
        assert f"{scenario['surface_interest_delta']:+.4f}" in text

    low = result["predicted_total_range"]["min"]
    high = result["predicted_total_range"]["max"]
    assert f"{low:.4f}억원 ~ {high:.4f}억원" in text


def test_evidence_registry_keeps_assumption_and_source_boundaries_explicit() -> None:
    text = EVIDENCE.read_text(encoding="utf-8")

    assert "**C — unverified assumption**" in text
    assert "실제 은행실적으로 추정됐다 | **거짓 / 근거 없음**" in text
    assert "`deposit beta`" in text
    assert "Supports" in text
    assert "Does NOT support" in text

    expected_sources = (
        "https://www.federalreserve.gov/Pubs/feds/2013/201380/index.html",
        "https://www.federalreserve.gov/econres/feds/"
        "demand-estimation-and-consumer-welfare-in-the-banking-industry.htm",
        "https://www.federalreserve.gov/econres/notes/feds-notes/"
        "what-drives-the-substitution-between-bank-deposits-and-money-market-funds-20251106.html",
        "https://www.federalreserve.gov/data/sfos/march-2024-senior-financial-officer-survey.htm",
        "https://www.bis.org/bcbs/publ/wp47.pdf",
        "https://online.stat.psu.edu/stat501/Lesson13",
        "https://online.stat.psu.edu/stat504/Lesson06",
        "https://scikit-learn.org/stable/modules/generated/"
        "sklearn.model_selection.TimeSeriesSplit.html",
    )
    for source in expected_sources:
        assert source in text
