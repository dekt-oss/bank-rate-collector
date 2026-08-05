"""내보내기와 검증 — 실제 수집 경로로 만든 DB에 대고 확인한다.

fixture로 수집을 한 번 돌린 뒤 그 결과를 쓴다. 손으로 만든 DB에 대고
검사하면 실제로 쓰이는 형태와 어긋나도 통과한다.
"""

import asyncio
import csv
import json
import sqlite3
from pathlib import Path

import pytest

from rate_monitor.db import models as m
from rate_monitor.db.session import create_db_engine, make_session_factory
from rate_monitor.domain.schemas import CollectionRequest
from rate_monitor.services.collection_service import collect_source
from rate_monitor.services.dashboard_service import (
    TABLE_COLUMNS,
    build_rate_table,
    latest_run_ids,
)
from rate_monitor.services.export_service import CSV_HEADERS, export_dataset
from rate_monitor.services.validation_service import run_validations
from tests.test_kfcc_collection import FixtureAdapter


@pytest.fixture
def collected(tmp_path: Path) -> Path:
    db = tmp_path / "rates.sqlite3"
    engine = create_db_engine(db)
    m.Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    asyncio.run(
        collect_source(
            FixtureAdapter(),
            CollectionRequest(source_id="kfcc", regions=("중구",)),
            factory,
            raw_root=tmp_path / "raw",
        )
    )
    return db


# ── 금리표 ──────────────────────────────────────────────────────────────


def test_rate_table_is_compact_and_reversible(collected: Path) -> None:
    """조회표로 압축한 값이 원래 값으로 정확히 되돌아온다."""
    conn = sqlite3.connect(collected)
    try:
        table = build_rate_table(conn, latest_run_ids(conn))
        expected = conn.execute(
            "SELECT COUNT(*) FROM rate_observations WHERE validation_status != 'error'"
        ).fetchone()[0]
    finally:
        conn.close()

    assert table["columns"] == list(TABLE_COLUMNS)
    assert len(table["rows"]) == expected

    inst_col = table["columns"].index("institution")
    names = {table["lookups"]["institution"][r[inst_col]] for r in table["rows"]}
    assert names == {"대청"}

    # 금리는 색인이 아니라 실수여야 한다. 화면이 크기 비교를 한다.
    rate_col = table["columns"].index("base_rate")
    assert all(isinstance(r[rate_col], float) for r in table["rows"])


def test_rate_table_excludes_error_rows(collected: Path) -> None:
    conn = sqlite3.connect(collected)
    try:
        conn.execute(
            "UPDATE rate_observations SET validation_status = 'error'"
            " WHERE rowid IN (SELECT rowid FROM rate_observations LIMIT 5)"
        )
        conn.commit()
        table = build_rate_table(conn, latest_run_ids(conn))
        total = conn.execute("SELECT COUNT(*) FROM rate_observations").fetchone()[0]
    finally:
        conn.close()
    assert len(table["rows"]) == total - 5


# ── 내보내기 ────────────────────────────────────────────────────────────


def test_export_writes_csv_and_json(collected: Path, tmp_path: Path) -> None:
    out = tmp_path / "export"
    written = export_dataset(collected, out)
    assert len(written) == 2
    assert all(p.exists() and p.stat().st_size > 0 for p in written)


def test_csv_opens_cleanly_in_a_spreadsheet(collected: Path, tmp_path: Path) -> None:
    """BOM이 없으면 엑셀이 한글 머리글을 깨서 연다."""
    out = tmp_path / "export"
    csv_path = next(p for p in export_dataset(collected, out) if p.suffix == ".csv")

    raw = csv_path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")

    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    assert rows[0] == [CSV_HEADERS[c] for c in TABLE_COLUMNS]
    assert len(rows) - 1 == _observation_count(collected)


def test_export_translates_codes_for_humans(collected: Path, tmp_path: Path) -> None:
    """사람이 여는 파일에 kfcc·term_deposit 같은 내부 코드를 남기지 않는다."""
    out = tmp_path / "export"
    csv_path = next(p for p in export_dataset(collected, out) if p.suffix == ".csv")
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert {r["권역"] for r in rows} == {"새마을금고"}
    assert {r["상품유형"] for r in rows} <= {"예금", "적금"}
    assert {r["가입제한"] for r in rows} == {"지역금고"}
    # 수집원 식별자는 추적용이라 코드 그대로 둔다.
    assert {r["수집원"] for r in rows} == {"kfcc"}


def test_json_export_carries_every_column(collected: Path, tmp_path: Path) -> None:
    out = tmp_path / "export"
    json_path = next(p for p in export_dataset(collected, out) if p.suffix == ".json")
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["columns"] == list(TABLE_COLUMNS)
    assert payload["count"] == len(payload["records"])
    assert set(payload["records"][0]) == set(TABLE_COLUMNS)


# ── 검증 ────────────────────────────────────────────────────────────────


def test_validations_pass_on_a_clean_collection(collected: Path) -> None:
    checks = run_validations(collected)
    failed = [c.name for c in checks if not c.ok]
    assert failed == []


def test_validation_catches_a_fabricated_max_rate(collected: Path) -> None:
    """새마을금고 최고금리를 채우면 잡혀야 한다.

    참고 저장소가 base_rate로 max_rate를 메운 지점이다. 검사가 실제로
    실패할 수 있는지 확인한다 — 항상 참인 검사는 검사가 아니다.
    """
    conn = sqlite3.connect(collected)
    try:
        conn.execute(
            "UPDATE rate_observations SET max_rate = base_rate"
            " WHERE rowid = (SELECT MIN(rowid) FROM rate_observations)"
        )
        conn.commit()
    finally:
        conn.close()

    failed = [c for c in run_validations(collected) if not c.ok]
    assert [c.name for c in failed] == ["새마을금고 최고금리 비어 있음"]


def test_validation_catches_a_guessed_region_code(collected: Path) -> None:
    """화면 파라미터를 행정구역 공식 코드로 채우면 잡혀야 한다."""
    conn = sqlite3.connect(collected)
    try:
        conn.execute("UPDATE institutions SET sigungu_code = '26110'")
        conn.commit()
    finally:
        conn.close()

    failed = [c.name for c in run_validations(collected) if not c.ok]
    assert "행정구역 코드 미채움" in failed


def _observation_count(db: Path) -> int:
    conn = sqlite3.connect(db)
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM rate_observations WHERE validation_status != 'error'"
        ).fetchone()[0]
    finally:
        conn.close()
