#!/usr/bin/env python3
"""D0 read-only ECOS recon for market-funding data.

This probe answers source-contract questions before any new series is persisted:

- Do non-bank sector deposit-rate tables/series actually exist?
- Do deposit-bank balance tables expose term deposits / installment savings?
- What are the latest observed values, units, ranges, and response fields?
- What RESULT code does ECOS return for an empty historical range?

The script never opens the rate-monitor DB. ECOS credentials are accepted only
through ECOS_API_KEY and are redacted from every persisted string.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.request
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

BASE = "https://ecos.bok.or.kr/api"
KEY_ENV = "ECOS_API_KEY"
OUT = Path("docs/source-recon/market-funding-d0-ecos-recon.json")
TIMEOUT = 25
INTERVAL = 0.35
TABLE_LIMIT = 1000
ITEM_LIMIT = 1000
SERIES_LIMIT = 300
START_MONTH = "202401"
END_MONTH = "202612"
EMPTY_START = "190001"
EMPTY_END = "190012"
MAX_TABLES_PER_TARGET = 20
MAX_ITEMS_PER_TABLE = 40
MAX_PROBES_PER_TARGET = 24


@dataclass(frozen=True)
class Target:
    key: str
    table_patterns: tuple[str, ...]
    item_patterns: tuple[str, ...]
    table_exclude_patterns: tuple[str, ...] = ()


TARGETS = (
    Target(
        key="nonbank_deposit_rates",
        table_patterns=(
            r"비은행.*수신.*금리",
            r"비은행금융기관.*금리",
            r"비은행.*여수신.*금리",
            r"상호저축은행.*금리",
            r"신용협동조합.*금리",
            r"새마을금고.*금리",
        ),
        item_patterns=(
            r"상호저축은행",
            r"저축은행",
            r"신용협동조합",
            r"신협",
            r"상호금융",
            r"새마을금고",
            r"정기예금",
            r"정기예탁금",
            r"1년",
        ),
        table_exclude_patterns=(r"대출",),
    ),
    Target(
        key="bank_deposit_balances",
        table_patterns=(
            r"예금은행.*종별.*예금",
            r"예금은행.*예금.*종류",
            r"예금은행.*수신.*종별",
            r"예금은행.*예금",
        ),
        item_patterns=(
            r"정기예금",
            r"정기적금",
            r"저축성예금",
            r"총예금",
            r"예금총액",
        ),
        table_exclude_patterns=(r"회전율",),
    ),
)


# Current trusted-main exact contracts. They are probed again as a runtime
# baseline so D0 evidence contains actual current values, not only candidates.
KNOWN_SERIES = (
    ("bank_savings_deposit_rate", "121Y002", "BEABAA2", "M"),
    ("bank_pure_savings_deposit_rate", "121Y002", "BEABAA21", "M"),
    ("bank_term_deposit_1y_rate", "121Y002", "BEABAA2118", "M"),
    ("savings_bank_deposit_balance", "111Y007", "1120600", "M"),
    ("credit_union_deposit_balance", "111Y007", "1120700", "M"),
    ("broad_mutual_finance_deposit_balance", "111Y007", "1120800", "M"),
    ("kfcc_deposit_balance", "111Y007", "1121000", "M"),
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


def _container_rows(record: dict[str, Any], container: str) -> list[dict[str, Any]]:
    payload = record.get("payload")
    if not isinstance(payload, dict):
        return []
    block = payload.get(container)
    if not isinstance(block, dict):
        return []
    rows = block.get("row") or []
    return rows if isinstance(rows, list) else []


def _api_result(record: dict[str, Any]) -> dict[str, Any] | None:
    payload = record.get("payload")
    if not isinstance(payload, dict):
        return None
    result = payload.get("RESULT")
    return result if isinstance(result, dict) else None


def _pattern_hits(text: str, patterns: tuple[str, ...]) -> list[str]:
    return [pattern for pattern in patterns if re.search(pattern, text, re.IGNORECASE)]


def _row_text(row: dict[str, Any]) -> str:
    fields = (
        "STAT_NAME",
        "ITEM_NAME",
        "ITEM_NAME1",
        "ITEM_NAME2",
        "ITEM_NAME3",
        "ITEM_NAME4",
    )
    return " ".join(str(row.get(field) or "") for field in fields)


def _item_code(row: dict[str, Any]) -> str | None:
    for field in ("ITEM_CODE", "ITEM_CODE1"):
        value = str(row.get(field) or "").strip()
        if value:
            return value
    return None


def _item_name(row: dict[str, Any]) -> str | None:
    for field in ("ITEM_NAME", "ITEM_NAME1"):
        value = str(row.get(field) or "").strip()
        if value:
            return value
    return None


def _candidate_tables(rows: list[dict[str, Any]], target: Target) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for row in rows:
        name = str(row.get("STAT_NAME") or "")
        if _pattern_hits(name, target.table_exclude_patterns):
            continue
        hits = _pattern_hits(name, target.table_patterns)
        if hits:
            found.append({**row, "_matched_patterns": hits})
    found.sort(
        key=lambda row: (
            -len(row.get("_matched_patterns") or []),
            str(row.get("STAT_NAME") or ""),
            str(row.get("STAT_CODE") or ""),
        )
    )
    return found[:MAX_TABLES_PER_TARGET]


def _candidate_items(
    rows: list[dict[str, Any]], target: Target, cycle: str
) -> list[dict[str, Any]]:
    """Return unique item codes for the table's actual cycle.

    ECOS StatisticItemList can return the same item code three times for A/M/Q.
    D0 is a monthly-series recon, so accepting all three creates duplicate probes
    and makes the artifact look like there are more distinct series than exist.
    """
    by_code: dict[str, dict[str, Any]] = {}
    for row in rows:
        row_cycle = str(row.get("CYCLE") or "").strip()
        if row_cycle and row_cycle != cycle:
            continue
        hits = _pattern_hits(_row_text(row), target.item_patterns)
        code = _item_code(row)
        if hits and code:
            candidate = {**row, "_matched_patterns": hits}
            prior = by_code.get(code)
            if prior is None or len(hits) > len(prior.get("_matched_patterns") or []):
                by_code[code] = candidate
    found = list(by_code.values())
    found.sort(
        key=lambda row: (
            -len(row.get("_matched_patterns") or []),
            str(_item_name(row) or ""),
            str(_item_code(row) or ""),
        )
    )
    return found[:MAX_ITEMS_PER_TABLE]


def _series_rows(record: dict[str, Any]) -> list[dict[str, Any]]:
    return _container_rows(record, "StatisticSearch")


def _series_summary(record: dict[str, Any]) -> dict[str, Any]:
    rows = sorted(_series_rows(record), key=lambda row: str(row.get("TIME") or ""))
    values: list[Decimal] = []
    max_scale = 0
    for row in rows:
        raw = str(row.get("DATA_VALUE") or "").strip()
        try:
            value = Decimal(raw)
        except (InvalidOperation, ValueError):
            continue
        values.append(value)
        exponent = value.as_tuple().exponent
        max_scale = max(max_scale, -exponent if exponent < 0 else 0)
    block = (record.get("payload") or {}).get("StatisticSearch") or {}
    return {
        "api_result": _api_result(record),
        "list_total_count": block.get("list_total_count") if isinstance(block, dict) else None,
        "row_count": len(rows),
        "first_time": rows[0].get("TIME") if rows else None,
        "last_time": rows[-1].get("TIME") if rows else None,
        "min_value": str(min(values)) if values else None,
        "max_value": str(max(values)) if values else None,
        "max_decimal_places": max_scale,
        "row_keys": sorted({key for row in rows for key in row}) if rows else [],
        "latest_rows": rows[-12:],
        "response_meta": {
            "status": record.get("status"),
            "bytes": record.get("bytes"),
            "error": record.get("error"),
        },
    }


def _probe_series(key: str, stat: str, cycle: str, item: str) -> dict[str, Any]:
    path = (
        f"StatisticSearch/{key}/json/kr/1/{SERIES_LIMIT}"
        f"/{stat}/{cycle}/{START_MONTH}/{END_MONTH}/{item}"
    )
    return _series_summary(probe(path, key))


def discover(key: str) -> dict[str, Any]:
    table_record = probe(f"StatisticTableList/{key}/json/kr/1/{TABLE_LIMIT}", key)
    table_rows = _container_rows(table_record, "StatisticTableList")
    report: dict[str, Any] = {
        "mode": "read_only_no_db_write",
        "base": BASE,
        "range": {"from": START_MONTH, "to": END_MONTH},
        "table_count": len(table_rows),
        "targets": {},
        "known_series": {},
        "empty_range_probe": {},
    }

    for target in TARGETS:
        tables = _candidate_tables(table_rows, target)
        target_report: dict[str, Any] = {
            "target": asdict(target),
            "candidate_table_count": len(tables),
            "candidate_tables": [],
            "series_probes": [],
        }
        probe_count = 0
        for table in tables:
            stat = str(table.get("STAT_CODE") or "").strip()
            cycle = str(table.get("CYCLE") or "M").strip() or "M"
            item_record = probe(
                f"StatisticItemList/{key}/json/kr/1/{ITEM_LIMIT}/{stat}", key
            )
            items = _candidate_items(
                _container_rows(item_record, "StatisticItemList"), target, cycle
            )
            target_report["candidate_tables"].append(
                {
                    "stat_code": stat,
                    "stat_name": table.get("STAT_NAME"),
                    "cycle": cycle,
                    "item_api_result": _api_result(item_record),
                    "item_hits": items,
                }
            )
            for item in items:
                if probe_count >= MAX_PROBES_PER_TARGET:
                    break
                code = _item_code(item)
                if not code or cycle != "M":
                    continue
                probe_count += 1
                target_report["series_probes"].append(
                    {
                        "stat_code": stat,
                        "stat_name": table.get("STAT_NAME"),
                        "cycle": cycle,
                        "item_code": code,
                        "item_name": _item_name(item),
                        "summary": _probe_series(key, stat, cycle, code),
                    }
                )
        report["targets"][target.key] = target_report

    for name, stat, item, cycle in KNOWN_SERIES:
        report["known_series"][name] = {
            "stat_code": stat,
            "item_code": item,
            "cycle": cycle,
            "summary": _probe_series(key, stat, cycle, item),
        }

    # Learn the real ECOS HTTP-200 RESULT contract for a pre-history range.
    name, stat, item, cycle = KNOWN_SERIES[0]
    empty_path = (
        f"StatisticSearch/{key}/json/kr/1/10"
        f"/{stat}/{cycle}/{EMPTY_START}/{EMPTY_END}/{item}"
    )
    empty_record = probe(empty_path, key)
    report["empty_range_probe"] = {
        "series": name,
        "range": {"from": EMPTY_START, "to": EMPTY_END},
        "api_result": _api_result(empty_record),
        "row_count": len(_series_rows(empty_record)),
        "response_meta": {
            "status": empty_record.get("status"),
            "bytes": empty_record.get("bytes"),
            "error": empty_record.get("error"),
        },
    }
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

    print(f"ECOS 통계표 {report['table_count']}개 확인")
    for target in TARGETS:
        data = report["targets"][target.key]
        successful = sum(
            1
            for probe_item in data["series_probes"]
            if probe_item["summary"]["row_count"] > 0
            and probe_item["summary"]["api_result"] is None
        )
        print(
            f"{target.key}: tables={data['candidate_table_count']} "
            f"probes={len(data['series_probes'])} data_series={successful}"
        )
    for name, data in report["known_series"].items():
        summary = data["summary"]
        print(
            f"known {name}: rows={summary['row_count']} "
            f"range={summary['first_time']}..{summary['last_time']} "
            f"min={summary['min_value']} max={summary['max_value']}"
        )
    print(f"empty range result={report['empty_range_probe']['api_result']}")
    print(f"기록: {OUT} ({len(blob):,} bytes)")

    # Known contracts must still work. Candidate targets are discovery results,
    # so absence is evidence rather than a workflow failure.
    failed_known = [
        name
        for name, data in report["known_series"].items()
        if data["summary"]["row_count"] == 0 or data["summary"]["api_result"] is not None
    ]
    if failed_known:
        print(f"known contract 실패: {failed_known}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
