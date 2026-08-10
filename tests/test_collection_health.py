"""Source freshness / run health / warning taxonomy 회귀 테스트."""

import sqlite3
from datetime import datetime
from pathlib import Path

from rate_monitor.db import models as m
from rate_monitor.db.session import create_db_engine, make_session_factory, session_scope
from rate_monitor.domain.timeutil import KST
from rate_monitor.services.source_health_service import _reason_counts, build_collection_health


def _db(tmp_path: Path):
    path = tmp_path / "health.sqlite3"
    engine = create_db_engine(path)
    m.Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    return path, engine, factory


def _source(session, *, source_id="nh_local", enabled=True):
    session.add(m.Source(
        id=source_id, name=source_id, sector="nh_local", mode="http",
        source_role="secondary_official", trust_level="official_direct", priority=10,
        enabled=enabled, policy_status="allowed", coverage_status="nationwide",
        parser_version="1", created_at=datetime(2026, 8, 1), updated_at=datetime(2026, 8, 1),
    ))


def _run(session, *, source_id="nh_local", run_id="r1", status="success",
         started=datetime(2026, 8, 10, 0, 0), warnings=0, errors=0):
    session.add(m.CollectionRun(
        id=run_id, source_id=source_id, mode="http", started_at=started,
        finished_at=started, status=status, query_context_json={}, raw_count=10,
        parsed_count=100, valid_count=100, warning_count=warnings, error_count=errors,
        fallback_used=False,
    ))


def _health(path, moment=datetime(2026, 8, 10, 22, 0, tzinfo=KST)):
    import sqlite3
    conn = sqlite3.connect(path)
    try:
        return build_collection_health(conn, moment=moment)
    finally:
        conn.close()


def test_recent_success_is_green(tmp_path) -> None:
    path, engine, factory = _db(tmp_path)
    with session_scope(factory) as s:
        _source(s)
        _run(s)
    card = _health(path)["sources"][0]
    assert card["signal"] == "green"
    assert card["last_success_at"].startswith("2026-08-10T09:00")
    engine.dispose()


def test_partial_is_yellow_but_failed_is_red(tmp_path) -> None:
    path, engine, factory = _db(tmp_path)
    with session_scope(factory) as s:
        _source(s)
        _run(s, run_id="ok", started=datetime(2026, 8, 10, 0, 0))
        _run(s, run_id="partial", status="partial", started=datetime(2026, 8, 10, 1, 0))
    assert _health(path)["sources"][0]["signal"] == "yellow"
    with session_scope(factory) as s:
        _run(s, run_id="bad", status="failed", started=datetime(2026, 8, 10, 2, 0))
    card = _health(path)["sources"][0]
    assert card["signal"] == "red"
    assert card["last_success_at"] is not None
    engine.dispose()


def test_bonus_rate_warning_is_info_not_yellow(tmp_path) -> None:
    path, engine, factory = _db(tmp_path)
    with session_scope(factory) as s:
        _source(s)
        _run(s, warnings=1)
        s.add(m.ReviewItem(
            run_id="r1", issue_type="schema_warning", severity="warning",
            message="우대금리 행: e-joy 인터넷예금 우대금리 (0.1%)",
            payload_json={}, created_at=datetime(2026, 8, 10),
        ))
    card = _health(path)["sources"][0]
    assert card["signal"] == "green"
    assert card["latest_attempt"]["raw_warning_count"] == 1
    assert card["latest_attempt"]["actionable_warning_count"] == 0
    assert card["latest_attempt"]["info_count"] == 1
    assert card["reasons"] == [{"code": "PREFERENCE_RATE_ROW", "severity": "info", "count": 1}]
    engine.dispose()


def test_actionable_schema_warning_is_yellow(tmp_path) -> None:
    path, engine, factory = _db(tmp_path)
    with session_scope(factory) as s:
        _source(s)
        _run(s, warnings=1)
        s.add(m.ReviewItem(
            run_id="r1", issue_type="schema_warning", severity="warning",
            message="계약기간을 읽지 못했다: '-'", payload_json={},
            created_at=datetime(2026, 8, 10),
        ))
    card = _health(path)["sources"][0]
    assert card["signal"] == "yellow"
    assert card["latest_attempt"]["actionable_warning_count"] == 1
    engine.dispose()


def test_business_day_freshness_handles_weekend_and_missed_cycles(tmp_path) -> None:
    path, engine, factory = _db(tmp_path)
    with session_scope(factory) as s:
        _source(s)
        # 8/7 00:00 UTC = 금요일 09:00 KST
        _run(s, started=datetime(2026, 8, 7, 0, 0))
    # 월요일 06:30 KST: core cutoff(07시) 전이므로 금요일이 기대일 → 정상
    before = _health(path, datetime(2026, 8, 10, 6, 30, tzinfo=KST))["sources"][0]
    assert before["freshness"]["signal"] == "green"
    # 월요일 밤: 월요일 수집 1회를 놓침 → yellow
    after = _health(path, datetime(2026, 8, 10, 22, 0, tzinfo=KST))["sources"][0]
    assert after["freshness"]["signal"] == "yellow"
    # 화요일 밤까지 못 받음 → 2회 지연 red
    late = _health(path, datetime(2026, 8, 11, 22, 0, tzinfo=KST))["sources"][0]
    assert late["freshness"]["signal"] == "red"
    engine.dispose()


def test_disabled_source_is_gray(tmp_path) -> None:
    path, engine, factory = _db(tmp_path)
    with session_scope(factory) as s:
        _source(s, enabled=False)
    card = _health(path)["sources"][0]
    assert card["signal"] == "gray"
    engine.dispose()



def test_row_validation_warning_is_actionable_even_without_review_item() -> None:
    """행 validation warning만 남는 parser 경로도 초록불로 숨기지 않는다."""
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript("""
            CREATE TABLE review_items (
                run_id TEXT, issue_type TEXT, severity TEXT, message TEXT
            );
            CREATE TABLE rate_observations (
                last_run_id TEXT, validation_status TEXT, validation_message TEXT
            );
            INSERT INTO rate_observations VALUES
                ('r1', 'warning', '계약기간을 읽지 못했다: -'),
                ('r1', 'valid', NULL),
                ('old', 'warning', '계약기간을 읽지 못했다: -');
        """)
        reasons = _reason_counts(conn, "r1")
    finally:
        conn.close()
    assert reasons == [
        {"code": "TERM_PARSE_AMBIGUOUS", "severity": "warning", "count": 1}
    ]
