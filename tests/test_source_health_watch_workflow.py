"""source health 감시 workflow와 정기 수집 1회 재실행 경로의 계약.

재실행은 recover-failed-scheduled-collection.yml 한 곳에서만 한다. 같은 완료
이벤트에 감시 workflow까지 "신협만"을 dispatch하면 재실행이 두 번 된다.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from scripts.source_health_incident import report

from rate_monitor.db import models as m
from rate_monitor.db.session import create_db_engine, make_session_factory, session_scope

WATCH = Path(".github/workflows/source-health-watch.yml")
RECOVERY = Path(".github/workflows/recover-failed-scheduled-collection.yml")


def test_watch_syncs_issues_read_only_and_fails_closed() -> None:
    text = WATCH.read_text(encoding="utf-8")
    assert "issues: write" in text
    assert "contents: read" in text
    assert "scripts/source_health_incident.py" in text
    assert "--report-only" in text
    assert "Synchronize source incident issues" in text
    assert "continue-on-error: true" not in text
    # 감시 workflow는 writer도, dispatcher도 아니다.
    assert "gh workflow run" not in text
    assert "actions: write" not in text
    assert "storage upload" not in text


def test_watch_only_operates_on_main_and_supports_manual_inspection() -> None:
    text = WATCH.read_text(encoding="utf-8")
    assert "github.event.workflow_run.head_branch == 'main'" in text
    assert "github.ref == 'refs/heads/main'" in text
    assert "workflow_dispatch:" in text
    assert "ref: main" in text
    assert '"수집 — 일반·새마을금고"' in text
    assert '"수집 — 농·축협"' in text
    assert 'SOURCES="nh_local"' in text
    assert 'SOURCES="cu kfcc"' in text


def test_exactly_one_retry_path_exists_for_scheduled_cu_failures() -> None:
    recovery = RECOVERY.read_text(encoding="utf-8")
    # 정기 수집(schedule)만 재실행하고, 재실행 자체(workflow_dispatch)는 다시 재실행하지 않는다.
    assert "github.event.workflow_run.event == 'schedule'" in recovery
    assert '"신협만"' in recovery
    assert "scripts/scheduled_soft_failure_recovery.py" in recovery
    assert "--ref main" in recovery
    # 감시 workflow에는 재실행이 없다 — 한 이벤트에 한 번만 재실행한다.
    assert "retry_cu_once" not in WATCH.read_text(encoding="utf-8")


def test_report_only_prints_canonical_evidence_without_github_token(tmp_path: Path) -> None:
    path = tmp_path / "evidence.sqlite3"
    engine = create_db_engine(path)
    m.Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    with session_scope(factory) as session:
        session.add(m.Source(
            id="cu", name="cu", sector="cu", mode="http", source_role="primary_official",
            trust_level="official_direct", priority=10, enabled=True, policy_status="review",
            coverage_status="partial", parser_version="1",
            created_at=datetime(2026, 9, 1), updated_at=datetime(2026, 9, 1),
        ))
        session.add(m.CollectionRun(
            id="bad", source_id="cu", mode="http", started_at=datetime(2026, 9, 10, 19, 11),
            finished_at=datetime(2026, 9, 10, 19, 14), status="failed", query_context_json={},
            raw_count=136, parsed_count=0, valid_count=0, warning_count=0, error_count=1,
            fallback_used=False, message="SOURCE_EMPTY_RESULT: cu 전국 파싱 건수 0건",
        ))

    line = report(path, "cu")
    assert line.startswith("cu: incident=yes code=SOURCE_EMPTY_RESULT status=failed run=bad")
    assert "raw/parsed/valid=136/0/0" in line
    assert "SOURCE_EMPTY_RESULT" in line

    assert report(path, "kfcc").startswith("kfcc: incident=yes code=NO_COLLECTION_RUN")
    sqlite3.connect(path).close()
