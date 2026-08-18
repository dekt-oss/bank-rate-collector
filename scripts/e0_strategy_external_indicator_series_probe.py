#!/usr/bin/env python3
"""Stage E0-2 exact ECOS series probe.

The table/item codes in this file are not guesses. They were discovered from a
trusted-main ECOS StatisticTableList/StatisticItemList run on 2026-08-18:

- run 32135388199
- artifact 9323770229
- evidence: docs/source-recon/strategy-external-indicators-e0-discovery.md

This script is still diagnostic-only. It reads StatisticSearch and writes a
redacted report artifact; it never writes the production DB.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

BASE = "https://ecos.bok.or.kr/api"
KEY_ENV = "ECOS_API_KEY"
OUT = Path("docs/source-recon/strategy-external-indicator-series-probe.json")
TIMEOUT = 20
INTERVAL = 0.4
PAGE_SIZE = 1000
START_MONTH = "202301"
END_MONTH = "202612"


@dataclass(frozen=True)
class SeriesSpec:
    key: str
    stat_code: str
    item_code: str
    cycle: str
    expected_name: str
    expected_unit: str
    role: str


SERIES = (
    SeriesSpec(
        key="bank_savings_deposit_rate",
        stat_code="121Y002",
        item_code="BEABAA2",
        cycle="M",
        expected_name="저축성수신",
        expected_unit="연%",
        role="bank_rate_candidate",
    ),
    SeriesSpec(
        key="bank_savings_deposit_rate_ex_financial_bonds",
        stat_code="121Y002",
        item_code="BEABAA1",
        cycle="M",
        expected_name="저축성수신(금융채 제외) 1)",
        expected_unit="연리%",
        role="bank_rate_candidate",
    ),
    SeriesSpec(
        key="bank_pure_savings_deposit_rate",
        stat_code="121Y002",
        item_code="BEABAA21",
        cycle="M",
        expected_name="순수저축성예금 1)",
        expected_unit="연리%",
        role="bank_rate_candidate",
    ),
    SeriesSpec(
        key="bank_term_deposit_1y_rate",
        stat_code="121Y002",
        item_code="BEABAA2118",
        cycle="M",
        expected_name="정기예금(1년)",
        expected_unit="연리%",
        role="bank_rate_candidate",
    ),
    SeriesSpec(
        key="savings_bank_deposit_balance",
        stat_code="111Y007",
        item_code="1120600",
        cycle="M",
        expected_name="상호저축은행",
        expected_unit="십억원",
        role="sector_balance",
    ),
    SeriesSpec(
        key="credit_union_deposit_balance",
        stat_code="111Y007",
        item_code="1120700",
        cycle="M",
        expected_name="신용협동조합",
        expected_unit="십억원",
        role="sector_balance",
    ),
    SeriesSpec(
        key="broad_mutual_finance_deposit_balance",
        stat_code="111Y007",
        item_code="1120800",
        cycle="M",
        expected_name="상호금융",
        expected_unit="십억원",
        role="broad_sector_balance_not_nh_local_1to1",
    ),
    SeriesSpec(
        key="kfcc_deposit_balance",
        stat_code="111Y007",
        item_code="1121000",
        cycle="M",
        expected_name="새마을금고",
        expected_unit="십억원",
        role="sector_balance",
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


def _rows(record: dict[str, Any]) -> list[dict[str, Any]]:
    payload = record.get("payload")
    if not isinstance(payload, dict):
        return []
    block = payload.get("StatisticSearch")
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


def validate_rows(spec: SeriesSpec, rows: list[dict[str, Any]]) -> list[str]:
    """Validate source identity/unit without interpreting values yet."""
    warnings: list[str] = []
    for row in rows:
        if str(row.get("STAT_CODE") or "") != spec.stat_code:
            warnings.append(f"unexpected STAT_CODE: {row.get('STAT_CODE')!r}")
        if str(row.get("ITEM_CODE1") or "") != spec.item_code:
            warnings.append(f"unexpected ITEM_CODE1: {row.get('ITEM_CODE1')!r}")
        if str(row.get("ITEM_NAME1") or "") != spec.expected_name:
            warnings.append(f"unexpected ITEM_NAME1: {row.get('ITEM_NAME1')!r}")
        if str(row.get("UNIT_NAME") or "") != spec.expected_unit:
            warnings.append(f"unexpected UNIT_NAME: {row.get('UNIT_NAME')!r}")
        month = str(row.get("TIME") or "")
        if len(month) != 6 or not month.isdigit():
            warnings.append(f"unexpected monthly TIME: {month!r}")
    return sorted(set(warnings))


def _ordered_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """ECOS response order is not part of the source contract."""
    return sorted(rows, key=lambda row: str(row.get("TIME") or ""))


def discover_series(key: str) -> dict[str, Any]:
    report: dict[str, Any] = {
        "base": BASE,
        "mode": "verified_exact_series_read_only",
        "evidence_run": 32135388199,
        "evidence_artifact": 9323770229,
        "range": {"from": START_MONTH, "to": END_MONTH},
        "series": {},
    }

    for spec in SERIES:
        path = (
            f"StatisticSearch/{key}/json/kr/1/{PAGE_SIZE}"
            f"/{spec.stat_code}/{spec.cycle}/{START_MONTH}/{END_MONTH}/{spec.item_code}"
        )
        result = probe(path, key)
        rows = _rows(result)
        ordered = _ordered_rows(rows)
        report["series"][spec.key] = {
            "spec": asdict(spec),
            "api_result": _api_result(result),
            "row_count": len(rows),
            "first_time": ordered[0].get("TIME") if ordered else None,
            "last_time": ordered[-1].get("TIME") if ordered else None,
            "latest_rows": ordered[-6:],
            "warnings": validate_rows(spec, rows),
            "response": result,
        }
    return report


def main() -> int:
    key = os.environ.get(KEY_ENV, "").strip()
    if not key:
        print(f"{KEY_ENV} 환경변수가 없다. 인증키는 환경변수로만 받는다.", file=sys.stderr)
        return 2

    report = discover_series(key)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(report, ensure_ascii=False, indent=2)
    if key in blob:
        blob = blob.replace(key, "[REDACTED]")
        print("경고: 인증키가 결과에 남아 저장 직전에 제거했다.")
    OUT.write_text(blob, encoding="utf-8")

    failed = False
    for spec in SERIES:
        result = report["series"][spec.key]
        api_result = result["api_result"]
        warnings = result["warnings"]
        print(
            f"{spec.key}: rows={result['row_count']} "
            f"range={result['first_time']}..{result['last_time']} "
            f"warnings={len(warnings)} result={api_result}"
        )
        if api_result or not result["row_count"] or warnings:
            failed = True
    print(f"기록: {OUT} ({len(blob):,} bytes)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
