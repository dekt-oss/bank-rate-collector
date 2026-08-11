"""Source freshness / run health / warning taxonomy 회귀 테스트."""

import sqlite3
from datetime import date, datetime
from pathlib import Path

from rate_monitor.db import models as m
from rate_monitor.db.session import create_db_engine, make_session_factory, session_scope
from rate_monitor.domain.timeutil import KST
from rate_monitor.services.source_health_service import (
    _reason_counts,
    _review_reason,
    _row_warning_reason,
    build_collection_health,
    expected_collection_date,
)


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
            message="새로운 스키마 경고", payload_json={},
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
    # core source의 기존 07:00 cutoff는 유지한다.
    before = _health(path, datetime(2026, 8, 10, 6, 45, tzinfo=KST))["sources"][0]
    assert before["freshness"]["signal"] == "green"
    # 월요일 07:05: 월요일 수집 1회를 놓침 → yellow
    after = _health(path, datetime(2026, 8, 10, 7, 5, tzinfo=KST))["sources"][0]
    assert after["freshness"]["signal"] == "yellow"
    # 화요일 07:05까지 못 받음 → 2회 지연 red
    late = _health(path, datetime(2026, 8, 11, 7, 5, tzinfo=KST))["sources"][0]
    assert late["freshness"]["signal"] == "red"
    engine.dispose()


def test_kfcc_freshness_cutoff_is_eight_but_core_stays_seven() -> None:
    friday = date(2026, 8, 7)
    monday = date(2026, 8, 10)
    assert expected_collection_date(
        "nh_local", datetime(2026, 8, 10, 6, 59, tzinfo=KST)
    ) == friday
    assert expected_collection_date(
        "nh_local", datetime(2026, 8, 10, 7, 0, tzinfo=KST)
    ) == monday
    assert expected_collection_date(
        "kfcc", datetime(2026, 8, 10, 7, 59, tzinfo=KST)
    ) == friday
    assert expected_collection_date(
        "kfcc", datetime(2026, 8, 10, 8, 0, tzinfo=KST)
    ) == monday


def test_disabled_source_is_gray(tmp_path) -> None:
    path, engine, factory = _db(tmp_path)
    with session_scope(factory) as s:
        _source(s, enabled=False)
    card = _health(path)["sources"][0]
    assert card["signal"] == "gray"
    engine.dispose()



def test_known_missing_term_is_info_even_without_review_item() -> None:
    """원천이 '-'로 주는 기간은 숨기지 않되 수집 장애로 취급하지 않는다."""
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
                ('r1', 'warning', '계약기간을 읽지 못했다: ''-'''),
                ('r1', 'valid', NULL),
                ('old', 'warning', '계약기간을 읽지 못했다: ''-''');
        """)
        reasons = _reason_counts(conn, "r1")
    finally:
        conn.close()
    assert reasons == [
        {"code": "TERM_NOT_PROVIDED", "severity": "info", "count": 1}
    ]



def test_known_source_shape_warnings_are_info_but_new_schema_warning_is_actionable() -> None:
    assert _review_reason(
        "schema_warning", "warning", "행이 0건이다. 조회 조건을 확인한다"
    ) == ("EMPTY_QUERY_RESULT", "info")
    assert _review_reason(
        "schema_warning", "warning", "금리 필드가 없는 행: '310009'"
    ) == ("RATELESS_SOURCE_ROW", "info")
    assert _review_reason(
        "schema_warning", "warning", "SWEETENER가 없다. 값 없이 진행한다"
    ) == ("OPTIONAL_FIELD_MISSING", "info")
    assert _review_reason(
        "schema_warning", "warning", "새로운 알 수 없는 구조"
    ) == ("SCHEMA_WARNING", "warning")
    assert _row_warning_reason("계약기간을 읽지 못했다: '-'") == (
        "TERM_NOT_PROVIDED", "info"
    )
    assert _row_warning_reason("최고금리 변환 실패: '문의'") == (
        "ROW_VALIDATION_WARNING", "warning"
    )


def test_all_empty_success_is_red_even_if_empty_pages_are_info(tmp_path) -> None:
    path, engine, factory = _db(tmp_path)
    with session_scope(factory) as s:
        _source(s)
        _run(s)
        run = s.get(m.CollectionRun, "r1")
        run.parsed_count = 0
        run.valid_count = 0
        s.add(m.ReviewItem(
            run_id="r1", issue_type="schema_warning", severity="warning",
            message="행이 0건이다. 조회 조건을 확인한다", payload_json={},
            created_at=datetime(2026, 8, 10),
        ))
    card = _health(path)["sources"][0]
    assert card["signal"] == "red"
    assert card["run_health"]["label"] == "파싱 결과 0건"
    assert card["latest_attempt"]["info_count"] == 1
    engine.dispose()
