#!/usr/bin/env python3
"""Stage E0 external indicator ECOS discovery probe.

This probe deliberately stops before StatisticSearch. It discovers candidate
StatisticTableList / StatisticItemList contracts for two Strategy calibration
inputs without guessing ECOS codes:

- bank_deposit_rate: deposit-bank new-business deposit rate
- nonbank_deposit_balance: non-bank sector deposit balances

Run only with an ECOS key supplied through the environment. The key is part of
ECOS URL paths, so every persisted URL and error message is redacted.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BASE = "https://ecos.bok.or.kr/api"
KEY_ENV = "ECOS_API_KEY"
OUT = Path("docs/source-recon/strategy-external-indicators-recon.json")
TIMEOUT = 20
INTERVAL = 0.4
TABLE_LIMIT = 1000
ITEM_LIMIT = 1000
MAX_TABLES_PER_TARGET = 16


@dataclass(frozen=True)
class Target:
    name: str
    table_patterns: tuple[str, ...]
    item_patterns: tuple[str, ...]


TARGETS = (
    Target(
        name="bank_deposit_rate",
        table_patterns=(
            r"예금은행.*여수신.*금리",
            r"예금은행.*금리",
            r"여수신.*금리",
        ),
        item_patterns=(r"저축성수신", r"수신금리", r"예금금리"),
    ),
    Target(
        name="nonbank_deposit_balance",
        table_patterns=(
            r"비은행금융기관.*기관별.*수신",
            r"비은행금융기관.*수신",
            r"비은행.*수신",
        ),
        item_patterns=(
            r"상호저축은행",
            r"저축은행",
            r"신용협동조합",
            r"신협",
            r"새마을금고",
            r"상호금융",
            r"농협",
            r"수협",
            r"산림조합",
        ),
    ),
)


def _mask(text: str, key: str) -> str:
    return text.replace(key, "[REDACTED]") if key else text


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
    except Exception as error:  # noqa: BLE001 - diagnostic probe records all failures
        record["error"] = f"{type(error).__name__}: {_mask(str(error), key)}"
    time.sleep(INTERVAL)
    return record


def _rows(record: dict[str, Any], container: str) -> list[dict[str, Any]]:
    payload = record.get("payload") or {}
    block = payload.get(container) or {}
    rows = block.get("row") or []
    return rows if isinstance(rows, list) else []


def _text(row: dict[str, Any], *fields: str) -> str:
    return " ".join(str(row.get(field) or "") for field in fields)


def _pattern_hits(text: str, patterns: tuple[str, ...]) -> list[str]:
    return [pattern for pattern in patterns if re.search(pattern, text, re.IGNORECASE)]


def candidate_tables(
    table_rows: list[dict[str, Any]], target: Target
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for row in table_rows:
        text = _text(row, "STAT_NAME")
        hits = _pattern_hits(text, target.table_patterns)
        if not hits:
            continue
        candidates.append({**row, "_matched_patterns": hits})
    candidates.sort(
        key=lambda row: (
            -len(row.get("_matched_patterns") or []),
            str(row.get("STAT_NAME") or ""),
            str(row.get("STAT_CODE") or ""),
        )
    )
    return candidates[:MAX_TABLES_PER_TARGET]


def candidate_items(
    item_rows: list[dict[str, Any]], target: Target
) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for row in item_rows:
        text = _text(
            row,
            "ITEM_NAME",
            "ITEM_NAME1",
            "ITEM_NAME2",
            "ITEM_NAME3",
            "ITEM_NAME4",
        )
        patterns = _pattern_hits(text, target.item_patterns)
        if patterns:
            hits.append({**row, "_matched_patterns": patterns})
    hits.sort(
        key=lambda row: (
            -len(row.get("_matched_patterns") or []),
            str(row.get("ITEM_NAME") or row.get("ITEM_NAME1") or ""),
        )
    )
    return hits


def _api_result(record: dict[str, Any]) -> dict[str, Any] | None:
    payload = record.get("payload")
    if not isinstance(payload, dict):
        return None
    result = payload.get("RESULT")
    return result if isinstance(result, dict) else None


def discover(key: str) -> dict[str, Any]:
    table_probe = probe(f"StatisticTableList/{key}/json/kr/1/{TABLE_LIMIT}", key)
    table_rows = _rows(table_probe, "StatisticTableList")
    report: dict[str, Any] = {
        "base": BASE,
        "mode": "discovery_only_no_statistic_search",
        "table_list": table_probe,
        "table_count": len(table_rows),
        "targets": {},
    }

    for target in TARGETS:
        tables = candidate_tables(table_rows, target)
        target_report: dict[str, Any] = {
            "candidate_table_count": len(tables),
            "candidate_tables": tables,
            "tables": {},
            "status": "candidates_found" if tables else "no_candidate_table",
        }
        for table in tables:
            code = str(table.get("STAT_CODE") or "").strip()
            if not code:
                continue
            items_probe = probe(
                f"StatisticItemList/{key}/json/kr/1/{ITEM_LIMIT}/{code}",
                key,
            )
            item_rows = _rows(items_probe, "StatisticItemList")
            target_report["tables"][code] = {
                "stat_name": table.get("STAT_NAME"),
                "cycle": table.get("CYCLE"),
                "api_result": _api_result(items_probe),
                "item_count": len(item_rows),
                "item_hits": candidate_items(item_rows, target),
                "item_list": items_probe,
            }
        report["targets"][target.name] = target_report
    return report


def main() -> int:
    key = os.environ.get(KEY_ENV, "").strip()
    if not key:
        print(f"{KEY_ENV} 환경변수가 없다. 인증키는 환경변수로만 받는다.", file=sys.stderr)
        return 2

    report = discover(key)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(report, ensure_ascii=False, indent=2)
    if key in blob:
        blob = blob.replace(key, "[REDACTED]")
        print("경고: 인증키가 결과에 남아 저장 직전에 제거했다.")
    OUT.write_text(blob, encoding="utf-8")

    print(f"통계표 {report['table_count']}개 확인")
    for target in TARGETS:
        result = report["targets"][target.name]
        print(
            f"{target.name}: tables={result['candidate_table_count']} "
            f"status={result['status']}"
        )
        for code, table in result["tables"].items():
            print(
                f"  {code} {table['stat_name']} cycle={table['cycle']} "
                f"items={table['item_count']} hits={len(table['item_hits'])}"
            )
    print(f"기록: {OUT} ({len(blob):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
