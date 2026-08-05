"""DB 세션과 PRAGMA 설정.

SQLite는 기본적으로 외래키를 강제하지 않는다. 연결마다 켜야 한다.
WAL은 파일 단위 설정이라 한 번만 적용되면 유지된다.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

DEFAULT_DB_PATH = Path("work/rate_monitor.sqlite3")


def _apply_pragmas(dbapi_connection, connection_record) -> None:  # noqa: ANN001, ARG001
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


def create_db_engine(db_path: Path | str = DEFAULT_DB_PATH, *, echo: bool = False) -> Engine:
    """엔진을 만들고 연결마다 PRAGMA를 적용한다.

    `:memory:`를 주면 인메모리 DB를 쓴다 (테스트용).
    """
    if str(db_path) == ":memory:":
        url = "sqlite+pysqlite:///:memory:"
    else:
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite+pysqlite:///{path}"

    engine = create_engine(url, echo=echo, future=True)
    event.listen(engine, "connect", _apply_pragmas)
    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """트랜잭션 경계. 예외가 나면 롤백한다.

    실패한 실행이 최신 정상값을 대체하면 안 되므로 (명세서 v3 §10.3),
    수집 저장은 이 경계 안에서 한 덩어리로 처리한다.
    """
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def pragma(engine: Engine, name: str) -> object:
    """PRAGMA 값을 조회한다. 검증용."""
    with engine.connect() as conn:
        return conn.execute(text(f"PRAGMA {name}")).scalar()
