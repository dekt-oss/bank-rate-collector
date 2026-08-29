from decimal import Decimal
from pathlib import Path

from rate_monitor.services.institution_funding_read_model import InstitutionFundingReadRow
from rate_monitor.services.institution_funding_read_model_db import VERIFIED_IDENTITY_STATUSES
from rate_monitor.services import institution_funding_strategy_payload as payload_module


def test_verified_identity_statuses_cover_current_exact_sources() -> None:
    assert VERIFIED_IDENTITY_STATUSES == {
        "mapped_exact_fss_code",
        "mapped_exact_nh_brc_name",
        "mapped_exact_cu_ingno",
    }


def test_strategy_payload_reports_coverage_and_growth_availability(monkeypatch) -> None:
    rows = [
        InstitutionFundingReadRow(
            institution_id="a",
            sector="cu",
            analysis_month="2026-06",
            balance=Decimal("120"),
            balance_6m_ago=Decimal("100"),
            balance_12m_ago=Decimal("80"),
            change_6m_amount=Decimal("20"),
            change_6m_pct=Decimal("0.2"),
            change_12m_amount=Decimal("40"),
            change_12m_pct=Decimal("0.5"),
            sector_balance_percentile=Decimal("75"),
            sector_growth_6m_percentile=Decimal("75"),
            sector_growth_12m_percentile=Decimal("75"),
            sector_median_growth_6m=Decimal("0.1"),
            relative_growth_6m_vs_peer_median=Decimal("0.1"),
        ),
        InstitutionFundingReadRow(
            institution_id="b",
            sector="cu",
            analysis_month="2026-06",
            balance=Decimal("100"),
            balance_6m_ago=None,
            balance_12m_ago=None,
            change_6m_amount=None,
            change_6m_pct=None,
            change_12m_amount=None,
            change_12m_pct=None,
            sector_balance_percentile=Decimal("25"),
            sector_growth_6m_percentile=None,
            sector_growth_12m_percentile=None,
            sector_median_growth_6m=Decimal("0.1"),
            relative_growth_6m_vs_peer_median=None,
        ),
    ]
    monkeypatch.setattr(
        payload_module,
        "build_institution_funding_read_model_from_db",
        lambda *args, **kwargs: rows,
    )

    payload = payload_module.build_institution_funding_strategy_payload(
        Path("unused.sqlite3"),
        sector="cu",
        analysis_month="2026-06",
        eligible_institutions=4,
    )

    assert payload["coverage"]["observed_institutions"] == 2
    assert payload["coverage"]["coverage_ratio"] == "0.5"
    assert payload["availability"]["growth_6m_institutions"] == 1
    assert payload["availability"]["growth_12m_institutions"] == 1
    assert payload["rows"][0]["change_6m_pct"] == "0.2"
