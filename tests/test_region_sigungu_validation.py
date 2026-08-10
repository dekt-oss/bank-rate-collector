"""P0-2: 주소의 도로명이 시군구로 승격되지 않게 한다."""

import os
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from rate_monitor.services.region_service import (
    BUSAN_DISTRICTS,
    looks_like_sigungu,
    region_fields,
    split_address,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_real_daegu_road_name_bug_is_not_a_sigungu() -> None:
    """실제 발행 데이터에서 `대구 / 동덕로`가 생긴 경로를 고정한다."""
    assert split_address("대구광역시 동덕로 6") == ("대구", None)
    fields = region_fields("fsb", "대구광역시 동덕로 6")
    assert (fields.sido, fields.sigungu, fields.confidence) == ("대구", None, "medium")


@pytest.mark.parametrize("district", BUSAN_DISTRICTS)
def test_every_busan_district_remains_valid(district: str) -> None:
    """부산 구·군 필터의 16개 계약을 한 건도 잃지 않는다."""
    assert looks_like_sigungu("부산", district)
    fields = region_fields("kfcc", f"부산광역시 {district} 테스트로 1")
    assert (fields.sido, fields.sigungu, fields.confidence) == (
        "부산",
        district,
        "high",
    )


def test_busan_uses_exact_master_not_suffix_only() -> None:
    assert not looks_like_sigungu("부산", "가짜구")
    assert split_address("부산광역시 가짜구 테스트로 1") == ("부산", None)


def test_known_sido_requires_the_right_admin_level() -> None:
    assert looks_like_sigungu("대구", "달서구")
    assert looks_like_sigungu("대구", "군위군")
    assert not looks_like_sigungu("대구", "동덕로")
    assert looks_like_sigungu("경기", "수원시")
    assert not looks_like_sigungu("경기", "영통구")
    assert not looks_like_sigungu("경기", "판교로")


def test_sejong_does_not_invent_a_sigungu_from_the_road() -> None:
    assert split_address("세종특별자치시 도움6로 42") == ("세종", None)


def test_new_unknown_sido_keeps_real_sigungu_but_rejects_road() -> None:
    """행정개편으로 새 시도가 생겨도 이름 목록 갱신 전까지 실제 지역은 보존한다."""
    assert looks_like_sigungu("전남광주통합특별시", "여수시")
    assert not looks_like_sigungu("전남광주통합특별시", "쌍봉로")
    assert split_address("전남광주통합특별시 여수시 쌍봉로 23-2") == (
        "전남광주통합특별시",
        "여수시",
    )


def _alembic(command: str, db_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *command.split()],
        cwd=REPO_ROOT,
        env={
            **os.environ,
            "RATE_MONITOR_DB_URL": f"sqlite+pysqlite:///{db_path}",
            "PYTHONPATH": str(REPO_ROOT / "src"),
        },
        capture_output=True,
        text=True,
    )


def test_migration_cleans_existing_bad_sigungu_but_preserves_evidence(tmp_path: Path) -> None:
    db_path = tmp_path / "region-clean.sqlite3"
    result = _alembic("upgrade e18c4a7d9b30", db_path)
    assert result.returncode == 0, result.stderr

    now = datetime.now(UTC).replace(tzinfo=None).isoformat(sep=" ")
    conn = sqlite3.connect(db_path)
    rows = [
        (
            "bad",
            "대구",
            "동덕로",
            "대구광역시 동덕로 6",
            "head_office",
            "medium",
        ),
        (
            "good-busan",
            "부산",
            "동구",
            "부산광역시 동구 중앙대로 260",
            "outlet_address",
            "high",
        ),
        (
            "future",
            "전남광주통합특별시",
            "여수시",
            "전남광주통합특별시 여수시 쌍봉로 23-2",
            "outlet_address",
            "high",
        ),
    ]
    for pk, sido, sigungu, address, basis, confidence in rows:
        conn.execute(
            "INSERT INTO institutions"
            " (id, sector, canonical_name, normalized_name, region_sido, region_sigungu,"
            "  geo_basis, geo_confidence, address, availability_scope, active,"
            "  first_seen_at, last_seen_at)"
            " VALUES (?, 'savings_bank', ?, ?, ?, ?, ?, ?, ?, 'unknown', 1, ?, ?)",
            (pk, pk, pk, sido, sigungu, basis, confidence, address, now, now),
        )
    conn.commit()
    conn.close()

    result = _alembic("upgrade head", db_path)
    assert result.returncode == 0, result.stderr

    conn = sqlite3.connect(db_path)
    got = {
        row[0]: row[1:]
        for row in conn.execute(
            "SELECT id, address, region_sido, region_sigungu, geo_confidence"
            " FROM institutions WHERE id IN ('bad', 'good-busan', 'future')"
        )
    }
    issue = conn.execute(
        "SELECT issue_type, entity_id, payload_json FROM review_items"
        " WHERE issue_type = 'region_invalid_sigungu'"
    ).fetchall()
    conn.close()

    assert got["bad"] == ("대구광역시 동덕로 6", "대구", None, "medium")
    assert got["good-busan"] == (
        "부산광역시 동구 중앙대로 260",
        "부산",
        "동구",
        "high",
    )
    assert got["future"] == (
        "전남광주통합특별시 여수시 쌍봉로 23-2",
        "전남광주통합특별시",
        "여수시",
        "high",
    )
    assert len(issue) == 1
    assert issue[0][0:2] == ("region_invalid_sigungu", "bad")
    assert "동덕로" in issue[0][2]
