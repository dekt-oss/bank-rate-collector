import sqlite3
from pathlib import Path

from rate_monitor.collectors.data_go_funding.aggregate_policy import (
    AGRI_COOP_CENTRAL_POPULATION_SCOPE,
)
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
                source_id TEXT,
                source_institution_key TEXT,
                population_scope TEXT,
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
            INSERT INTO source_entity_links VALUES
                ('cu', 'institution', 'cu-a', NULL),
                ('cu', 'institution', 'cu-b', NULL);
            INSERT INTO institution_funding_observations VALUES
                (
                    'cu-a', 'cu_disclosure', 'cu-a-key', 'credit_unions_source_reported',
                    'cu', '2026-06', 'mapped_exact_cu_ingno',
                    'deposit_liabilities_total', NULL
                ),
                (
                    NULL, 'cu_disclosure', 'cu-b-key', 'credit_unions_source_reported',
                    'cu', '2026-06', 'unmapped_no_exact_cross_source_code',
                    'deposit_liabilities_total', NULL
                ),
                (
                    'cu-a', 'cu_disclosure', 'cu-a-key', 'credit_unions_source_reported',
                    'cu', '2026-09', 'mapped_exact_future_status',
                    'deposit_liabilities_total', NULL
                ),
                (
                    'cu-a', 'cu_disclosure', 'cu-a-key', 'credit_unions_source_reported',
                    'cu', '2026-12', 'mapped_exact_cu_ingno',
                    'other_future_metric', NULL
                );
            """
        )
        conn.commit()
    finally:
        conn.close()


def test_position_overview_uses_latest_month_and_official_cu_denominator(
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
    assert result["display_order"] == ["cu"]
    cu = result["sectors"]["cu"]
    assert cu["coverage"]["eligible_institutions"] == 2
    assert cu["rows"][0]["institution"] == "가나다신협"
    assert cu["rows"][0]["growth_12m_pct"] is None
    assert cu["freshness"]["cadence_label"] == "반기·정기공시"
    assert cu["freshness"]["next_reporting_month"] == "2026-12"
    contract = result["contract"]
    assert contract["metric_code"] == "deposit_liabilities_total"
    assert contract["coverage_quality_threshold"] is None
    assert contract["aggregate_equals_ecos"] is False
    assert contract["missing_history_is_zero"] is False
    assert contract["coverage_denominator"] == "sector-specific eligible institution population"
    assert contract["coverage_denominator_by_sector"]["cu"].startswith(
        "active official same-grain"
    )
    assert contract["coverage_denominator_by_sector"]["nh_local"].startswith(
        "same-month Data.go"
    )


def test_directory_denominator_counts_distinct_active_institutions(tmp_path: Path) -> None:
    db = tmp_path / "directory.sqlite3"
    conn = sqlite3.connect(db)
    try:
        conn.executescript(
            """
            CREATE TABLE source_entity_links (
                source_id TEXT,
                entity_type TEXT,
                entity_id TEXT,
                valid_to TEXT
            );
            INSERT INTO source_entity_links VALUES
                ('cu', 'institution', 'cu-a', NULL),
                ('cu', 'institution', 'cu-b', NULL),
                ('cu', 'institution', 'cu-b', '2026-01-01'),
                ('fsb', 'institution', 'sb-a', NULL),
                ('other', 'institution', 'x', NULL);
            """
        )
        assert position_service._directory_eligible_institutions(conn, "cu") == 2
        assert position_service._directory_eligible_institutions(conn, "savings_bank") == 1
        assert position_service._directory_eligible_institutions(conn, "nh_local") is None
    finally:
        conn.close()


def test_nh_denominator_uses_same_month_real_local_coop_keys(tmp_path: Path) -> None:
    db = tmp_path / "nh.sqlite3"
    conn = sqlite3.connect(db)
    try:
        conn.executescript(
            f"""
            CREATE TABLE institution_funding_observations (
                institution_id TEXT,
                source_id TEXT,
                source_institution_key TEXT,
                population_scope TEXT,
                sector TEXT,
                source_effective_month TEXT,
                identity_status TEXT,
                metric_code TEXT,
                valid_to TEXT
            );
            INSERT INTO institution_funding_observations VALUES
                (NULL, 'data_go_agri_coop_funding', '0010027121020',
                 'agri_coops_local_units_source_reported', 'nh_local', '2025-12',
                 'unmapped_no_exact_cross_source_code', 'deposit_liabilities_total', NULL),
                (NULL, 'data_go_agri_coop_funding', '0010027121021',
                 'agri_coops_local_units_source_reported', 'nh_local', '2025-12',
                 'unmapped_no_exact_cross_source_code', 'deposit_liabilities_total', NULL),
                (NULL, 'data_go_agri_coop_funding', '0010027121022',
                 '{AGRI_COOP_CENTRAL_POPULATION_SCOPE}', 'nh_local', '2025-12',
                 'unmapped_no_exact_cross_source_code', 'deposit_liabilities_total', NULL),
                (NULL, 'data_go_agri_coop_funding', '030801S',
                 'agri_coops_local_units_source_reported', 'nh_local', '2025-12',
                 'unmapped_no_exact_cross_source_code', 'deposit_liabilities_total', NULL),
                (NULL, 'data_go_agri_coop_funding', '0321301S',
                 'agri_coops_local_units_source_reported', 'nh_local', '2025-12',
                 'unmapped_no_exact_cross_source_code', 'deposit_liabilities_total', NULL),
                (NULL, 'data_go_agri_coop_funding', '0010027129999',
                 'agri_coops_local_units_source_reported', 'nh_local', '2025-06',
                 'unmapped_no_exact_cross_source_code', 'deposit_liabilities_total', NULL),
                (NULL, 'data_go_agri_coop_funding', '0010027128888',
                 'agri_coops_local_units_source_reported', 'nh_local', '2025-12',
                 'unmapped_no_exact_cross_source_code', 'other_metric', NULL);
            """
        )
        assert position_service._nh_funding_eligible_institutions(conn, "2025-12") == 2
    finally:
        conn.close()


def test_position_presentation_is_strategy_only_and_idempotent() -> None:
    html = '<html><head></head><body><div id="market-scope"></div></body></html>'
    rendered = inject_institution_funding_position(html)

    assert STYLE_MARKER in rendered
    assert SCRIPT_MARKER in rendered
    assert "기관 수신 포지션" in rendered
    assert "부분 관측" in rendered
    assert "부분 모집단" not in rendered
    assert "수신규모순" in rendered
    assert "6M 성장순" in rendered
    assert "Peer 대비순" in rendered
    assert "기관명 미확인" in rendered
    assert "백분위 · 상위" in rendered
    assert "수집 성공률과 다른 개념" in rendered
    assert "ECOS 업권 수신잔액과 합계 일치를 전제하지 않고" in rendered
    assert inject_institution_funding_position(rendered) == rendered
