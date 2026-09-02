"""FSB 정기예금 가입가능지역 membership을 작업 DB에 동기화한다.

production 원본 DB를 직접 대상으로 실행하지 않는다. 운영에서는 기존 snapshot
복원/검증 절차로 만든 work DB에 실행한 뒤 별도 publish gate를 거친다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from datetime import date
from pathlib import Path

from rate_monitor.db.session import DEFAULT_DB_PATH, create_db_engine, make_session_factory
from rate_monitor.services.fsb_availability_service import sync_fsb_availability


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=Path(DEFAULT_DB_PATH))
    parser.add_argument("--as-of", type=date.fromisoformat, default=None)
    args = parser.parse_args()

    engine = create_db_engine(args.db)
    factory = make_session_factory(engine)
    result = asyncio.run(sync_fsb_availability(factory, as_of=args.as_of))
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
