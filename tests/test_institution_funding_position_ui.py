import sqlite3
from pathlib import Path

from rate_monitor.services import institution_funding_position_service as position_service
from rate_monitor.services.institution_funding_position_presentation import (
    SCRIPT_MARKER,
    STYLE_MARKER,
    inject_institution_funding_position,
)


def _seed_contract_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE institution_funding_observations (
                institution_id TEXT,
                sector TEXT,
                source_effective_month TEXT,
                identity_status TEXT,
                metric_code TEXT,
                valid_to TEXT
            );
            CREATE TABLE source_entity_links (
                source_id TEXT,
                entity_type TEXT,
                entity_id TEXT,
                valid_to TEXT
            );
            CREATE TABLE institutions (
                id TEXT PRIMARY KEY,
                canonical_name TEXT
            );
            INSERT INTO institutions VALUES ('cu-a', '가나다신협');
            INSERT INTO institution_funding_observations VALUES
                ('cu-a', 'cu', '2026-06', 'mapped_exact_cu_ingno', 'deposit_liabilities_total', NULL);
            INSERT INTO source_entity_links VALUES
                ('cu', 'institution', 'cu-a', NULL),
                ('cu', 'institution', 'cu-b', NULL);
            """
        )
        conn.commit()
    finally:
        conn.close()


def test_position_overview_uses_latest_month_and_active_identity_denominator(
    tmp_path: Path, monkeypatch
) -> None:
    db = tmp_path / "rates.sqlite3"
    _seed_contract_db(db)

    def fake_payload(
        _db_path: Path,
        *,
        sector: str,
        analysis_month: str,
        eligible_institutions: int | None,
    ) -> dict:
        assert sector == "cu"
        assert analysis_month == "2026-06"
        assert eligible_institutions == 2
        return {
            "sector": "cu",
            "analysis_month": "2026-06",
            "coverage": {
                "eligible_institutions": 2,
                "observed_institutions": 1,
                "coverage_ratio": "0.5",
                "status": "measured",
            },
            "availability": {
                "growth_6m_institutions": 1,
                "growth_12m_institutions": 0,
            },
            "rows": [
                {
                    "institution_id": "cu-a",
                    "balance": "120000.000000",
                    "sector_balance_percentile": "75",
                    "change_6m_pct": "0.1",
                    "sector_growth_6m_percentile": "80",
                    "change_12m_pct": None,
                    "sector_growth_12m_percentile": None,
                    "sector_median_growth_6m": "0.04",
                    "relative_growth_6m_vs_peer_median": "0.06",
                }
            ],
        }

    monkeypatch.setattr(
        position_service,
        "build_institution_funding_strategy_payload",
        fake_payload,
    )
    result = position_service.build_institution_funding_positions(db)

    assert result["available"] is True
    cu = result["sectors"]["cu"]
    assert cu["coverage"]["eligible_institutions"] == 2
    assert cu["rows"][0]["institution"] == "가나다신협"
    assert cu["rows"][0]["growth_12m_pct"] is None
    assert result["contract"]["aggregate_equals_ecos"] is False
    assert result["contract"]["missing_history_is_zero"] is False


def test_position_presentation_is_strategy_only_and_idempotent() -> None:
    html = '<html><head></head><body><div id="market-scope"></div></body></html>'
    rendered = inject_institution_funding_position(html)

    assert STYLE_MARKER in rendered
    assert SCRIPT_MARKER in rendered
    assert "기관 수신 포지션" in rendered
    assert "부분 모집단" in rendered
    assert "ECOS 업권 수신잔액과 합계 일치를 전제하지 않으며" in rendered
    assert inject_institution_funding_position(rendered) == rendered
