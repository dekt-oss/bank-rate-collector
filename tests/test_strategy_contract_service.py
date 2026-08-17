import sqlite3
from copy import deepcopy
from pathlib import Path

import pytest

from rate_monitor.services.dashboard_service import DashboardBuildError
from rate_monitor.services.strategy_contract_service import (
    augment_strategy_table,
    slice_strategy_table,
    strategy_universe_metadata,
)
from tests.strategy_output_helper import built_strategy_html


def _identity_db(path: Path) -> Path:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE collection_runs (id TEXT PRIMARY KEY, source_id TEXT NOT NULL);
            CREATE TABLE institutions (
                id TEXT PRIMARY KEY, canonical_name TEXT NOT NULL
            );
            CREATE TABLE products (
                id TEXT PRIMARY KEY, institution_id TEXT NOT NULL,
                name TEXT NOT NULL, product_type TEXT NOT NULL
            );
            CREATE TABLE product_variants (
                id TEXT PRIMARY KEY, product_id TEXT NOT NULL, term_months INTEGER,
                payment_method TEXT, interest_method TEXT, join_channel TEXT
            );
            CREATE TABLE rate_observations (
                id TEXT PRIMARY KEY, variant_id TEXT NOT NULL, run_id TEXT NOT NULL,
                valid_to TEXT, validation_status TEXT NOT NULL
            );
            INSERT INTO collection_runs VALUES ('r1', 'fsb');
            INSERT INTO institutions VALUES ('i1', '테스트저축은행');
            INSERT INTO products VALUES ('p-stable', 'i1', '테스트예금', 'term_deposit');
            INSERT INTO product_variants VALUES (
                'v1', 'p-stable', 12, 'installment', 'simple', 'online'
            );
            INSERT INTO rate_observations VALUES ('o1', 'v1', 'r1', NULL, 'valid');
            """
        )
        conn.commit()
    finally:
        conn.close()
    return path


def _table() -> dict:
    return {
        "columns": [
            "sector",
            "source_id",
            "institution",
            "product",
            "product_type",
            "term_months",
            "payment_method",
            "interest_method",
            "join_channel",
        ],
        "lookups": {
            "sector": ["savings_bank"],
            "source_id": ["fsb"],
            "institution": ["테스트저축은행"],
            "product": ["테스트예금"],
            "product_type": ["term_deposit"],
            "payment_method": ["installment"],
            "interest_method": ["simple"],
            "join_channel": ["online"],
        },
        "rows": [[0, 0, 0, 0, 0, 12, 0, 0, 0]],
    }


def _universe_table() -> dict:
    return {
        "columns": [
            "sector",
            "product_type",
            "term_months",
            "max_rate",
            "geo_basis",
            "rate_scope",
            "availability_scope",
            "source_effective_at",
        ],
        "lookups": {
            "sector": ["savings_bank", "cu", "kfcc", "nh_local"],
            "product_type": ["term_deposit", "installment_savings"],
            "geo_basis": ["head_office", "source_query_region", "outlet_address"],
            "rate_scope": ["institution", "outlet"],
            "availability_scope": ["unknown", "local_members"],
            "source_effective_at": ["2026-08-16", "2026-08-17"],
        },
        "rows": [
            [0, 0, 12, 3.6, 0, 0, 0, 0],
            [1, 0, 12, 4.0, 1, 0, 0, 1],
            [1, 0, 24, 3.8, 1, 0, 0, 1],
            [2, 0, 12, None, 2, 0, 1, 1],
            [3, 0, 12, None, 2, 1, 0, 1],
            [0, 0, 60, 9.9, 0, 0, 0, 1],
            [1, 1, 12, 9.9, 1, 0, 0, 1],
        ],
    }


def test_strategy_build_uses_stable_id_and_reference_date() -> None:
    html = built_strategy_html()

    assert 'productId:look("product_id"' in html
    assert 'const key=`${r.sector}\\0${r.productId}\\0${term}`;' in html
    assert "const key=r.productId?" not in html
    assert "tagLatest:new Map" in html
    assert "latestAt:latest.get(code)||null" in html
    assert '원천 기준일 ${formatDate(topPref.latestAt)}' in html
    assert "최신 공시기준일" not in html


def test_strategy_build_contains_structural_inflow_engine_contract() -> None:
    html = built_strategy_html()

    assert (
        'const INFLOW_MODEL=data.strategy?.inflow_prediction||'
        '{"version":"inflow-structural-v1"' in html
    )
    assert '"calibration_status":"uncalibrated"' in html
    assert '"coefficient_provenance":"uncalibrated_stress_assumptions"' in html
    assert '"cost_metric":"simple_surface_interest_total_delta"' in html
    assert "수신금액 예측 엔진" in html
    assert 'id="baseline-new"' in html
    assert 'id="maturity-amount"' in html
    assert 'id="rollover-rate"' in html
    assert "function runInflowScenario" in html
    assert "function predictInflow" in html
    assert "relativeChange=proposedGap-currentGap" in html
    assert "Math.exp(logEffect)" in html
    assert "Math.abs(rateSteps)<=1e-12?p0:logistic(rollLogit)" in html
    assert "baselineCost=baselineTotal*ownRate/100*termFactor" in html
    assert "predictedCost=total*proposed/100*termFactor" in html
    assert "cost=predictedCost-baselineCost" in html
    assert "FTP 미반영" in html
    assert "내부 수신실적 계수가 아직 미보정" in html
    assert 'id="baseline"' not in html
    assert 'id="sensitivity"' not in html
    assert "가정 기반 예상 월 수신액" not in html


def test_strategy_slice_publishes_only_evidence_backed_max_rate_sectors() -> None:
    table = _universe_table()

    sliced = slice_strategy_table(table)

    assert sliced["columns"] is table["columns"]
    assert sliced["lookups"] is table["lookups"]
    assert sliced["rows"] == table["rows"][:3]
    assert sliced["strategy_universe"]["published_sectors"] == ["savings_bank", "cu", "nh_local"]
    assert sliced["strategy_universe"]["base_rate_fallback"] is False


def test_strategy_universe_records_coverage_and_block_reasons() -> None:
    universe = strategy_universe_metadata(_universe_table())
    sectors = universe["sectors"]

    assert universe["metric_basis"] == "max_rate"
    assert sectors["savings_bank"]["state"] == "supported"
    assert sectors["savings_bank"]["coverage_ratio"] == 1.0
    assert sectors["cu"]["state"] == "supported"
    assert sectors["cu"]["coverage_ratio"] == 1.0
    assert sectors["cu"]["latest_source_effective_at"] == "2026-08-17"
    assert sectors["cu"]["geo_basis"] == ["source_query_region"]
    assert sectors["cu"]["terms"]["6"]["rows"] == 0
    assert sectors["cu"]["terms"]["6"]["selectable"] is False

    assert sectors["kfcc"]["state"] == "unsupported"
    assert sectors["kfcc"]["max_rate_rows"] == 0
    assert sectors["kfcc"]["selectable"] is False
    assert "gmgo_cd" in sectors["kfcc"]["blocked_reason"]

    assert sectors["nh_local"]["state"] == "no_max_rate_data"
    assert sectors["nh_local"]["max_rate_capability"] is True
    assert sectors["nh_local"]["rate_scope"] == ["outlet"]
    assert sectors["nh_local"]["geo_basis"] == ["outlet_address"]
    assert sectors["nh_local"]["selectable"] is False
    assert sectors["nh_local"]["blocked_reason"] is None
    assert sectors["nh_local"]["evidence"] == (
        "official_ejoy_same_brc_product_term_interval_internet_variant"
    )


def test_strategy_nh_local_publishes_only_evidence_backed_max_rows() -> None:
    table = deepcopy(_universe_table())
    table["rows"][4][3] = 4.15
    table["rows"].append([3, 0, 24, None, 2, 1, 0, 1])

    sliced = slice_strategy_table(table)
    nh_meta = sliced["strategy_universe"]["sectors"]["nh_local"]

    assert nh_meta["state"] == "supported"
    assert nh_meta["selectable"] is True
    assert nh_meta["max_rate_rows"] == 1
    assert nh_meta["rows"] == 2
    assert nh_meta["coverage_ratio"] == 0.5
    assert table["rows"][4] in sliced["rows"]
    assert table["rows"][-1] not in sliced["rows"]
    assert table["rows"][3] not in sliced["rows"]  # KFCC remains blocked


def test_strategy_table_adds_compressed_stable_product_id(tmp_path: Path) -> None:
    db = _identity_db(tmp_path / "identity.sqlite3")
    table, stats = augment_strategy_table(db, _table())

    assert table["columns"][-1] == "product_id"
    assert table["lookups"]["product_id"] == ["p-stable"]
    assert table["rows"][0][-1] == 0
    assert stats == {"matched": 1, "unmatched": 0}

    conn = sqlite3.connect(db)
    try:
        assert conn.execute("SELECT COUNT(*) FROM rate_observations").fetchone()[0] == 1
    finally:
        conn.close()


def test_strategy_table_accepts_pretransported_product_id_without_rejoin(tmp_path: Path) -> None:
    table = {
        "columns": ["sector", "product_id"],
        "lookups": {
            "sector": ["savings_bank"],
            "product_id": ["p-direct"],
        },
        "rows": [[0, 0]],
    }

    augmented, stats = augment_strategy_table(tmp_path / "does-not-exist.sqlite3", table)

    assert augmented is table
    assert stats == {"matched": 1, "unmatched": 0}


def test_strategy_table_rejects_null_pretransported_product_id(tmp_path: Path) -> None:
    table = {
        "columns": ["sector", "product_id"],
        "lookups": {
            "sector": ["savings_bank"],
            "product_id": ["p-direct"],
        },
        "rows": [[0, 0], [0, None]],
    }

    with pytest.raises(DashboardBuildError, match="stable product_id.*1행"):
        augment_strategy_table(tmp_path / "does-not-exist.sqlite3", table)
