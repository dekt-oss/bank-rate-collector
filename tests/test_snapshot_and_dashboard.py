"""스냅샷·대시보드 검증 (명세서 v3.1 §3, §6).

실물 fixture로 수집한 DB를 스냅샷하고 대시보드를 만들어, 화면 수치가
SQL 집계와 일치하는지 확인한다.
"""

import json
import sqlite3
from pathlib import Path

import pytest

from rate_monitor.services.dashboard_service import (
    DATA_MARKER,
    HEAD_OFFICE_NOTICE,
    DashboardBuildError,
    build_dashboard,
    build_summary,
    render,
)
from rate_monitor.services.snapshot_service import (
    SnapshotIntegrityError,
    create_snapshot,
    sha256_of,
    verify_snapshot,
)
from tests.test_collection_service import REAL, run_collect

TEMPLATE = Path(__file__).resolve().parents[1] / "web" / "templates" / "dashboard.html"


@pytest.fixture()
def collected_db(tmp_path):
    """실물 fixture로 한 번 수집한 작업 DB."""
    from rate_monitor.db import models as m
    from rate_monitor.db.session import create_db_engine, make_session_factory

    db_path = tmp_path / "work.sqlite3"
    engine = create_db_engine(db_path)
    m.Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    run_collect(factory, tmp_path / "raw")
    engine.dispose()
    return db_path


# ── 스냅샷 ──────────────────────────────────────────────────────────────

def test_snapshot_creates_consistent_copy(collected_db, tmp_path) -> None:
    publish = tmp_path / "publish" / "rate_monitor.sqlite3"
    manifest_path = tmp_path / "publish" / "manifest.json"
    manifest = create_snapshot(collected_db, publish, manifest_path, run_id="run-x")

    assert publish.exists()
    assert manifest.integrity_check == "ok"
    assert manifest.foreign_key_check_violations == 0
    assert manifest.row_counts["rate_observations"] == 647


def test_manifest_hash_matches_actual_file(collected_db, tmp_path) -> None:
    """manifest SHA256 == 실제 DB 파일 해시 (P1-A 게이트)."""
    publish = tmp_path / "publish" / "db.sqlite3"
    manifest_path = tmp_path / "publish" / "manifest.json"
    manifest = create_snapshot(collected_db, publish, manifest_path)
    assert manifest.sqlite_sha256 == sha256_of(publish)


def test_manifest_counts_match_sql(collected_db, tmp_path) -> None:
    """manifest 행 수 == SQL COUNT (P1-A 게이트)."""
    publish = tmp_path / "publish" / "db.sqlite3"
    manifest_path = tmp_path / "publish" / "manifest.json"
    create_snapshot(collected_db, publish, manifest_path)
    verify_snapshot(publish, manifest_path)  # 어긋나면 예외


def test_published_snapshot_is_not_wal(collected_db, tmp_path) -> None:
    """배포본은 단일 파일로 완결돼야 한다.

    WAL 모드로 배포하면 이후 쓰기가 -wal 사이드카로 가서 본체 바이트가
    안 바뀌고, manifest의 SHA256이 변조를 놓친다.
    """
    publish = tmp_path / "publish" / "db.sqlite3"
    create_snapshot(collected_db, publish, tmp_path / "publish" / "m.json")

    conn = sqlite3.connect(publish)
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() != "wal"
    finally:
        conn.close()
    assert not publish.with_name(publish.name + "-wal").exists()
    assert not publish.with_name(publish.name + "-shm").exists()


def test_verify_detects_tampering(collected_db, tmp_path) -> None:
    """배포본이 바뀌면 검증이 잡아낸다.

    WAL 모드였다면 이 수정이 사이드카로 빠져 SHA256이 그대로였다.
    """
    publish = tmp_path / "publish" / "db.sqlite3"
    manifest_path = tmp_path / "publish" / "manifest.json"
    manifest = create_snapshot(collected_db, publish, manifest_path)
    original_hash = sha256_of(publish)
    assert original_hash == manifest.sqlite_sha256

    conn = sqlite3.connect(publish)
    conn.execute("DELETE FROM rate_observations WHERE rowid = 1")
    conn.commit()
    conn.close()

    assert sha256_of(publish) != original_hash, "변조가 본체 파일에 반영되지 않았다"
    with pytest.raises(SnapshotIntegrityError):
        verify_snapshot(publish, manifest_path)


def test_verify_detects_value_tampering(collected_db, tmp_path) -> None:
    """행 수가 그대로여도 값이 바뀌면 SHA256이 잡아낸다."""
    publish = tmp_path / "publish" / "db.sqlite3"
    manifest_path = tmp_path / "publish" / "manifest.json"
    create_snapshot(collected_db, publish, manifest_path)

    conn = sqlite3.connect(publish)
    # 실제로 값이 달라지는 수정이어야 한다. 같은 값을 다시 쓰면 페이지가
    # 안 바뀌어 해시도 그대로다.
    conn.execute("UPDATE rate_observations SET max_rate = '099.9999' WHERE rowid <= 5")
    conn.commit()
    changed = conn.execute(
        "SELECT COUNT(*) FROM rate_observations WHERE max_rate = '099.9999'"
    ).fetchone()[0]
    conn.close()
    assert changed == 5

    with pytest.raises(SnapshotIntegrityError, match="SHA256"):
        verify_snapshot(publish, manifest_path)


