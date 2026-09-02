"""Alembic 환경.

DB URL은 RATE_MONITOR_DB_URL 환경변수를 우선하고, 없으면 작업용 경로
(work/rate_monitor.sqlite3)를 쓴다. publish/ 스냅샷에는 마이그레이션을
직접 걸지 않는다 — 스냅샷은 work/에서 복사되어 만들어진다 (명세서 v3.1 §3).
"""

import os
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, event, pool

# 별도 모델 모듈도 Alembic metadata registry에 등록한다. import 자체가 목적이다.
import rate_monitor.db.availability_models  # noqa: F401
import rate_monitor.db.institution_funding_models  # noqa: F401
from rate_monitor.db.models import Base
from rate_monitor.db.session import DEFAULT_DB_PATH

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _enable_foreign_keys(dbapi_connection, connection_record) -> None:  # noqa: ANN001, ARG001
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def _database_url() -> str:
    url = os.environ.get("RATE_MONITOR_DB_URL")
    if url:
        return url
    path = Path(DEFAULT_DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite+pysqlite:///{path}"


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)

    # SQLite는 연결마다 외래키를 켜야 한다. 연결 이벤트로 붙여야 alembic의
    # 트랜잭션 관리에 끼어들지 않는다. 마이그레이션 컨텍스트 밖에서 직접
    # PRAGMA를 실행하면 버전 기록이 커밋되지 않는다.
    event.listen(connectable, "connect", _enable_foreign_keys)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # SQLite는 ALTER가 제한적이라 배치 모드를 켠다.
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
