import sqlite3
from pathlib import Path

import pytest

from rate_monitor.services.dashboard_service import DashboardBuildError
from rate_monitor.services.strategy_contract_service import (
    augment_strategy_table,
    slice_strategy_table,
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


def test_strategy_build_uses_stable_id_and_reference_date() -> None:
    html = built_strategy_html()

    assert 'productId:look("product_id"' in html
    assert 'const key=`${r.productId}\\0${term}`;' in html
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


def test_strategy_slice_keeps_only_frozen_universe_without_transforming_rows() -> None:
    table = {
        "columns": ["sector", "product_type", "term_months"],
        "lookups": {
            "sector": ["savings_bank", "credit_union"],
            "product_type": ["term_deposit", "installment_savings"],
        },
        "rows": [
            [0, 0, 6],
            [0, 0, 12],
            [0, 0, 24],
            [0, 0, 36],
            [0, 0, 60],
            [1, 0, 12],
            [0, 1, 12],
        ],
    }

    sliced = slice_strategy_table(table)

    assert sliced["columns"] is table["columns"]
    assert sliced["lookups"] is table["lookups"]
    assert sliced["rows"] == table["rows"][:4]


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
