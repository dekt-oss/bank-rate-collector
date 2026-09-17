"""화면에 나가는 시간은 한국시간이다 (domain/timeutil.py).

이 저장소가 다루는 것은 한국 금융기관의 공시금리이고 읽는 사람도 한국에
있다. GitHub Actions와 DB 경계에서는 UTC를 쓰므로, 화면·경로·스케줄 해석에서
KST 변환을 빠뜨리지 않는지 확인한다.
"""

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from rate_monitor.domain.timeutil import KST, kst_date_stamp, kst_path_stamp, to_kst

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_a_late_utc_timestamp_lands_on_the_right_korean_day() -> None:
    """16:17 UTC는 한국에서는 다음 날 01:17이다.

    UTC 날짜로 파일 이름과 원본 디렉터리를 만들면 하루 전 날짜가 붙을 수 있다.
    """
    instant = datetime(2026, 8, 5, 16, 17, tzinfo=UTC)
    assert to_kst(instant).strftime("%Y-%m-%d %H:%M") == "2026-08-06 01:17"
    assert kst_date_stamp(instant) == "20260806"
    assert kst_path_stamp(instant) == "2026/08/06"


def test_morning_parent_cron_matches_fourteen_fifty_korea_time() -> None:
    """Morning parent의 05:50 UTC 예약은 한국시간 14:50이다."""
    import re

    text = (
        REPO_ROOT / ".github/workflows/collect-morning-cycle.yml"
    ).read_text(encoding="utf-8")
    match = re.search(r'cron:\s*"(\d+)\s+(\d+)\s', text)
    assert match, "morning parent cron을 찾지 못했다"
    minute, hour = int(match.group(1)), int(match.group(2))
    utc = datetime(2026, 8, 9, hour, minute, tzinfo=UTC)
    local = to_kst(utc)
    assert local.strftime("%H:%M") == "14:50"
    assert (local + timedelta(days=1)).weekday() < 5


def test_the_page_carries_korean_time(tmp_path: Path) -> None:
    """빌드된 페이지의 시각에 +09:00이 붙어 있어야 한다.

    시간대 표시가 없으면 읽는 쪽이 UTC로 볼지 KST로 볼지 알 수 없다.
    """
    from rate_monitor.services.dashboard_service import build_summary

    db = tmp_path / "empty.sqlite3"
    _make_schema(db)
    summary = build_summary(db)
    assert summary["generated_at"].endswith("+09:00"), summary["generated_at"]


def test_run_times_are_converted_on_the_way_out(tmp_path: Path) -> None:
    """DB에는 UTC가 적혀 있다. 화면으로 나갈 때 바뀌어야 한다."""
    from rate_monitor.services.dashboard_service import build_summary

    db = tmp_path / "one_run.sqlite3"
    _make_schema(db)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO sources (id, name, sector, mode, source_role, trust_level,"
        " priority, base_reference, enabled, policy_status, coverage_status,"
        " parser_version, created_at, updated_at) VALUES"
        " ('finlife', 'x', 'savings_bank', 'api', 'secondary_official',"
        " 'official_direct', 20, 'x', 1, 'allowed', 'partial', '0.1.0', ?, ?)",
        ("2026-08-06 05:20:52", "2026-08-06 05:20:52"),
    )
    conn.execute(
        "INSERT INTO collection_runs (id, source_id, status, started_at, finished_at,"
        " raw_count, parsed_count, valid_count, warning_count, error_count, mode,"
        " query_context_json, fallback_used) VALUES"
        " ('run-1', 'finlife', 'success', '2026-08-06 05:20:52', '2026-08-06 05:21:12',"
        "  7, 4010, 4010, 0, 0, 'api', '{}', 0)"
    )
    conn.commit()
    conn.close()

    summary = build_summary(db)
    # 05:20 UTC는 한국에서 14:20이다.
    assert summary["runs"][0]["started_at"] == "2026-08-06T14:20:52+09:00"
    assert summary["runs"][0]["finished_at"] == "2026-08-06T14:21:12+09:00"
    assert summary["latest_run"]["started_at"].startswith("2026-08-06T14:20:52")


def test_kst_is_nine_hours_ahead() -> None:
    assert KST.utcoffset(None).total_seconds() == 9 * 3600


def _make_schema(db: Path) -> None:
    from rate_monitor.db.models import Base
    from rate_monitor.db.session import create_db_engine

    engine = create_db_engine(db)
    Base.metadata.create_all(engine)
    engine.dispose()
