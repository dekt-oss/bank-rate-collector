"""발행 게이트가 수집원별 실행 이력을 먼저 보는 계약.

2026-09-11 04:14 KST 신협 실행(136장 전부 `[]`, parsed 0, status success)은 발행
게이트에서 "비교할 직전 실행이 없다. 건너뛴다"로 통과해 신협 0건 화면이 발행됐다.
`summary.runs`가 전체 10개 창이라 Data.go 수신잔액 4회가 신협 직전 실행을 창 밖으로
밀어냈기 때문이다. 이제 `source_run_history`(수집원별 확인 실행 2개)를 먼저 본다.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from scripts.volume_gate import compare, last_two_runs, report

from rate_monitor.db import models as m
from rate_monitor.db.session import create_db_engine, make_session_factory, session_scope
from rate_monitor.services.dashboard_service import _source_run_history, build_summary


def _run(source_id: str, status: str, parsed: int, raw: int = 10) -> dict:
    return {"source_id": source_id, "status": status, "parsed_count": parsed, "raw_count": raw}


def _summary_2026_09_11_04_14() -> dict:
    """그날 발행 artifact의 runs 창을 그대로 옮긴 것이다 (신협 직전 실행 없음)."""
    return {
        "runs": [
            _run("cu", "success", 0, raw=136),
            _run("fsb", "success", 3_754),
            _run("bok_ecos_macro", "no_change", 861),
            _run("bok_ecos", "no_change", 398),
            _run("finlife_bank", "success", 333),
            _run("finlife_savings_bank", "success", 3_989),
            _run("data_go_agri_coop_funding", "success", 1_109),
            _run("data_go_savings_bank_funding", "success", 158),
            _run("data_go_agri_coop_funding", "success", 1_109),
            _run("data_go_savings_bank_funding", "success", 158),
        ],
        "source_run_history": [
            {
                "source_id": "cu",
                "confirmed_runs": [
                    _run("cu", "success", 0, raw=136), _run("cu", "success", 30_483)
                ],
                "latest_attempt": _run("cu", "success", 0, raw=136),
            },
            {
                "source_id": "fsb",
                "confirmed_runs": [_run("fsb", "success", 3_754), _run("fsb", "success", 3_754)],
                "latest_attempt": _run("fsb", "success", 3_754),
            },
        ],
    }


def test_per_source_history_restores_the_cu_baseline_and_blocks_the_empty_publish():
    summary = _summary_2026_09_11_04_14()

    grouped = last_two_runs(summary)
    assert [r["parsed_count"] for r in grouped["cu"]] == [0, 30_483]

    changes = compare(summary)
    cu = next(c for c in changes if c.source_id == "cu")
    assert cu.before == 30_483 and cu.after == 0 and cu.collapsed
    assert report(changes) == 1


def test_without_history_the_old_window_silently_skips_cu():
    summary = _summary_2026_09_11_04_14()
    del summary["source_run_history"]

    # 예전 동작 그대로다 — 이것이 사고의 원인이었다. 이력이 있으면 위 시험이 막는다.
    assert "cu" not in {c.source_id for c in compare(summary)}


def test_history_still_excludes_separate_data_products_and_failed_runs():
    summary = {
        "runs": [],
        "source_run_history": [
            {
                "source_id": "cu_disclosure_funding",
                "confirmed_runs": [_run("cu_disclosure_funding", "success", 4),
                                   _run("cu_disclosure_funding", "success", 828)],
                "latest_attempt": None,
            },
            {
                "source_id": "cu",
                "confirmed_runs": [_run("cu", "success", 30_482), _run("cu", "success", 30_483)],
                "latest_attempt": _run("cu", "failed", 0),
            },
        ],
    }
    changes = compare(summary)
    assert {c.source_id for c in changes} == {"cu"}
    assert not changes[0].collapsed
    assert report(changes) == 0


def test_summary_exposes_two_confirmed_runs_per_source_and_the_latest_attempt(tmp_path: Path):
    path = tmp_path / "history.sqlite3"
    engine = create_db_engine(path)
    m.Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    with session_scope(factory) as session:
        for source_id in ("cu", "fsb"):
            session.add(m.Source(
                id=source_id, name=source_id, sector="cu", mode="http",
                source_role="primary_official", trust_level="official_direct", priority=10,
                enabled=True, policy_status="review", coverage_status="partial",
                parser_version="1", created_at=datetime(2026, 9, 1),
                updated_at=datetime(2026, 9, 1),
            ))
        rows = [
            ("cu", "c1", "success", datetime(2026, 9, 9, 19, 0), 702, 30_495),
            ("cu", "c2", "success", datetime(2026, 9, 10, 13, 20), 702, 30_483),
            ("cu", "c3", "failed", datetime(2026, 9, 10, 19, 11), 136, 0),
            ("fsb", "f1", "success", datetime(2026, 9, 10, 19, 10), 13, 3_754),
        ]
        for source_id, run_id, status, started, raw, parsed in rows:
            session.add(m.CollectionRun(
                id=run_id, source_id=source_id, mode="http", started_at=started,
                finished_at=started, status=status, query_context_json={}, raw_count=raw,
                parsed_count=parsed, valid_count=parsed, warning_count=0, error_count=0,
                fallback_used=False,
                message="SOURCE_EMPTY_RESULT: cu" if status == "failed" else "ok",
            ))

    conn = sqlite3.connect(path)
    try:
        history = {h["source_id"]: h for h in _source_run_history(conn)}
    finally:
        conn.close()

    assert [r["id"] for r in history["cu"]["confirmed_runs"]] == ["c2", "c1"]
    assert history["cu"]["latest_attempt"]["id"] == "c3"
    assert history["cu"]["latest_attempt"]["status"] == "failed"
    assert "SOURCE_EMPTY_RESULT" in history["cu"]["latest_attempt"]["message"]
    assert [r["id"] for r in history["fsb"]["confirmed_runs"]] == ["f1"]

    summary = build_summary(path)
    assert {h["source_id"] for h in summary["source_run_history"]} == {"cu", "fsb"}
    # 발행 게이트의 옛 창(`runs`)에도 raw_count가 실려 soft-recovery가 0건 판정을 한다.
    assert all("raw_count" in run for run in summary["runs"])
