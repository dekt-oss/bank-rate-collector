#!/usr/bin/env python3
"""D0 exact-series verification for market-funding ECOS data.

Only series with explicit ECOS table/item labels are included. Ambiguous
non-bank item codes from discovery are intentionally omitted. Read-only: this
script never opens the application DB.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

BASE = "https://ecos.bok.or.kr/api"
KEY_ENV = "ECOS_API_KEY"
OUT = Path("docs/source-recon/market-funding-d0-exact-series.json")
START_MONTH = "202201"
END_MONTH = "202612"
PAGE_SIZE = 1000
BILLION_PER_TRILLION = Decimal("1000")


@dataclass(frozen=True)
class SeriesSpec:
    key: str
    stat: str
    item: str
    name: str
    source_unit: str
    semantics: str
    normalized_unit: str
    balance_basis: str | None = None


RATE = "flow_weighted_avg_of_month"
STOCK = "stock_eom"
PERCENT = "percent"
TRILLION = "trillion_krw"

SERIES = (
    SeriesSpec("bank_term_deposit_1y_rate", "121Y002", "BEABAA2118", "정기예금(1년)", "연리%", RATE, PERCENT),
    SeriesSpec("savings_bank_term_deposit_1y_rate", "121Y004", "BEBBBE01", "상호저축은행-정기예금(1년)", "연리%", RATE, PERCENT),
    SeriesSpec("credit_union_term_deposit_1y_rate", "121Y004", "BEBBBG01", "신협-정기예탁금(1년)", "연리%", RATE, PERCENT),
    SeriesSpec("kfcc_term_deposit_1y_rate", "121Y004", "BEBBA000", "새마을금고-정기예탁금(1년)", "연리%", RATE, PERCENT),
    SeriesSpec("savings_bank_deposit_balance_eom", "111Y007", "1120600", "상호저축은행", "십억원", STOCK, TRILLION, "eom"),
    SeriesSpec("credit_union_deposit_balance_eom", "111Y007", "1120700", "신용협동조합", "십억원", STOCK, TRILLION, "eom"),
    SeriesSpec("broad_mutual_finance_deposit_balance_eom", "111Y007", "1120800", "상호금융", "십억원", STOCK, TRILLION, "eom"),
    SeriesSpec("kfcc_deposit_balance_eom", "111Y007", "1121000", "새마을금고", "십억원", STOCK, TRILLION, "eom"),
    SeriesSpec("bank_total_deposit_balance_eom", "104Y015", "BDAA1", "총예금", "십억원", STOCK, TRILLION, "eom"),
    SeriesSpec("bank_savings_deposit_balance_eom", "104Y015", "BDAA3", "저축성예금", "십억원", STOCK, TRILLION, "eom"),
    SeriesSpec("bank_term_deposit_balance_eom", "104Y015", "BDAA31", "정기예금", "십억원", STOCK, TRILLION, "eom"),
    SeriesSpec("bank_installment_savings_balance_eom", "104Y015", "BDAA33", "정기적금", "십억원", STOCK, TRILLION, "eom"),
    SeriesSpec("bank_term_deposit_lt_6m_eom", "104Y010", "1021000", "6개월미만", "십억원", STOCK, TRILLION, "eom"),
    SeriesSpec("bank_term_deposit_6m_lt_1y_eom", "104Y010", "1030000", "6개월이상 1년미만", "십억원", STOCK, TRILLION, "eom"),
    SeriesSpec("bank_term_deposit_1y_lt_2y_eom", "104Y010", "1040000", "1년이상 2년미만", "십억원", STOCK, TRILLION, "eom"),
    SeriesSpec("bank_term_deposit_2y_lt_3y_eom", "104Y010", "1060000", "2년이상 3년미만", "십억원", STOCK, TRILLION, "eom"),
    SeriesSpec("bank_term_deposit_3y_plus_eom", "104Y010", "1070000", "3년이상", "십억원", STOCK, TRILLION, "eom"),
)

REQUIRED = {"STAT_CODE", "ITEM_CODE1", "ITEM_NAME1", "UNIT_NAME", "TIME", "DATA_VALUE"}


def _mask(text: str, key: str) -> str:
    return text.replace(key, "[REDACTED]")


def _request(spec: SeriesSpec, key: str) -> dict[str, Any]:
    path = (
        f"StatisticSearch/{key}/json/kr/1/{PAGE_SIZE}/"
        f"{spec.stat}/M/{START_MONTH}/{END_MONTH}/{spec.item}"
    )
    url = f"{BASE}/{path}"
    record: dict[str, Any] = {"url": _mask(url, key)}
    request = urllib.request.Request(
        url, headers={"User-Agent": "rate-monitor/1 (+public rate disclosure collector)"}
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            body = response.read()
            record["status"] = response.status
            record["bytes"] = len(body)
            record["payload"] = json.loads(body.decode("utf-8"))
    except Exception as error:  # noqa: BLE001 - diagnostic captures all failures
        record["error"] = f"{type(error).__name__}: {_mask(str(error), key)}"
    time.sleep(0.3)
    return record


def _next_month(month: str) -> str:
    year, value = int(month[:4]), int(month[4:])
    return f"{year + 1:04d}01" if value == 12 else f"{year:04d}{value + 1:02d}"


def _missing_months(months: list[str]) -> list[str]:
    if not months:
        return []
    present = set(months)
    current = months[0]
    missing: list[str] = []
    while current < months[-1]:
        current = _next_month(current)
        if current not in present:
            missing.append(current)
    return missing


def _normalize(value: Decimal, spec: SeriesSpec) -> Decimal:
    if spec.normalized_unit == TRILLION:
        return value / BILLION_PER_TRILLION
    return value


def _validate(spec: SeriesSpec, record: dict[str, Any]) -> dict[str, Any]:
    payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
    api_result = payload.get("RESULT") if isinstance(payload.get("RESULT"), dict) else None
    block = payload.get("StatisticSearch") if isinstance(payload.get("StatisticSearch"), dict) else {}
    rows = block.get("row") if isinstance(block.get("row"), list) else []
    rows = sorted(rows, key=lambda row: str(row.get("TIME") or ""))
    errors: list[str] = []
    months: list[str] = []
    values: list[Decimal] = []
    normalized: list[Decimal] = []

    if api_result:
        errors.append(f"api_result={api_result}")
    if not rows:
        errors.append("no rows")
    total = block.get("list_total_count")
    if total is not None and int(total) != len(rows):
        errors.append(f"pagination mismatch total={total} rows={len(rows)}")

    for index, row in enumerate(rows):
        missing = REQUIRED - set(row)
        if missing:
            errors.append(f"row {index}: missing={sorted(missing)}")
            continue
        checks = (
            ("STAT_CODE", spec.stat),
            ("ITEM_CODE1", spec.item),
            ("ITEM_NAME1", spec.name),
            ("UNIT_NAME", spec.source_unit),
        )
        for field, expected in checks:
            actual = str(row.get(field) or "").strip()
            if actual != expected:
                errors.append(f"row {index}: {field}={actual!r} expected={expected!r}")
        month = str(row.get("TIME") or "")
        if len(month) != 6 or not month.isdigit() or not 1 <= int(month[4:]) <= 12:
            errors.append(f"row {index}: invalid TIME={month!r}")
            continue
        months.append(month)
        try:
            value = Decimal(str(row.get("DATA_VALUE") or "").strip())
        except (InvalidOperation, ValueError):
            errors.append(f"row {index}: invalid DATA_VALUE={row.get('DATA_VALUE')!r}")
            continue
        if value < 0:
            errors.append(f"row {index}: negative value={value}")
        values.append(value)
        normalized.append(_normalize(value, spec))

    duplicates = sorted({month for month in months if months.count(month) > 1})
    gaps = _missing_months(sorted(set(months)))
    if duplicates:
        errors.append(f"duplicate months={duplicates}")
    if gaps:
        errors.append(f"missing months={gaps}")

    latest: list[dict[str, str | None]] = []
    for row in rows[-12:]:
        raw = str(row.get("DATA_VALUE") or "").strip()
        try:
            normalized_value = str(_normalize(Decimal(raw), spec))
        except (InvalidOperation, ValueError):
            normalized_value = None
        latest.append(
            {"time": str(row.get("TIME") or ""), "source_value": raw, "normalized_value": normalized_value}
        )

    return {
        "spec": asdict(spec),
        "api_result": api_result,
        "list_total_count": total,
        "row_count": len(rows),
        "first_time": months[0] if months else None,
        "last_time": months[-1] if months else None,
        "source_min": str(min(values)) if values else None,
        "source_max": str(max(values)) if values else None,
        "normalized_min": str(min(normalized)) if normalized else None,
        "normalized_max": str(max(normalized)) if normalized else None,
        "latest_rows": latest,
        "errors": sorted(set(errors)),
        "response_meta": {"status": record.get("status"), "bytes": record.get("bytes"), "error": record.get("error")},
    }


def main() -> int:
    key = os.environ.get(KEY_ENV, "").strip()
    if not key:
        print(f"{KEY_ENV} 환경변수가 없다.", file=sys.stderr)
        return 2

    report: dict[str, Any] = {
        "mode": "exact_series_read_only_no_db_write",
        "base": BASE,
        "cycle": "M",
        "range": {"from": START_MONTH, "to": END_MONTH},
        "series": {},
    }
    failed = False
    for spec in SERIES:
        result = _validate(spec, _request(spec, key))
        report["series"][spec.key] = result
        print(
            f"{spec.key}: rows={result['row_count']} "
            f"range={result['first_time']}..{result['last_time']} errors={len(result['errors'])}"
        )
        failed = failed or bool(result["errors"])

    OUT.parent.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(report, ensure_ascii=False, indent=2)
    if key in blob:
        blob = blob.replace(key, "[REDACTED]")
    OUT.write_text(blob, encoding="utf-8")
    print(f"기록: {OUT} ({len(blob):,} bytes)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
