"""지역 데이터 모델 (v4 §4).

주소를 자르는 규칙이 예전에는 세 벌이었다 — 대시보드 SQL, `kfcc/parser`,
`fsb/parser`. 한쪽만 고치면 수집한 값과 보이는 값이 갈라지고, 그 차이는
집계가 어긋날 때까지 안 보인다. 여기서 한 벌인지 확인한다.
"""

import os
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from rate_monitor.domain.enums import GeoBasis
from rate_monitor.services.region_service import (
    is_known_sido,
    region_fields,
    split_address,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


# ── 규칙이 한 벌인가 ────────────────────────────────────────────────────


def test_every_parser_uses_the_same_splitter() -> None:
    """같은 주소를 세 곳에 넣으면 같은 답이 나와야 한다."""
    from rate_monitor.collectors.kfcc.parser import split_region

    address = "부산광역시 동구 중앙대로 260"
    assert split_region(address) == split_address(address) == ("부산", "동구")


def test_the_old_second_copy_is_gone() -> None:
    """대시보드가 SQL에서 주소를 자르던 코드가 남아 있으면 안 된다.

    남겨 두면 다음 사람이 그쪽을 고치고, 칸은 그대로 옛 값을 들고 있는다.
    """
    source = (REPO_ROOT / "src/rate_monitor/services/dashboard_service.py").read_text(
        encoding="utf-8"
    )
    assert "INSTR(" not in source, "주소를 SQL에서 자르는 코드가 남아 있다"
    assert "SIDO_ALIASES" not in source, "시도 별칭표가 두 벌이다"


# ── 네 칸의 값 ──────────────────────────────────────────────────────────


def test_head_office_never_claims_a_district() -> None:
    """본점이 동구에 있다는 것과 동구에서 그 금리를 받는 것은 다르다."""
    outlet = region_fields("kfcc", "부산광역시 동구 중앙대로 260")
    head = region_fields("fsb", "부산광역시 동구 중앙대로 260")

    assert outlet.sigungu == head.sigungu == "동구"
    assert outlet.confidence == "high"
    assert head.confidence == "medium"
    assert head.basis is GeoBasis.HEAD_OFFICE


def test_an_unknown_source_gets_no_basis() -> None:
    """기본값을 outlet_address로 두면 근거 없는 값이 근거 있어 보인다."""
    assert region_fields("nh_local", "부산 중구 대청로 101-1").basis is GeoBasis.NONE


def test_a_missing_address_stays_empty() -> None:
    fields = region_fields("finlife", None)
    assert (fields.sido, fields.sigungu, fields.confidence) == (None, None, "none")


def test_a_real_address_with_an_unknown_sido_is_kept() -> None:
    """실측값이다. 버리면 여수시라는 진짜 지역 정보가 같이 사라진다."""
    fields = region_fields("kfcc", "전남광주통합특별시 여수시 쌍봉로 23-2")
    assert (fields.sido, fields.sigungu) == ("전남광주통합특별시", "여수시")
    assert not is_known_sido(fields.sido), "별칭표가 모르는 이름이라 표시 대상이다"


# ── 마이그레이션 ────────────────────────────────────────────────────────


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


@pytest.fixture()
def seeded_db(tmp_path: Path) -> Path:
    """옛 스키마(지역 칸 없음)로 만든 뒤 행을 넣어 둔 DB."""
    db_path = tmp_path / "seed.sqlite3"
    result = _alembic("upgrade 31f56a26f628", db_path)
    assert result.returncode == 0, result.stderr

    now = datetime.now(UTC).replace(tzinfo=None).isoformat(sep=' ')
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO sources (id, name, sector, mode, source_role, trust_level,"
        " priority, base_reference, enabled, policy_status, coverage_status,"
        " parser_version, created_at, updated_at) VALUES"
        " ('kfcc', '새마을금고', 'kfcc', 'html', 'secondary_official',"
        " 'official_direct', 10, 'x', 1, 'allowed', 'partial', '0.1.0', ?, ?)",
        (now, now),
    )
    rows = [
        ("i-1", "부산광역시 동구 중앙대로 260"),   # 읽힌다
        ("i-2", None),                              # 주소가 없다
        ("i-3", "신동해빌딩 1,2,3층"),              # 주소가 아니다
    ]
    for pk, address in rows:
        conn.execute(
            "INSERT INTO institutions (id, sector, canonical_name, normalized_name,"
            " address, availability_scope, active, first_seen_at, last_seen_at)"
            " VALUES (?, 'kfcc', ?, ?, ?, 'unknown', 1, ?, ?)",
            (pk, pk, pk, address, now, now),
        )
        conn.execute(
            "INSERT INTO source_entity_links (id, source_id, entity_type,"
            " source_entity_key, entity_id, confidence, match_method, created_at,"
            " updated_at) VALUES (?, 'kfcc', 'institution', ?, ?, 1.0, 'exact_code', ?, ?)",
            (f"l-{pk}", pk, pk, now, now),
        )
    conn.commit()
    conn.close()
    return db_path


def test_backfill_fills_what_it_can_and_leaves_the_rest(seeded_db: Path) -> None:
    result = _alembic("upgrade head", seeded_db)
    assert result.returncode == 0, result.stderr

    conn = sqlite3.connect(seeded_db)
    got = dict(
        (row[0], row[1:])
        for row in conn.execute(
            "SELECT id, region_sido, region_sigungu, geo_basis, geo_confidence"
            "  FROM institutions ORDER BY id"
        )
    )
    assert got["i-1"] == ("부산", "동구", "outlet_address", "high")
    # 주소가 없으면 지어내지 않는다. 근거는 원천에서 오므로 그대로 남는다.
    assert got["i-2"] == (None, None, "outlet_address", "none")
    # 주소처럼 안 생긴 값도 버리지 않는다. 버리면 그 기관이 화면에서 사라진다.
    assert got["i-3"] == ("신동해빌딩", "1,2,3층", "outlet_address", "high")

    issues = dict(
        conn.execute(
            "SELECT issue_type, COUNT(*) FROM review_items"
            " WHERE issue_type LIKE 'region_%' GROUP BY 1"
        )
    )
    conn.close()
    # 조용히 NULL만 남으면 "원래 없는 것"과 "채우다 실패한 것"이 구별되지 않는다.
    assert issues == {"region_unresolved": 1, "region_unknown_sido": 1}


def test_downgrade_puts_the_schema_back(seeded_db: Path) -> None:
    """되돌릴 수 없는 마이그레이션은 운영에서 못 쓴다."""
    _alembic("upgrade head", seeded_db)
    result = _alembic("downgrade 31f56a26f628", seeded_db)
    assert result.returncode == 0, result.stderr

    conn = sqlite3.connect(seeded_db)
    columns = {r[1] for r in conn.execute("PRAGMA table_info(institutions)")}
    conn.close()
    assert "region_sido" not in columns
    assert "geo_basis" not in columns


def test_indexes_exist_after_migration(seeded_db: Path) -> None:
    """구·군 필터가 매번 전체 훑기를 하면 화면이 느려진다."""
    _alembic("upgrade head", seeded_db)
    conn = sqlite3.connect(seeded_db)
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    conn.close()
    for table in ("institutions", "outlets"):
        assert f"ix_{table}_region_sido" in names
        assert f"ix_{table}_region_sigungu" in names
