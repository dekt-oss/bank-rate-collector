"""화면에 나가는 시간은 한국시간이다 (domain/timeutil.py).

이 저장소가 다루는 것은 한국 금융기관의 공시금리이고 읽는 사람도 한국에
있다. 그런데 GitHub Actions는 UTC로 돌고, DB에도 UTC가 적힌다. 경계에서
바꾸는 것을 잊으면 정기 수집 시각과 날짜가 하루씩 어긋나 보일 수 있다.
"""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from rate_monitor.domain.timeutil import KST, kst_date_stamp, kst_path_stamp, to_kst

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_the_scheduled_run_lands_on_the_right_korean_day() -> None:
    """core 정기 수집은 전날 15:17 UTC, 한국에서는 다음 날 00:17이다.

    UTC 날짜로 파일 이름과 원본 디렉터리를 만들면 하루 전 날짜가 붙는다.
    """
    scheduled = datetime(2026, 8, 5, 15, 17, tzinfo=UTC)
    assert to_kst(scheduled).strftime("%Y-%m-%d %H:%M") == "2026-08-06 00:17"
    assert kst_date_stamp(scheduled) == "20260806"
    assert kst_path_stamp(scheduled) == "2026/08/06"


def test_the_core_cron_matches_twelve_seventeen_korea_time() -> None:
    """워크플로우의 첫 cron이 실제로 한국시간 00:17인지 값에서 확인한다.

    08:00 hard deadline에 여유를 두기 위해 core를 00:17 KST로 앞당겼다.
    00:17 KST는 전날 15:17 UTC다. 요일 이동과 두 번째 KFCC cron까지의
    계약은 `test_gate_contract`가 별도로 검증한다.
    """
    import re

    text = (REPO_ROOT / ".github/workflows/collect.yml").read_text(encoding="utf-8")
    match = re.search(r'cron:\s*"(\d+)\s+(\d+)\s', text)
    assert match, "cron을 찾지 못했다"
    minute, hour = int(match.group(1)), int(match.group(2))
    utc = datetime(2026, 8, 5, hour, minute, tzinfo=UTC)
    assert to_kst(utc).strftime("%H:%M") == "00:17"


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


def _make_schema(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE sources (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, sector TEXT NOT NULL,
          mode TEXT NOT NULL, source_role TEXT NOT NULL, trust_level TEXT NOT NULL,
          priority INTEGER NOT NULL, base_reference TEXT NOT NULL,
          enabled INTEGER NOT NULL, policy_status TEXT NOT NULL,
          coverage_status TEXT NOT NULL, parser_version TEXT NOT NULL,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE collection_runs (
          id TEXT PRIMARY KEY, source_id TEXT NOT NULL, status TEXT NOT NULL,
          started_at TEXT NOT NULL, finished_at TEXT,
          raw_count INTEGER NOT NULL DEFAULT 0,
          parsed_count INTEGER NOT NULL DEFAULT 0,
          valid_count INTEGER NOT NULL DEFAULT 0,
          warning_count INTEGER NOT NULL DEFAULT 0,
          error_count INTEGER NOT NULL DEFAULT 0,
          mode TEXT NOT NULL, query_context_json TEXT NOT NULL,
          fallback_used INTEGER NOT NULL DEFAULT 0,
          message TEXT
        );
        CREATE TABLE collection_run_stats (
          run_id TEXT PRIMARY KEY, fetched_count INTEGER NOT NULL DEFAULT 0,
          parsed_count INTEGER NOT NULL DEFAULT 0,
          unchanged_count INTEGER NOT NULL DEFAULT 0,
          changed_count INTEGER NOT NULL DEFAULT 0,
          new_variant_count INTEGER NOT NULL DEFAULT 0,
          missing_variant_count INTEGER NOT NULL DEFAULT 0,
          error_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE review_items (
          id TEXT PRIMARY KEY, run_id TEXT, issue_type TEXT NOT NULL,
          severity TEXT NOT NULL, message TEXT NOT NULL,
          raw_ref TEXT, entity_ref TEXT, status TEXT NOT NULL DEFAULT 'open',
          created_at TEXT NOT NULL, resolved_at TEXT
        );
        CREATE TABLE institutions (
          id TEXT PRIMARY KEY, sector TEXT NOT NULL, canonical_name TEXT NOT NULL,
          raw_name TEXT NOT NULL, institution_code TEXT, region_sido TEXT,
          region_sigungu TEXT, address TEXT, geo_basis TEXT,
          availability_scope TEXT NOT NULL DEFAULT 'public', active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE products (
          id TEXT PRIMARY KEY, institution_id TEXT NOT NULL,
          product_type TEXT NOT NULL, name TEXT NOT NULL, raw_name TEXT NOT NULL,
          source_product_key TEXT, availability_scope TEXT NOT NULL DEFAULT 'public'
        );
        CREATE TABLE product_variants (
          id TEXT PRIMARY KEY, product_id TEXT NOT NULL, variant_key TEXT NOT NULL,
          term_months INTEGER, interest_method TEXT, payment_method TEXT,
          join_channel TEXT, rate_scope TEXT, amount_min TEXT, amount_max TEXT,
          raw_terms_text TEXT, preference_status TEXT,
          preference_tags_json TEXT
        );
        CREATE TABLE rate_observations (
          id TEXT PRIMARY KEY, variant_id TEXT NOT NULL, run_id TEXT NOT NULL,
          last_run_id TEXT, base_rate TEXT, max_rate TEXT,
          source_effective_at TEXT, validation_status TEXT NOT NULL,
          validation_message TEXT, raw_ref TEXT,
          raw_preference_text TEXT, preference_status TEXT,
          preference_tags_json TEXT
        );
        CREATE TABLE market_indicators (
          id TEXT PRIMARY KEY, source_id TEXT NOT NULL, indicator_key TEXT NOT NULL,
          value TEXT, source_effective_at TEXT, run_id TEXT
        );
        CREATE TABLE outlets (
          id TEXT PRIMARY KEY, institution_id TEXT NOT NULL, name TEXT,
          region_sido TEXT, region_sigungu TEXT, address TEXT, geo_basis TEXT
        );
        """
    )
    conn.commit()
    conn.close()
