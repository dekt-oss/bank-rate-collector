from decimal import Decimal
from types import SimpleNamespace

from rate_monitor.services.institution_funding_position_service import _compact_rows


def test_direct_peer_decimals_are_json_safe_strings() -> None:
    rows = [
        {
            "institution_id": "nh-a",
            "balance": "1000.000000",
            "sector_balance_percentile": "75",
            "change_6m_pct": "0.08",
            "sector_growth_6m_percentile": "80",
            "change_12m_pct": "0.10",
            "sector_growth_12m_percentile": "70",
            "sector_median_growth_6m": "0.03",
            "relative_growth_6m_vs_peer_median": "0.05",
        }
    ]
    direct = SimpleNamespace(
        scope="sido",
        peer_ids=tuple(f"p{i}" for i in range(16)),
        peer_median_growth_6m=Decimal("0.025"),
        relative_growth_6m_vs_direct_peer=Decimal("0.055"),
        shortfall=False,
    )

    compact = _compact_rows(rows, {"nh-a": "가나다농협"}, {"nh-a": direct})[0]

    assert compact["direct_peer_count"] == 16
    assert compact["direct_peer_median_growth_6m"] == "0.025"
    assert compact["relative_growth_6m_vs_direct_peer"] == "0.055"
    assert compact["direct_peer_shortfall"] is False
