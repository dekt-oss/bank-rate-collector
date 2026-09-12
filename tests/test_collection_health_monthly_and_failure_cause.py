"""수집 상태 카드 — 월 주기 수집원의 최신성과 실패 원인 노출 계약.

2026-09-11 화면의 신협 RED 카드는 금리 수집이 아니라 "신협중앙회 경영공시
요약재무현황"(월 단위 공시, 매월 2일 01:17 KST 수집)이 평일 주기로 재어져
"예정 수집 3회 지연"이 된 것이었다. 실제 금리 수집 실패와 구분되어야 한다.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path

from rate_monitor.db import models as m
from rate_monitor.db.session import create_db_engine, make_session_factory, session_scope
from rate_monitor.domain.timeutil import KST
from rate_monitor.services.source_health_service import (
    MONTHLY_SOURCES,
    build_collection_health,
)
from rate_monitor.services.source_health_service import (
    expected_monthly_collection_date as due,
)

SITE = (Path(__file__).resolve().parents[1] / "web/templates/site.html").read_text(
    encoding="utf-8"
)


def _db(tmp_path: Path):
    path = tmp_path / "health.sqlite3"
    engine = create_db_engine(path)
    m.Base.metadata.create_all(engine)
    return path, make_session_factory(engine)


def _source(session, source_id: str) -> None:
    session.add(m.Source(
        id=source_id, name=source_id, sector="cu", mode="http",
        source_role="primary_official", trust_level="official_direct", priority=10,
        enabled=True, policy_status="review", coverage_status="partial",
        parser_version="1", created_at=datetime(2026, 8, 1), updated_at=datetime(2026, 8, 1),
    ))


def _run(session, *, source_id: str, run_id: str, status: str, started: datetime,
         raw: int = 10, parsed: int = 100, message: str = "ok") -> None:
    session.add(m.CollectionRun(
        id=run_id, source_id=source_id, mode="http", started_at=started,
        finished_at=started, status=status, query_context_json={}, raw_count=raw,
        parsed_count=parsed, valid_count=parsed, warning_count=0,
        error_count=1 if status == "failed" else 0, fallback_used=False, message=message,
    ))


def _card(path: Path, source_id: str, moment: datetime) -> dict:
    conn = sqlite3.connect(path)
    try:
        health = build_collection_health(conn, moment=moment)
    finally:
        conn.close()
    return next(c for c in health["sources"] if c["source_id"] == source_id)


def test_monthly_due_date_is_the_second_of_the_month_after_the_morning_cutoff() -> None:
    assert due(datetime(2026, 9, 11, 20, tzinfo=KST)) == date(2026, 9, 2)
    assert due(datetime(2026, 9, 2, 6, tzinfo=KST)) == date(2026, 8, 2)
    assert due(datetime(2026, 9, 2, 7, tzinfo=KST)) == date(2026, 9, 2)
    assert due(datetime(2026, 1, 1, 12, tzinfo=KST)) == date(2025, 12, 2)


def test_cu_disclosure_funding_is_fresh_within_its_month(tmp_path: Path) -> None:
    assert "cu_disclosure_funding" in MONTHLY_SOURCES
    path, factory = _db(tmp_path)
    with session_scope(factory) as session:
        _source(session, "cu_disclosure_funding")
        # 2026-09-08 23:44 KST = 14:44 UTC (DB는 naive UTC)
        _run(session, source_id="cu_disclosure_funding", run_id="m1", status="success",
             started=datetime(2026, 9, 8, 14, 44), raw=0, parsed=828)

    card = _card(path, "cu_disclosure_funding", datetime(2026, 9, 11, 20, tzinfo=KST))
    assert card["freshness"]["cadence"] == "monthly"
    assert card["freshness"]["signal"] == "green"
    assert card["freshness"]["missed_cycles"] == 0
    assert card["signal"] == "green"
    assert card["failure_message"] is None

    october = _card(path, "cu_disclosure_funding", datetime(2026, 10, 3, 9, tzinfo=KST))
    assert october["freshness"]["signal"] == "yellow"
    assert october["freshness"]["label"] == "월 주기 수집 1회 지연"

    november = _card(path, "cu_disclosure_funding", datetime(2026, 11, 3, 9, tzinfo=KST))
    assert november["freshness"]["signal"] == "red"
    assert november["freshness"]["missed_cycles"] == 2


def test_weekday_sources_keep_the_business_day_contract(tmp_path: Path) -> None:
    path, factory = _db(tmp_path)
    with session_scope(factory) as session:
        _source(session, "cu")
        _run(session, source_id="cu", run_id="c1", status="success",
             started=datetime(2026, 9, 8, 8, 22), raw=702, parsed=30_502)

    card = _card(path, "cu", datetime(2026, 9, 11, 20, tzinfo=KST))
    assert "cadence" not in card["freshness"]
    assert card["freshness"]["signal"] == "red"
    assert card["freshness"]["missed_cycles"] == 3


def test_failed_gate_run_shows_the_exact_cause_and_keeps_last_success(tmp_path: Path) -> None:
    path, factory = _db(tmp_path)
    cause = (
        "SOURCE_EMPTY_RESULT: cu 전국 파싱 건수 0건이 최소 정상 기준 7,500건보다 적다"
    )
    with session_scope(factory) as session:
        _source(session, "cu")
        _run(session, source_id="cu", run_id="ok", status="success",
             started=datetime(2026, 9, 10, 13, 20), raw=702, parsed=30_483)
        _run(session, source_id="cu", run_id="bad", status="failed",
             started=datetime(2026, 9, 10, 19, 11), raw=136, parsed=0, message=cause)

    card = _card(path, "cu", datetime(2026, 9, 11, 4, 20, tzinfo=KST))
    assert card["signal"] == "red"
    assert card["run_health"] == {"signal": "red", "label": "failed"}
    assert card["failure_message"] == cause
    assert card["latest_attempt"]["run_id"] == "bad"
    assert card["latest_attempt"]["parsed_count"] == 0
    # 마지막 정상은 실패 실행이 아니라 직전 정상 실행이다.
    assert card["last_success_at"].startswith("2026-09-10T22:20")
    assert card["showing_from_at"].startswith("2026-09-10T22:20")


def test_site_renders_the_failure_cause_and_parsed_count_on_the_card() -> None:
    assert "s.failure_message" in SITE
    assert 'data-source-failure-cause="${esc(s.source_id)}"' in SITE
    assert "실패 원인 ${esc(s.failure_message)}" in SITE
    assert "parsed ${num(r.parsed_count)}" in SITE
    assert ".health-src .health-failure-cause" in SITE
