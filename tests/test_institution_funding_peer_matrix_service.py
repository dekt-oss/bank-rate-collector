import sqlite3
from pathlib import Path

from rate_monitor.services import institution_funding_peer_matrix_service as matrix_service


def _seed_rate_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE collection_runs (id TEXT PRIMARY KEY, source_id TEXT);
            CREATE TABLE institutions (
                id TEXT PRIMARY KEY,
                canonical_name TEXT,
                normalized_name TEXT,
                sector TEXT,
                region_sido TEXT,
                region_sigungu TEXT,
                geo_basis TEXT
            );
            CREATE TABLE products (
                id TEXT PRIMARY KEY,
                institution_id TEXT,
                name TEXT,
                is_special_sale INTEGER,
                product_type TEXT,
                active INTEGER
            );
            CREATE TABLE outlets (
                id TEXT PRIMARY KEY,
                name TEXT,
                region_sido TEXT,
                region_sigungu TEXT,
                geo_basis TEXT
            );
            CREATE TABLE product_variants (
                id TEXT PRIMARY KEY,
                product_id TEXT,
                outlet_id TEXT,
                term_months INTEGER
            );
            CREATE TABLE rate_observations (
                id TEXT PRIMARY KEY,
                variant_id TEXT,
                last_run_id TEXT,
                valid_to TEXT,
                validation_status TEXT,
                base_rate TEXT,
                max_rate TEXT,
                raw_preference_text TEXT,
                source_effective_at TEXT
            );

            INSERT INTO collection_runs VALUES ('run-a', 'primary');
            INSERT INTO institutions VALUES
                ('sb-a', '가저축은행', '가저축은행', 'savings_bank', '부산', '중구', 'head_office'),
                ('sb-b', '나저축은행', '나저축은행', 'savings_bank', '부산', '동구', 'head_office');
            INSERT INTO products VALUES
                ('p-a1', 'sb-a', '정기예금A', 0, 'term_deposit', 1),
                ('p-a2', 'sb-a', '특판A', 1, 'term_deposit', 1),
                ('p-b1', 'sb-b', '정기예금B', 0, 'term_deposit', 1);
            INSERT INTO product_variants VALUES
                ('v-a1', 'p-a1', NULL, 12),
                ('v-a2', 'p-a2', NULL, 12),
                ('v-b1', 'p-b1', NULL, 12);
            INSERT INTO rate_observations VALUES
                ('o-a1', 'v-a1', 'run-a', NULL, 'valid', '3.1', '3.4', '', '2026-08-29'),
                ('o-a2', 'v-a2', 'run-a', NULL, 'valid', '3.6', NULL, '', '2026-08-30'),
                ('o-b1', 'v-b1', 'run-a', NULL, 'valid', '3.2', '3.3', '', '2026-08-28');
            """
        )
        conn.commit()
    finally:
        conn.close()


def _positions() -> dict:
    return {
        "available": True,
        "sectors": {
            "savings_bank": {
                "label": "저축은행",
                "analysis_month": "2026-03",
                "freshness": {
                    "months_old": 5,
                    "cadence_label": "분기 공시",
                    "next_reporting_month": "2026-06",
                },
                "rows": [
                    {
                        "institution_id": "sb-a",
                        "institution": "가저축은행",
                        "balance_million_krw": "100000",
                        "balance_percentile": "75",
                        "growth_6m_pct": "0.08",
                        "growth_12m_pct": "0.10",
                        "growth_6m_percentile": "80",
                    },
                    {
                        "institution_id": "sb-b",
                        "institution": "나저축은행",
                        "balance_million_krw": "90000",
                        "balance_percentile": "25",
                        "growth_6m_pct": None,
                        "growth_12m_pct": "0.03",
                        "growth_6m_percentile": None,
                    },
                ],
            }
        },
    }


def test_matrix_uses_strategy_rate_and_requires_exact_6m_growth(
    tmp_path: Path, monkeypatch
) -> None:
    db = tmp_path / "rates.sqlite3"
    _seed_rate_db(db)
    monkeypatch.setattr(matrix_service, "dedupe_sources", lambda: [])
    monkeypatch.setattr(
        matrix_service,
        "build_institution_funding_positions",
        lambda _path: _positions(),
    )

    result = matrix_service.build_institution_funding_peer_matrix(db)

    assert result["available"] is True
    term = result["sectors"]["savings_bank"]["terms"]["12"]
    assert term["point_count"] == 1
    assert term["missing_exact_6m_count"] == 1
    point = term["points"][0]
    assert point["institution_id"] == "sb-a"
    assert point["rate"] == "3.6"
    assert point["rate_basis"] == "collected_base_rate"
    assert point["rate_is_special_sale"] is True
    assert point["growth_6m_pct"] == "0.08"
    assert term["rate_median"] == "3.6"
    assert term["growth_6m_median"] == "0.08"
    assert result["contract"]["mixed_sector_matrix"] is False
    assert result["contract"]["missing_growth_is_zero"] is False
    assert result["contract"]["relation_semantics"] == (
        "descriptive_association_not_causal_effect"
    )


def test_source_max_beats_base_fallback_for_same_institution_product(
    tmp_path: Path, monkeypatch
) -> None:
    db = tmp_path / "rates.sqlite3"
    _seed_rate_db(db)
    monkeypatch.setattr(matrix_service, "dedupe_sources", lambda: [])
    rows = matrix_service._load_rate_rows(db)
    rates = matrix_service._institution_term_rates(matrix_service._strategy_rates(rows))

    selected = rates[("sb-a", 12)]
    assert selected.rate == matrix_service.Decimal("3.6")
    assert selected.row.product == "특판A"