def test_snapshot_reads_wal_data(collected_db, tmp_path) -> None:
    """WAL 모드 DB를 파일 복사하면 최신 데이터가 빠질 수 있다.

    backup()은 WAL을 반영하므로 관측 건수가 그대로 넘어와야 한다.
    """
    publish = tmp_path / "publish" / "db.sqlite3"
    create_snapshot(collected_db, publish, tmp_path / "publish" / "m.json")
    conn = sqlite3.connect(publish)
    try:
        assert conn.execute("SELECT COUNT(*) FROM rate_observations").fetchone()[0] == 647
    finally:
        conn.close()


# ── 대시보드 ────────────────────────────────────────────────────────────

def test_summary_reflects_real_data(collected_db) -> None:
    summary = build_summary(collected_db)
    assert summary["totals"]["observations"] == 647
    assert summary["totals"]["products"] == 100
    assert summary["latest_run"]["status"] == "success"
    assert summary["by_term"], "기간별 분포가 비어 있다"
    assert summary["top_rates"], "상위 금리가 비어 있다"


def test_top_rates_are_sorted_numerically(collected_db) -> None:
    """0 패딩 저장 덕분에 SQL ORDER BY가 수치 순서여야 한다."""
    summary = build_summary(collected_db)
    rates = [float(r["base_rate"]) for r in summary["top_rates"]]
    assert rates == sorted(rates, reverse=True)
    assert rates[0] >= rates[-1]


def test_dashboard_builds_and_matches_summary(collected_db, tmp_path) -> None:
    site = tmp_path / "site" / "index.html"
    summary_path = tmp_path / "publish" / "summary.json"
    summary = build_dashboard(collected_db, TEMPLATE, site, summary_path)

    html = site.read_text(encoding="utf-8")
    assert DATA_MARKER in html
    assert HEAD_OFFICE_NOTICE in html

    written = json.loads(summary_path.read_text(encoding="utf-8"))
    assert written["totals"] == summary["totals"]


def test_dashboard_has_no_hardcoded_p0_numbers() -> None:
    """P0 대시보드의 하드코딩 수치가 템플릿에 남아 있으면 안 된다 (v3.1 §6.3)."""
    template = TEMPLATE.read_text(encoding="utf-8")
    for stale in ("768", "4,343", "137", "273", "2,652"):
        assert stale not in template, f"하드코딩 수치 잔존: {stale}"


def test_dashboard_inline_json_parses(collected_db, tmp_path) -> None:
    site = tmp_path / "site" / "index.html"
    build_dashboard(collected_db, TEMPLATE, site, tmp_path / "s.json")
    html = site.read_text(encoding="utf-8")
    start = html.find(DATA_MARKER) + len(DATA_MARKER)
    end = html.find("</script>", start)
    payload = json.loads(html[start:end].replace("<\\/", "</"))
    assert payload["totals"]["observations"] == 647


def test_render_rejects_template_without_marker() -> None:
    with pytest.raises(DashboardBuildError, match="주입 지점"):
        render("<html>주입 지점 없음</html>", {"totals": {}})


def test_build_fails_when_totals_disagree(collected_db, tmp_path) -> None:
    """화면 집계값이 summary와 다르면 산출물을 쓰지 않는다."""
    from rate_monitor.services import dashboard_service

    site = tmp_path / "site" / "index.html"
    original = dashboard_service.render

    def sabotage(template_text: str, summary: dict) -> str:
        broken = {**summary, "totals": {**summary["totals"], "observations": -1}}
        return original(template_text, broken)

    dashboard_service.render = sabotage
    try:
        with pytest.raises(DashboardBuildError, match="집계값"):
            build_dashboard(collected_db, TEMPLATE, site, tmp_path / "s.json")
    finally:
        dashboard_service.render = original
    assert not site.exists(), "검증 실패 시 산출물을 쓰면 안 된다"


def test_empty_db_produces_valid_dashboard(tmp_path) -> None:
    """수집 전에도 대시보드가 깨지지 않아야 한다."""
    from rate_monitor.db import models as m
    from rate_monitor.db.session import create_db_engine

    db_path = tmp_path / "empty.sqlite3"
    engine = create_db_engine(db_path)
    m.Base.metadata.create_all(engine)
    engine.dispose()

    site = tmp_path / "site" / "index.html"
    summary = build_dashboard(db_path, TEMPLATE, site, tmp_path / "s.json")
    assert summary["totals"]["observations"] == 0
    assert summary["latest_run"] is None
    assert site.exists()


def test_fixture_matches_expected_source_size() -> None:
    """fixture가 바뀌면 위 기대값들이 전부 흔들리므로 크기를 고정한다."""
    payload = json.loads(REAL.read_text(encoding="utf-8"))
    assert len(payload["result"]["optionList"]) == 647
