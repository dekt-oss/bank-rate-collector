#!/usr/bin/env python3
"""Stage E ECOS 후보의 실제 월별 StatisticSearch 응답을 검증한다.

후보 코드는 metadata recon의 실제 항목명 검토 후에만 여기로 승격한다. 이 단계도
read-only이며 DB/collector를 수정하지 않는다. 응답 항목명·단위·월 주기·최신값이
예상과 다르면 fail closed한다.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

BASE = "https://ecos.bok.or.kr/api"
KEY_ENV = "ECOS_API_KEY"
OUT = Path("docs/source-recon/stage-e-external-indicators-series-runtime.json")
TIMEOUT = 25
INTERVAL = 0.35
START = "202401"
END = "202612"

SERIES = (
    {
        "feature": "commercial_bank_1y_new_business_rate",
        "stat_code": "121Y002",
        "item_code": "BEABAA2118",
        "expected_name": "정기예금(1년)",
        "expected_unit": "연리%",
    },
    {
        "feature": "savings_bank_1y_new_business_rate",
        "stat_code": "121Y004",
        "item_code": "BEBBBE01",
        "expected_name": "상호저축은행-정기예금(1년)",
        "expected_unit": "연리%",
    },
    {
        "feature": "savings_bank_deposit_balance",
        "stat_code": "111Y007",
        "item_code": "1120600",
        "expected_name": "상호저축은행",
        "expected_unit": "십억원",
    },
    {
        "feature": "credit_union_deposit_balance",
        "stat_code": "111Y007",
        "item_code": "1120700",
        "expected_name": "신용협동조합",
        "expected_unit": "십억원",
    },
    {
        "feature": "mutual_finance_deposit_balance",
        "stat_code": "111Y007",
        "item_code": "1120800",
        "expected_name": "상호금융",
        "expected_unit": "십억원",
    },
    {
        "feature": "kfcc_deposit_balance",
        "stat_code": "111Y007",
        "item_code": "1121000",
        "expected_name": "새마을금고",
        "expected_unit": "십억원",
    },
)


def _mask(value: str, key: str) -> str:
    return value.replace(key, "[REDACTED]") if key else value


def _probe(stat_code: str, item_code: str, key: str) -> dict[str, Any]:
    path = (
        f"StatisticSearch/{key}/json/kr/1/1000/{stat_code}/M/"
        f"{START}/{END}/{item_code}"
    )
    url = f"{BASE}/{path}"
    record: dict[str, Any] = {"url": _mask(url, key)}
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "rate-monitor/1 (+public rate disclosure collector)"},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            body = response.read()
            record["status"] = response.status
            record["bytes"] = len(body)
            record["payload"] = json.loads(body.decode("utf-8"))
    except Exception as error:  # noqa: BLE001 - preserve external evidence failures
        record["error"] = f"{type(error).__name__}: {_mask(str(error), key)}"
    time.sleep(INTERVAL)
    return record


def _rows(record: dict[str, Any]) -> list[dict[str, Any]]:
    return ((record.get("payload") or {}).get("StatisticSearch") or {}).get("row") or []


def _item_name(row: dict[str, Any]) -> str:
    names = [
        str(row.get(key) or "")
        for key in ("ITEM_NAME1", "ITEM_NAME2", "ITEM_NAME3", "ITEM_NAME")
    ]
    return " | ".join(name for name in names if name)


def _public_point(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "time": row.get("TIME"),
        "value": row.get("DATA_VALUE"),
        "unit": row.get("UNIT_NAME"),
        "item_name1": row.get("ITEM_NAME1"),
        "item_name2": row.get("ITEM_NAME2"),
        "item_name3": row.get("ITEM_NAME3"),
    }


def main() -> int:
    key = os.environ.get(KEY_ENV, "").strip()
    if not key:
        print(f"{KEY_ENV} 환경변수가 없다.", file=sys.stderr)
        return 2

    verified: list[dict[str, Any]] = []
    for spec in SERIES:
        record = _probe(spec["stat_code"], spec["item_code"], key)
        if record.get("error"):
            print(f"{spec['feature']}: {record['error']}", file=sys.stderr)
            return 3
        rows = _rows(record)
        if not rows:
            print(f"{spec['feature']}: 시계열이 비어 있다.", file=sys.stderr)
            return 4
        if any(str(row.get("UNIT_NAME") or "") != spec["expected_unit"] for row in rows):
            print(f"{spec['feature']}: 단위 불일치", file=sys.stderr)
            return 5
        if any(spec["expected_name"] not in _item_name(row) for row in rows):
            print(f"{spec['feature']}: 항목명 불일치", file=sys.stderr)
            return 6
        if any(len(str(row.get("TIME") or "")) != 6 for row in rows):
            print(f"{spec['feature']}: 월 주기 TIME 형식 불일치", file=sys.stderr)
            return 7
        latest = rows[-1]
        verified.append(
            {
                **spec,
                "cycle": "M",
                "verified": True,
                "point_count": len(rows),
                "first": _public_point(rows[0]),
                "latest": _public_point(latest),
                "recent_points": [_public_point(row) for row in rows[-12:]],
            }
        )
        print(
            f"{spec['feature']}: {latest.get('TIME')}={latest.get('DATA_VALUE')} "
            f"{latest.get('UNIT_NAME')} points={len(rows)}"
        )

    report = {
        "source": "BOK ECOS Open API",
        "mode": "read_only_series_verification",
        "window": {"start": START, "end": END, "cycle": "M"},
        "all_verified": all(item["verified"] for item in verified),
        "series": verified,
        "production_collector_status": "not_implemented",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if key in blob:
        print("검증 산출물에 인증키가 남아 있다.", file=sys.stderr)
        return 8
    OUT.write_text(blob, encoding="utf-8")
    print(f"wrote {OUT} ({len(blob):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
