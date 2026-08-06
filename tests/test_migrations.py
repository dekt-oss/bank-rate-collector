"""Alembic 마이그레이션 재현성 검증 (P1-A 게이트 §12.1).

수동 확인은 다음 사람이 반복하지 못한다. 실제로 돌려서 확인한다.
"""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_TABLE_COUNT = 14


def _alembic(command: str, db_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "alembic", command.split()[0], *command.split()[1:]],
        cwd=REPO_ROOT,
        env={
            **os.environ,
            "RATE_MONITOR_DB_URL": f"sqlite+pysqlite:///{db_path}",
            "PYTHONPATH": str(REPO_ROOT / "src"),
        },
        capture_output=True,
        text=True,
    )


def _tables(db_path: Path) -> set[str]:
    if not db_path.exists():
        return set()
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' AND name != 'alembic_version'"
        )
        return {r[0] for r in rows}
    finally:
        conn.close()


def _version(db_path: Path) -> list[str]:
    conn = sqlite3.connect(db_path)
    try:
        return [r[0] for r in conn.execute("SELECT version_num FROM alembic_version")]
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "migration.sqlite3"


def test_upgrade_creates_fourteen_tables(db_path: Path) -> None:
    result = _alembic("upgrade head", db_path)
    assert result.returncode == 0, result.stderr
    assert len(_tables(db_path)) == EXPECTED_TABLE_COUNT
    assert _version(db_path), "버전이 기록되지 않았다"


def test_downgrade_removes_everything(db_path: Path) -> None:
    _alembic("upgrade head", db_path)
    result = _alembic("downgrade base", db_path)
    assert result.returncode == 0, result.stderr
    assert _tables(db_path) == set()
    assert _version(db_path) == []


def test_migration_is_reproducible(db_path: Path) -> None:
    """올렸다 내렸다 다시 올려도 같은 결과. 재현성이 없으면 운영에서 못 쓴다."""
    _alembic("upgrade head", db_path)
    first = _tables(db_path)
    _alembic("downgrade base", db_path)
    result = _alembic("upgrade head", db_path)
    assert result.returncode == 0, result.stderr
    assert _tables(db_path) == first
    assert len(first) == EXPECTED_TABLE_COUNT


def test_migration_matches_models(db_path: Path) -> None:
    """마이그레이션 결과가 모델 정의와 일치하는지.

    autogenerate가 놓친 테이블이 있으면 여기서 잡힌다.
    """
    from rate_monitor.db.models import Base

    _alembic("upgrade head", db_path)
    assert _tables(db_path) == set(Base.metadata.tables)


def test_partial_unique_index_survives_migration(db_path: Path) -> None:
    """활성 매핑 부분 유니크 인덱스가 마이그레이션으로도 만들어지는지."""
    _alembic("upgrade head", db_path)
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' "
            "AND name='uq_source_entity_links_active'"
        ).fetchone()
    finally:
        conn.close()
    assert row is not None, "부분 유니크 인덱스가 만들어지지 않았다"
    sql = row[0].upper()
    assert "UNIQUE" in sql
    assert "VALID_TO IS NULL" in sql
