import sqlite3
from copy import deepcopy
from pathlib import Path

import pytest

from rate_monitor.services.dashboard_service import DashboardBuildError
from rate_monitor.services.strategy_contract_service import (
    STRATEGY_RATE_BASIS_COLLECTED_BASE,
    STRATEGY_RATE_BASIS_NH_EJOY,
    STRATEGY_RATE_BASIS_SOURCE_MAX,
    augment_strategy_table,
    slice_strategy_table,
)
from tests.strategy_output_helper import built_strategy_html

EJOY_NOTE = (
    "- 대상예금 <거치식> 정기예탁금, 복리식 정기예탁금 "
    "<적립식> 정기적금, 자유적립 적금, 자유로 부금 "
    "- 상품별 금리 + 우대금리 적용"
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


def _universe_table() -> dict:
    columns = [
        "sector",
        "institution",
        "outlet",
        "region",
        "district",
        "product",
        "product_id",
        "product_type",
        "term_months",
        "base_rate",
        "max_rate",
        "geo_basis",
        "rate_scope",
        "availability_scope",
        "source_id",
        "source_effective_at",
        "join_channel",
        "preference",
        "preference_status",
        "preference_tags",
    ]
    lookups = {
        "sector": ["savings_bank", "cu", "kfcc", "nh_local"],
        "institution": ["저축은행A", "신협A", "새마을금고A", "농협A"],
        "outlet": [None, "농협A"],
        "region": ["서울", "부산"],
        "district": [None, "강서구"],
        "product": [
            "저축예금",
            "신협예금",
            "Block예금",
            "정기예탁금",
            "e-joy 인터넷예금 우대금리",
        ],
        "product_id": ["p-save", "p-cu", "p-kfcc", "p-nh", "p-ejoy"],
        "product_type": ["term_deposit", "installment_savings"],
        "geo_basis": ["head_office", "source_query_region", "outlet_address"],
        "rate_scope": ["institution", "outlet"],
        "availability_scope": ["unknown", "local_members"],
        "source_id": ["fsb", "cu", "kfcc", "nh_local"],
        "source_effective_at": ["2026-08-16", "2026-08-17"],
        "join_channel": ["unknown", "internet"],
        "preference": ["", EJOY_NOTE],
        "preference_status": ["missing", "present"],
        "preference_tags": ["", "DIGITAL_CHANNEL"],
    }

    def ix(column: str, value):
        return lookups[column].index(value)

    def row(
        sector: str,
        institution: str,
        outlet,
        region: str,
        district,
        product: str,
        product_id: str,
        term: int,
        base: float,
        max_rate,
        geo_basis: str,
        rate_scope: str,
        availability: str,
        source_id: str,
        *,
        join_channel: str = "unknown",
        preference: str = "",
        preference_status: str = "missing",
        preference_tags: str = "",
        product_type: str = "term_deposit",
    ):
        return [
            ix("sector", sector),
            ix("institution", institution),
            ix("outlet", outlet),
            ix("region", region),
            ix("district", district),
            ix("product", product),
            ix("product_id", product_id),
            ix("product_type", product_type),
            term,
            base,
            max_rate,
            ix("geo_basis", geo_basis),
            ix("rate_scope", rate_scope),
            ix("availability_scope", availability),
            ix("source_id", source_id),
            ix("source_effective_at", "2026-08-17"),
            ix("join_channel", join_channel),
            ix("preference", preference),
            ix("preference_status", preference_status),
            ix("preference_tags", preference_tags),
        ]

    rows = [
        row(
            "savings_bank", "저축은행A", None, "서울", None, "저축예금", "p-save",
            12, 3.2, 3.6, "head_office", "institution", "unknown", "fsb",
        ),
        row(
            "cu", "신협A", None, "서울", None, "신협예금", "p-cu",
            12, 3.5, 4.0, "source_query_region", "institution", "unknown", "cu",
        ),
        row(
            "cu", "신협A", None, "서울", None, "신협예금", "p-cu",
            24, 3.4, 3.8, "source_query_region", "institution", "unknown", "cu",
        ),
        row(
            "kfcc", "새마을금고A", None, "부산", None, "Block예금", "p-kfcc",
            12, 4.1, None, "outlet_address", "institution", "local_members", "kfcc",
        ),
        row(
            "nh_local", "농협A", "농협A", "부산", "강서구", "정기예탁금", "p-nh",
            12, 3.6, None, "outlet_address", "outlet", "unknown", "nh_local",
        ),
    ]
    for term in (1, 12, 24, 36):
        rows.append(
            row(
                "nh_local", "농협A", "농협A", "부산", "강서구",
                "e-joy 인터넷예금 우대금리", "p-ejoy", term, 0.5, None,
                "outlet_address", "outlet", "unknown", "nh_local",
                join_channel="internet",
                preference=EJOY_NOTE,
                preference_status="present",
                preference_tags="DIGITAL_CHANNEL",
            )
        )
    rows.extend(
        [
            row(
                "savings_bank", "저축은행A", None, "서울", None, "저축예금", "p-save",
                60, 9.9, 9.9, "head_office", "institution", "unknown", "fsb",
            ),
            row(
                "cu", "신협A", None, "서울", None, "신협예금", "p-cu",
                12, 9.9, 9.9, "source_query_region", "institution", "unknown", "cu",
                product_type="installment_savings",
            ),
        ]
    )
    return {"columns": columns, "lookups": lookups, "rows": rows}


def _decode_row(table: dict, row: list) -> dict:
    out = {}
    for index, column in enumerate(table["columns"]):
        value = row[index]
        lookup = table.get("lookups", {}).get(column)
        out[column] = lookup[value] if lookup is not None and value is not None else value
    return out


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


def test_strategy_slice_uses_collected_best_rate_without_mutating_canonical() -> None:
    table = _universe_table()
    original = deepcopy(table)

    sliced = slice_strategy_table(table)
    decoded = [_decode_row(sliced, row) for row in sliced["rows"]]

    assert table == original
    assert "strategy_rate_basis" in sliced["columns"]
    assert sliced["strategy_universe"]["published_sectors"] == [
        "savings_bank", "cu", "kfcc", "nh_local"
    ]
    assert sliced["strategy_universe"]["base_rate_fallback"] is True
    assert sliced["strategy_universe"]["canonical_max_rate_unchanged"] is True

    by_sector = {item["sector"]: item for item in decoded if item["term_months"] == 12}
    assert by_sector["savings_bank"]["max_rate"] == 3.6
    assert by_sector["savings_bank"]["strategy_rate_basis"] == STRATEGY_RATE_BASIS_SOURCE_MAX
    assert by_sector["kfcc"]["max_rate"] == 4.1
    assert by_sector["kfcc"]["strategy_rate_basis"] == STRATEGY_RATE_BASIS_COLLECTED_BASE
    assert by_sector["nh_local"]["max_rate"] == 4.1
    assert by_sector["nh_local"]["join_channel"] == "internet"
    assert by_sector["nh_local"]["strategy_rate_basis"] == STRATEGY_RATE_BASIS_NH_EJOY


def test_strategy_universe_records_collected_best_rate_coverage() -> None:
    sliced = slice_strategy_table(_universe_table())
    universe = sliced["strategy_universe"]
    sectors = universe["sectors"]

    assert universe["metric_basis"] == "collected_best_rate"
    assert universe["metric_label"] == "수집 데이터 기준 최고금리"
    for sector in ("savings_bank", "cu", "kfcc", "nh_local"):
        assert sectors[sector]["state"] == "supported"
        assert sectors[sector]["strategy_rate_capability"] is True
        assert sectors[sector]["selectable"] is True
        assert sectors[sector]["blocked_reason"] is None

    assert sectors["cu"]["latest_source_effective_at"] == "2026-08-17"
    assert sectors["cu"]["geo_basis"] == ["source_query_region"]
    assert sectors["cu"]["terms"]["6"]["rows"] == 0
    assert sectors["cu"]["terms"]["6"]["selectable"] is False
    assert sectors["kfcc"]["rate_basis_counts"] == {"collected_base_rate": 1}
    assert sectors["nh_local"]["rate_basis_counts"] == {"nh_ejoy_base_plus_add": 1}


def test_strategy_nh_ejoy_linkage_fails_closed_on_ambiguous_location_key() -> None:
    table = _universe_table()
    ejoy_rows = [
        row for row in table["rows"]
        if _decode_row(table, row)["product"] == "e-joy 인터넷예금 우대금리"
    ]
    table["rows"].extend(deepcopy(ejoy_rows))

    sliced = slice_strategy_table(table)
    decoded = [
        _decode_row(sliced, row)
        for row in sliced["rows"]
        if _decode_row(sliced, row)["sector"] == "nh_local"
        and _decode_row(sliced, row)["product"] == "정기예탁금"
        and _decode_row(sliced, row)["term_months"] == 12
    ]

    assert len(decoded) == 1
    assert decoded[0]["max_rate"] == 3.6
    assert decoded[0]["strategy_rate_basis"] == STRATEGY_RATE_BASIS_COLLECTED_BASE


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
