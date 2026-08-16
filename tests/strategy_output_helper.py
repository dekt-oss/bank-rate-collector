"""전략 UI 계약 테스트용 실제 build_site 산출물 helper."""

import asyncio
import tempfile
from pathlib import Path

from rate_monitor.db import models as m
from rate_monitor.db.session import create_db_engine, make_session_factory
from rate_monitor.domain.schemas import CollectionRequest
from rate_monitor.services.collection_service import collect_source
from rate_monitor.services.site_service import DEFAULT_STRATEGY_TEMPLATE, build_site
from tests.test_collection_service import REAL, FixtureAdapter

_CACHE: str | None = None
_TMP: tempfile.TemporaryDirectory[str] | None = None


def built_strategy_html() -> str:
    """실제 수집 fixture → build_site → strategy.html을 한 번만 생성한다."""
    global _CACHE, _TMP
    if _CACHE is not None:
        return _CACHE

    _TMP = tempfile.TemporaryDirectory(prefix="strategy-output-")
    root = Path(_TMP.name)
    db = root / "strategy.sqlite3"
    engine = create_db_engine(db)
    m.Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    asyncio.run(
        collect_source(
            FixtureAdapter([REAL]),
            CollectionRequest(source_id="finlife"),
            factory,
            raw_root=root / "raw",
        )
    )
    engine.dispose()

    out = root / "site-public"
    build_site(db, out_dir=out, strategy_template_path=DEFAULT_STRATEGY_TEMPLATE)
    _CACHE = (out / "strategy.html").read_text(encoding="utf-8")
    return _CACHE
