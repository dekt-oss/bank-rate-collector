"""NH e-joy current-run fail-closed validation contract."""

import json
import sqlite3

from rate_monitor.services.validation_service import _nh_ejoy_current_run_checks

MARKER = "nh_acquisition_contract=v2"


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE collection_runs (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL,
            message TEXT
        );
        CREATE TABLE raw_artifacts (
            run_id TEXT NOT NULL,
            request_meta_json TEXT NOT NULL
        );
        CREATE TABLE rate_observations (
            last_run_id TEXT,
            max_rate TEXT
        );
        """
    )
    return conn


def _run(
    conn: sqlite3.Connection,
    run_id: str,
    *,
    status: str = "success",
    started_at: str = "2026-08-30T00:00:00",
    v2: bool = False,
) -> None:
    message = f"수집 완료 · {MARKER}" if v2 else "수집 완료"
    conn.execute(
        "INSERT INTO collection_runs(id, source_id, status, started_at, message)"
        " VALUES (?, 'nh_local', ?, ?, ?)",
        (run_id, status, started_at, message),
    )


def _raw(conn: sqlite3.Connection, run_id: str, meta: dict) -> None:
    conn.execute(
        "INSERT INTO raw_artifacts(run_id, request_meta_json) VALUES (?, ?)",
        (run_id, json.dumps(meta, ensure_ascii=False)),
    )


def _max(conn: sqlite3.Connection, run_id: str) -> None:
    conn.execute(
        "INSERT INTO rate_observations(last_run_id, max_rate) VALUES (?, '003.2000')",
        (run_id,),
    )


def test_v1_confirmed_run_is_explicitly_skipped() -> None:
    conn = _conn()
    try:
        _run(conn, "v1")
        _raw(conn, "v1", {"kind": "rate", "screen": "SFDPW0163R"})
        checks = _nh_ejoy_current_run_checks(conn)
    finally:
        conn.close()

    assert len(checks) == 1
    assert checks[0].ok is True
    assert checks[0].name.startswith("[건너뜀]")
    assert "v1 baseline" in checks[0].detail


def test_v2_evidence_and_current_max_rate_pass() -> None:
    conn = _conn()
    try:
        _run(conn, "v2", v2=True)
        _raw(
            conn,
            "v2",
            {"kind": "rate", "ejoy_options": [{"add_rate": "0.2"}]},
        )
        _raw(conn, "v2", {"kind": "rate", "ejoy_options": []})
        _max(conn, "v2")
        checks = _nh_ejoy_current_run_checks(conn)
    finally:
        conn.close()

    assert [check.ok for check in checks] == [True, True, True]
    assert checks[0].name == "NH e-joy v2 run contract 표식"
    assert "2/2" in checks[1].detail
    assert "evidence artifacts 1 / max_rate 1건" in checks[2].detail


def test_v2_evidence_without_current_max_rate_fails_closed() -> None:
    conn = _conn()
    try:
        _run(conn, "v2", v2=True)
        _raw(
            conn,
            "v2",
            {"kind": "rate", "ejoy_options": [{"add_rate": "0.2"}]},
        )
        checks = _nh_ejoy_current_run_checks(conn)
    finally:
        conn.close()

    assert checks[0].ok is True
    assert checks[1].ok is True
    assert checks[2].ok is False
    assert checks[2].name == "NH e-joy evidence → current max_rate"


def test_v2_with_all_ejoy_metadata_missing_fails_instead_of_looking_like_v1() -> None:
    conn = _conn()
    try:
        _run(conn, "v2", v2=True)
        _raw(conn, "v2", {"kind": "rate", "screen": "SFDPW0163R"})
        _raw(conn, "v2", {"kind": "rate", "screen": "SFDPW0164R"})
        checks = _nh_ejoy_current_run_checks(conn)
    finally:
        conn.close()

    assert checks[0].ok is True
    assert checks[1].ok is False
    assert "0/2" in checks[1].detail


def test_partial_v2_metadata_fails_even_if_a_max_rate_exists() -> None:
    conn = _conn()
    try:
        _run(conn, "v2", v2=True)
        _raw(
            conn,
            "v2",
            {"kind": "rate", "ejoy_options": [{"add_rate": "0.2"}]},
        )
        _raw(conn, "v2", {"kind": "rate", "screen": "SFDPW0164R"})
        _max(conn, "v2")
        checks = _nh_ejoy_current_run_checks(conn)
    finally:
        conn.close()

    assert checks[1].ok is False
    assert "1/2" in checks[1].detail
    assert checks[2].ok is True


def test_v2_without_source_evidence_does_not_invent_a_max_rate_requirement() -> None:
    conn = _conn()
    try:
        _run(conn, "v2", v2=True)
        _raw(conn, "v2", {"kind": "rate", "ejoy_options": []})
        checks = _nh_ejoy_current_run_checks(conn)
    finally:
        conn.close()

    assert [check.ok for check in checks] == [True, True, True]
    assert "evidence artifacts 0 / max_rate 0건" in checks[2].detail


def test_latest_failed_v2_attempt_does_not_block_previous_confirmed_value_publish() -> None:
    conn = _conn()
    try:
        _run(conn, "old-confirmed", started_at="2026-08-29T00:00:00")
        _raw(conn, "old-confirmed", {"kind": "rate", "screen": "SFDPW0163R"})
        _run(
            conn,
            "failed-v2",
            status="failed",
            started_at="2026-08-30T00:00:00",
            v2=True,
        )
        _raw(
            conn,
            "failed-v2",
            {"kind": "rate", "ejoy_options": [{"add_rate": "0.2"}]},
        )
        checks = _nh_ejoy_current_run_checks(conn)
    finally:
        conn.close()

    assert len(checks) == 1
    assert checks[0].ok is True
    assert "old-confirmed" in checks[0].detail


def test_losing_run_marker_after_v2_cutover_fails_closed() -> None:
    conn = _conn()
    try:
        _run(
            conn,
            "first-v2",
            started_at="2026-08-29T00:00:00",
            v2=True,
        )
        _raw(conn, "first-v2", {"kind": "rate", "ejoy_options": []})
        _run(conn, "marker-lost", started_at="2026-08-30T00:00:00")
        _raw(conn, "marker-lost", {"kind": "rate", "ejoy_options": []})
        checks = _nh_ejoy_current_run_checks(conn)
    finally:
        conn.close()

    assert len(checks) == 1
    assert checks[0].ok is False
    assert checks[0].name == "NH e-joy v2 run contract 연속성"
    assert "계약 표식을 잃었다" in checks[0].detail
