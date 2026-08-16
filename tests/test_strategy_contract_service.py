import sqlite3
from pathlib import Path

from rate_monitor.services.site_service import DEFAULT_STRATEGY_TEMPLATE
from rate_monitor.services.strategy_contract_service import (
    adapt_strategy_template,
    augment_strategy_table,
)


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


def test_strategy_template_adapter_uses_stable_id_and_reference_date() -> None:
    html = adapt_strategy_template(DEFAULT_STRATEGY_TEMPLATE.read_text(encoding="utf-8"))
    assert 'productId:look("product_id"' in html
    assert 'const key=`${r.productId}\\0${term}`;' in html
    assert "const key=r.productId?" not in html
    assert "tagLatest:new Map" in html
    assert "latestAt:latest.get(code)||null" in html
    assert '원천 기준일 ${formatDate(topPref.latestAt)}' in html
    assert "최신 공시기준일" not in html


def test_strategy_template_adapter_replaces_manual_inflow_sensitivity_with_engine() -> None:
    html = adapt_strategy_template(DEFAULT_STRATEGY_TEMPLATE.read_text(encoding="utf-8"))

    assert 'const INFLOW_MODEL={"version":"inflow-structural-v1"' in html
    assert '"calibration_status":"uncalibrated"' in html
    assert '"coefficient_provenance":"uncalibrated_stress_assumptions"' in html
    assert "수신금액 예측 엔진" in html
    assert 'id="baseline-new"' in html
    assert 'id="maturity-amount"' in html
    assert 'id="rollover-rate"' in html
    assert "function runInflowScenario" in html
    assert "function predictInflow" in html
    assert "relativeChange=proposedGap-currentGap" in html
    assert "Math.exp(logEffect)" in html
    assert "logistic(rollLogit)" in html
    assert "FTP 미반영" in html
    assert "내부 수신실적 계수가 아직 미보정" in html
    assert 'id="baseline"' not in html
    assert 'id="sensitivity"' not in html
    assert "가정 기반 예상 월 수신액" not in html


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
