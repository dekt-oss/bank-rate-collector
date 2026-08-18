"""`bok_ecos_macro` production wiring 전용 얇은 CLI.

기존 `rate-monitor collect --source bok_ecos` 경로를 건드리지 않고 새 operational
source를 독립 실행하기 위한 진입점이다. 실제 저장 로직은 기존
``indicator_service.collect_indicator``를 그대로 사용한다.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from rate_monitor.collectors.bok_ecos.macro_adapter import BokEcosMacroAdapter
from rate_monitor.db.session import DEFAULT_DB_PATH, create_db_engine, make_session_factory
from rate_monitor.domain.schemas import CollectionRequest
from rate_monitor.services.collection_service import DEFAULT_RAW_ROOT
from rate_monitor.services.indicator_service import collect_indicator


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="한국은행 수신시장 거시지표 수집")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--raw-root", default=str(DEFAULT_RAW_ROOT))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    engine = create_db_engine(args.db)
    factory = make_session_factory(engine)
    adapter = BokEcosMacroAdapter()
    result = asyncio.run(
        collect_indicator(
            adapter,
            CollectionRequest(source_id=adapter.source_id),
            factory,
            raw_root=Path(args.raw_root),
        )
    )

    print(f"run_id      : {result.run_id}")
    print(f"status      : {result.status}")
    print(f"raw/parsed  : {result.fetched} / {result.parsed}")
    print(f"새/그대로   : {result.stored} / {result.unchanged}")
    print(f"warnings    : {result.warnings}")
    print(f"message     : {result.message}")
    return 0 if result.status in ("success", "partial", "no_change") else 1


if __name__ == "__main__":
    raise SystemExit(main())
