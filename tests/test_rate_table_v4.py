"""통합 비교 데이터 계층 (v4 §10.4·§10.6·§10.7, PR 7).

화면이 요구하는 칸을 표가 실제로 싣는지, 그러면서 **크기가 안 터지는지**를
본다. 우대조건 원문을 행마다 그대로 실으면 7.5 MB가 되고, 그건 조회 화면을
못 쓰게 만든다.
"""

import json
import sqlite3
from pathlib import Path

import pytest

from rate_monitor.services.dashboard_service import (
    TABLE_COLUMNS,
    build_benchmarks,
    build_rate_table,
    build_summary,
    latest_run_ids,
)
from tests.test_kfcc_collection import run_collect


@pytest.fixture()
def db(tmp_path: Path, factory) -> Path:
    run_collect(factory, tmp_path / "raw")
    return tmp_path / "kfcc.sqlite3"


@pytest.fixture()
def factory(tmp_path: Path):
    from rate_monitor.db import models as m
    from rate_monitor.db.session import create_db_engine, make_session_factory

    engine = create_db_engine(tmp_path / "kfcc.sqlite3")
    m.Base.metadata.create_all(engine)
    return make_session_factory(engine)


def _table(db: Path) -> dict:
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        return build_rate_table(conn, latest_run_ids(conn))
    finally:
        conn.close()


# ── 칸 ──────────────────────────────────────────────────────────────────


def test_the_table_carries_what_the_screen_needs(db: Path) -> None:
    """v4 §10.4가 표 행에 요구하는 칸."""
    table = _table(db)
    for column in ("outlet", "geo_basis", "rate_scope", "amount_max", "preference"):
        assert column in table["columns"], column


def test_amount_min_is_deliberately_absent(db: Path) -> None:
    """실측 135,384행 중 채워진 값이 0건이다.

    빈 칸을 화면에 만들면 "정보 없음"이 아니라 "0원부터"로 읽힌다.
    """
    assert "amount_min" not in TABLE_COLUMNS


def test_geo_basis_prefers_the_outlet(db: Path) -> None:
    """지역근거가 기관 것으로 덮이면 배지가 거짓말을 한다.

    새마을금고는 점포 주소로 지역을 잡으므로 `outlet_address`여야 한다.
    """
    table = _table(db)
    assert set(table["lookups"]["geo_basis"]) == {"outlet_address"}


# ── 크기 ────────────────────────────────────────────────────────────────


def test_preference_text_is_not_repeated_per_row(db: Path) -> None:
    """우대조건은 조회표로 나간다. 이게 이번 확장의 크기 전제다.

    발행 DB 실측: 원문 있는 관측 38,305건에 서로 다른 문장이 387가지.
    행마다 실으면 7.5 MB, 조회표로 빼면 0.08 MB다.
    """
    table = _table(db)
    lookup = table["lookups"]["preference"]
    index = table["columns"].index("preference")
    used = [row[index] for row in table["rows"]]

    # 조회표의 색인이 들어가야 한다. 원문이 행에 그대로 있으면 안 된다.
    assert all(isinstance(v, int) for v in used)
    # 서로 다른 문장 수가 행 수보다 훨씬 적어야 의미가 있다.
    assert len(lookup) < len(table["rows"])

    # 직렬화했을 때 원문이 조회표에서만 한 번씩 나오는가.
    payload = json.dumps(table, ensure_ascii=False)
    for text in lookup:
        if text and len(text) > 20:
            assert payload.count(text) == 1, f"원문이 여러 번 실렸다: {text[:30]}"
            break


# ── 참고카드 ────────────────────────────────────────────────────────────


def test_benchmarks_are_none_without_bank_data(db: Path) -> None:
    """새마을금고만 있는 DB에는 시중은행이 없다. 빈 카드를 지어내지 않는다."""
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        marks = build_benchmarks(conn, latest_run_ids(conn))
    finally:
        conn.close()
    assert marks["commercial_bank_12m"] is None
    # 기준금리는 v4 PR 6에서 채운다. 자리는 있고 값은 없다.
    assert marks["bok_base_rate"] is None


def test_summary_carries_the_benchmark_block(db: Path) -> None:
    """카드 셋. 시중은행과 2금융권을 **나눠** 싣는다 (v4 §4.1).

    합치면 전국 공시(은행)와 점포 기준(금고·농·축협)이 한 숫자에 섞여
    그 값이 무엇의 평균인지 말할 수 없게 된다.
    """
    summary = build_summary(db)
    assert "benchmarks" in summary
    assert set(summary["benchmarks"]) == {
        "bok_base_rate", "commercial_bank_12m", "second_tier_12m"
    }


def test_percentiles_pick_a_real_value_not_an_average() -> None:
    """보간하면 아무 은행도 주지 않는 금리가 화면에 뜬다."""
    from rate_monitor.services.dashboard_service import _percentile

    values = [2.0, 3.0]
    assert _percentile(values, 0.5) in values
    assert _percentile([], 0.5) is None


# ── 내보내기 ────────────────────────────────────────────────────────────


def test_every_table_column_has_a_csv_header() -> None:
    """표에 칸을 더하면 내보내기 머리글도 같이 늘려야 한다.

    2026-08-06에 실제로 걸렸다. §10.4의 다섯 칸을 더했더니 내보내기가
    `KeyError: 'outlet'`으로 죽었다 — 표와 CSV가 같은 목록을 두 곳에 적고
    있어서다. 다음에 칸을 더할 때 여기서 먼저 걸린다.
    """
    from rate_monitor.services.export_service import CSV_HEADERS

    missing = [c for c in TABLE_COLUMNS if c not in CSV_HEADERS]
    assert missing == [], f"CSV 머리글이 없는 칸: {missing}"


def test_exported_codes_are_readable_korean(db: Path, tmp_path: Path) -> None:
    """`outlet_address`가 아니라 「점포 주소」로 나가야 사람이 읽는다."""
    from rate_monitor.services.export_service import export_dataset

    written = export_dataset(db, tmp_path / "out", formats=("csv",))
    text = written[0].read_text(encoding="utf-8-sig")
    assert "지역근거" in text and "금리적용범위" in text
    assert "점포 주소" in text
    assert "outlet_address" not in text
