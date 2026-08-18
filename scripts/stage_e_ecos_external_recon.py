#!/usr/bin/env python3
"""Stage E 외부지표용 한국은행 ECOS read-only 정찰.

통계코드/항목코드를 추정해서 collector에 넣지 않는다. StatisticTableList와
StatisticItemList를 **이름으로** 탐색하여 다음 후보만 보고한다.

1. 예금은행 신규취급액 저축성수신/정기예금 금리
2. 저축은행·상호금융 등 예금취급기관의 수신/예수금 잔액 계열

이 스크립트는 DB·collector·운영 산출물을 수정하지 않는다. 결과 JSON은 CI
artifact로만 사용하며 인증키는 저장 전에 반드시 마스킹한다.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

BASE = "https://ecos.bok.or.kr/api"
KEY_ENV = "ECOS_API_KEY"
OUT = Path("work/stage-e-ecos-external-recon.json")
TIMEOUT = 25
INTERVAL = 0.35

PRICING_TABLE_RE = re.compile(r"가중평균금리|수신금리|예금은행.*금리|여수신금리")
BALANCE_TABLE_RE = re.compile(
    r"비은행.*수신|상호저축은행.*수신|상호금융.*수신|예금취급기관.*수신|금융기관.*수신"
)
PRICING_ITEM_RE = re.compile(r"저축성수신|정기예금|신규취급|수신금리")
BALANCE_ITEM_RE = re.compile(r"수신|예수금|예금|저축은행|상호금융|신용협동|새마을")
MAX_TABLES_PER_PURPOSE = 12


def _mask(value: str, key: str) -> str:
    return value.replace(key, "[REDACTED]") if key else value


def probe(path: str, key: str) -> dict[str, Any]:
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
            try:
                record["payload"] = json.loads(body.decode("utf-8"))
            except json.JSONDecodeError:
                record["text"] = body.decode("utf-8", "replace")[:2000]
    except Exception as error:  # noqa: BLE001 - diagnostic evidence must preserve failures
        record["error"] = f"{type(error).__name__}: {_mask(str(error), key)}"
    time.sleep(INTERVAL)
    return record


def _rows(record: dict[str, Any], container: str) -> list[dict[str, Any]]:
    payload = record.get("payload") or {}
    block = payload.get(container) or {}
    return block.get("row") or []


def _row_text(row: dict[str, Any]) -> str:
    return " | ".join(str(value or "") for value in row.values())


def _table_candidates(
    rows: list[dict[str, Any]], pattern: re.Pattern[str]
) -> list[dict[str, Any]]:
    hits = [row for row in rows if pattern.search(str(row.get("STAT_NAME") or ""))]
    hits.sort(key=lambda row: (str(row.get("STAT_CODE") or ""), str(row.get("STAT_NAME") or "")))
    return hits[:MAX_TABLES_PER_PURPOSE]


def _item_candidates(
    rows: list[dict[str, Any]], pattern: re.Pattern[str]
) -> list[dict[str, Any]]:
    hits = [row for row in rows if pattern.search(_row_text(row))]
    hits.sort(
        key=lambda row: (
            str(row.get("ITEM_CODE") or row.get("ITEM_CODE1") or ""),
            str(row.get("ITEM_NAME") or row.get("ITEM_NAME1") or ""),
        )
    )
    return hits


def _recon_purpose(
    *,
    purpose: str,
    tables: list[dict[str, Any]],
    item_pattern: re.Pattern[str],
    key: str,
) -> dict[str, Any]:
    result: dict[str, Any] = {"purpose": purpose, "tables": [], "item_probes": {}}
    for table in tables:
        code = str(table.get("STAT_CODE") or "")
        if not code:
            continue
        result["tables"].append(table)
        items = probe(f"StatisticItemList/{key}/json/kr/1/1000/{code}", key)
        result["item_probes"][code] = items
        rows = _rows(items, "StatisticItemList")
        result.setdefault("matched_items", {})[code] = _item_candidates(rows, item_pattern)
        print(
            f"{purpose}: {code} {table.get('STAT_NAME')} "
            f"items={len(rows)} matched={len(result['matched_items'][code])}"
        )
    return result


def main() -> int:
    key = os.environ.get(KEY_ENV, "").strip()
    if not key:
        print(f"{KEY_ENV} 환경변수가 없다.", file=sys.stderr)
        return 2

    table_probe = probe(f"StatisticTableList/{key}/json/kr/1/1000", key)
    table_rows = _rows(table_probe, "StatisticTableList")
    if not table_rows:
        print("StatisticTableList가 비어 있다.", file=sys.stderr)
        return 3

    pricing_tables = _table_candidates(table_rows, PRICING_TABLE_RE)
    balance_tables = _table_candidates(table_rows, BALANCE_TABLE_RE)
    print(
        f"tables={len(table_rows)} pricing_candidates={len(pricing_tables)} "
        f"balance_candidates={len(balance_tables)}"
    )

    report: dict[str, Any] = {
        "base": BASE,
        "mode": "read_only_recon",
        "selected_stat_codes": [],
        "selected_item_codes": [],
        "selection_status": "not_selected_until_human_evidence_review",
        "table_list": table_probe,
        "purposes": {
            "deposit_pricing": _recon_purpose(
                purpose="deposit_pricing",
                tables=pricing_tables,
                item_pattern=PRICING_ITEM_RE,
                key=key,
            ),
            "deposit_balances": _recon_purpose(
                purpose="deposit_balances",
                tables=balance_tables,
                item_pattern=BALANCE_ITEM_RE,
                key=key,
            ),
        },
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(report, ensure_ascii=False, indent=2)
    if key in blob:
        blob = blob.replace(key, "[REDACTED]")
    if key in blob:
        print("인증키 마스킹 실패", file=sys.stderr)
        return 4
    OUT.write_text(blob, encoding="utf-8")
    print(f"wrote {OUT} ({len(blob):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
