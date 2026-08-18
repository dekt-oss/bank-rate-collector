#!/usr/bin/env python3
"""검증된 ECOS 예금시장 월별지표 6계열을 market_indicators에 수집한다."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from rate_monitor.collectors.bok_ecos.deposit_market_adapter import (
    BokEcosDepositMarketAdapter,
)
from rate_monitor.db.session import create_db_engine, make_session_factory
from rate_monitor.domain.schemas import CollectionRequest
from rate_monitor.services.indicator_service import collect_indicator


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--raw-root", default="data/raw")
    args = parser.parse_args()

    engine = create_db_engine(Path(args.db))
    factory = make_session_factory(engine)
    try:
        adapter = BokEcosDepositMarketAdapter()
        result = asyncio.run(
            collect_indicator(
                adapter,
                CollectionRequest(source_id=adapter.source_id),
                factory,
                raw_root=Path(args.raw_root),
            )
        )
    finally:
        engine.dispose()

    print(f"run_id      : {result.run_id}")
    print(f"status      : {result.status}")
    print(f"raw/parsed  : {result.fetched} / {result.parsed}")
    print(f"새/그대로   : {result.stored} / {result.unchanged}")
    print(f"warnings    : {result.warnings}")
    print(f"message     : {result.message}")
    return 0 if result.status in ("success", "partial", "no_change") else 1


if __name__ == "__main__":
    raise SystemExit(main())
