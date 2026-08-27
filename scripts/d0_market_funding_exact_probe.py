#!/usr/bin/env python3
"""D0 exact-series verification for market-funding ECOS data.

Only series whose table/item labels were explicit in the preceding discovery
run are included here. Ambiguous non-bank item codes are intentionally omitted.
This is read-only and never opens the application DB.
"""

from __future__ import annotations

import calendar
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
TIMEOUT = 25
INTERVAL = 0.3
PAGE_SIZE = 1000
START_MONTH = "202201"
END_MONTH = "202612"
BILLION_PER_TRILLION = Decimal("1000")


@dataclass(frozen=True)
class SeriesSpec:
    key: str
    stat_code: str
    item_code: str
    expected_name: str
    expected_unit: str
    value_semantics: str
    balance_basis: str | None = None
    normalized_unit: str | None = None


SERIES = (
    # Existing bank realized/new-business rates.
    SeriesSpec(
        "bank_term_deposit_1y_rate",
        "121Y002",
        "BEABAA2118",
        "정기예금(1년)",
        "연리%",
        "flow_weighted_avg_of_month",
        normalized_unit="percent",
    ),
    # Newly proven non-bank sector rates.
    SeriesSpec(
        "savings_bank_term_deposit_1y_rate",
        "121Y004",
        "BEBBBE01",
        "상호저축은행-정기예금(1년)",
        "연리%",
        "flow_weighted_avg_of_month",
        normalized_unit="percent",
    ),
    SeriesSpec(
        "credit_union_term_deposit_1y_rate",
        "121Y004",
        "BEBBBG01",
        "신협-정기예탁금(1년)",
        "연리%",
        "flow_weighted_avg_of_month",
        normalized_unit="percent",
    ),
    SeriesSpec(
        "kfcc_term_deposit_1y_rate",
        "121Y004",
        "BEBBA000",
        "새마을금고-정기예탁금(1년)",
        "연리%",
        "flow_weighted_avg_of_month",
        normalized_unit="percent",
    ),
    # Existing non-bank EOM balances.
    SeriesSpec(
        "savings_bank_deposit_balance_eom",
        "111Y007",
        "1120600",
        "상호저축은행",
        "십억원",
        "stock_eom",
        "eom",
        "trillion_krw",
    ),
    SeriesSpec(
        "credit_union_deposit_balance_eom",
        "111Y007",
        "1120700",
        "신용협동조합",
        "십억원",
        "stock_eom",
        "eom",
        "trillion_krw",
    ),
    SeriesSpec(
        "broad_mutual_finance_deposit_balance_eom",
        "111Y007",
        "1120800",
        "상호금융",
        "십억원",
        "stock_eom",
        "eom",
        "trillion_krw",
    ),
    SeriesSpec(
        "kfcc_deposit_balance_eom",
        "111Y007",
        "1121000",
        "새마을금고",
        "십억원",
        "stock_eom",
        "eom",
        "trillion_krw",
    ),
    # Newly proven all deposit-bank EOM balances.
    SeriesSpec(
        "bank_total_deposit_balance_eom",
        "104Y015",
        "BDAA1",
        "총예금",
        "십억원",
        "stock_eom",
        "eom",
        "trillion_krw",
    ),
    SeriesSpec(
        "bank_savings_deposit_balance_eom",
        "104Y015",
        "BDAA3",
        "저축성예금",
        "십억원",
        "stock_eom",
        "eom",
        "trillion_krw",
    ),
    SeriesSpec(
        "bank_term_deposit_balance_eom",
        "104Y015",
        "BDAA31",
        "정기예금",
        "십억원",
        "stock_eom",
        "eom",
        "trillion_krw",
    ),
    SeriesSpec(
        "bank_installment_savings_balance_eom",
        "104Y015",
        "BDAA33",
        "정기적금",
        "십억원",
        "stock_eom",
        "eom",
        "trillion_krw",
    ),
    # Deposit-bank term-deposit maturity structure, EOM.
    SeriesSpec(
        "bank_term_deposit_lt_6m_eom",
        "104Y010",
        "1021000",
        "6개월미만",
        "십억원",
        "stock_eom",
        "eom",
        "trillion_krw",
    ),
    SeriesSpec(
        "bank_term_deposit_6m_lt_1y_eom",
        "104Y010",
        "1030000",
        "6개월이상 1년미만",
        "십억원",
        "stock_eom",
        "eom",
        "trillion_krw",
    ),
    SeriesSpec(
        "bank_term_deposit_1y_lt_2y_eom",
        "104Y010",
        "1040000",
        "1년이상 2년미만",
        "십억원",
        "stock_eom",
        "eom",
        "trillion_krw",
    ),
    SeriesSpec(
        "bank_term_deposit_2y_lt_3y_eom",
        "104Y010",
        "1060000",
        "2년이상 3년미만",
        "십억원",
        "stock_eom",
        "eom",
        "trillion_krw",
    ),
    SeriesSpec(
        "bank_term_deposit_3y_plus_eom",
        "104Y010",
        "1070000",
        "3년이상",
        "십억원",
        "stock_eom",
        "eom",
        "trillion_krw",
    ),
)

REQUIRED_FIELDS = frozenset(
    {"STAT_CODE", "ITEM_CODE1", "ITEM_NAME1", "UNIT_NAME", "TIME", "DATA_VALUE"}
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
            record["payload"] = json.loads(body.decode("utf-8"))
    except Exception as error:  # noqa: BLE001 - diagnostic captures failures
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


def _next_month(month: str) -> str:
    year, value = int(month[:4]), int(month[4:])
    if value == 12:
        return f"{year + 1:04d}01"
    return f"{year:04d}{value + 1:02d}"


def _continuity(months: list[str]) -> list[str]:
    missing: list[str] = []
    if not months:
        return missing
    current = months[0]
    present = set(months)
    while current < months[-1]:
        current = _next_month(current)
        if current not in present:
            missing.append(current)
    return missing


def _normalize(raw: Decimal, spec: SeriesSpec) -> Decimal:
    if spec.normalized_unit == "trillion_krw" and spec.expected_unit == "십억원":
        return raw / BILLION_PER_TRILLION
    return raw


def validate(spec: SeriesSpec, record: dict[str, Any]) -> dict[str, Any]:
    api_result = _api_result(record)
    rows = sorted(_rows(record), key=lambda row: str(row.get("TIME") or ""))
    errors: list[str] = []
    values: list[Decimal] = []
    normalized: list[Decimal] = []
    months: list[str] = []
    row_keys = sorted({key for row in rows for key in row}) if rows else []

    block = (record.get("payload") or {}).get("StatisticSearch") or {}
    total_count = block.get("list_total_count") if isinstance(block, dict) else None
    if api_result is not None:
        errors.append(f"api_result={api_result}")
    if not rows:
        errors.append("no rows")
    if total_count is not None and int(total_count) != len(rows):
        errors.append(f"pagination mismatch total={total_count} rows={len(rows)}")

    for index, row in enumerate(rows):
        missing_fields = REQUIRED_FIELDS - set(row)
        if missing_fields:
            errors.append(f"row {index}: missing fields {sorted(missing_fields)}")
            continue
        if str(row.get("STAT_CODE") or "") != spec.stat_code:
            errors.append(f"row {index}: STAT_CODE={row.get('STAT_CODE')!r}")
        if str(row.get("ITEM_CODE1") or "") != spec.item_code:
            errors.append(f"row {index}: ITEM_CODE1={row.get('ITEM_CODE1')!r}")
        if str(row.get("ITEM_NAME1") or "") != spec.expected_name:
            errors.append(f"row {index}: ITEM_NAME1={row.get('ITEM_NAME1')!r}")
        if str(row.get("UNIT_NAME") or "").strip() != spec.expected_unit:
            errors.append(f"row {index}: UNIT_NAME={row.get('UNIT_NAME')!r}")
        month = str(row.get("TIME") or "")
        if len(month) != 6 or not month.isdigit() or not 1 <= int(month[4:]) <= 12:
            errors.append(f"row {index}: TIME={month!r}")
            continue
        months.append(month)
        try:
            value = Decimal(str(row.get("DATA_VALUE") or "").strip())
        except (InvalidOperation, ValueError):
            errors.append(f"row {index}: DATA_VALUE={row.get('DATA_VALUE')!r}")
            continue
        if value < 0:
            errors.append(f"row {index}: negative value={value}")
        values.append(value)
        normalized.append(_normalize(value, spec))

    duplicate_months = sorted({month for month in months if months.count(month) > 1})
    missing_months = _continuity(sorted(set(months)))
    if duplicate_months:
        errors.append(f"duplicate months={duplicate_months}")
    if missing_months:
        errors.append(f"missing months={missing_months}")

    latest = []
    for row in rows[-12:]:
        try:
            raw_value = Decimal(str(row.get("DATA_VALUE") or "").strip())
            normalized_value = _normalize(raw_value, spec)
        except (InvalidOperation, ValueError):
            normalized_value = None
        latest.append(
            {
                "time": row.get("TIME"),
                "source_value": row.get("DATA_VALUE"),
                "normalized_value": str(normalized_value) if normalized_value is not None else None,
            }
        )

    return {
        "spec": asdict(spec),
        "api_result": api_result,
        "list_total_count": total_count,
        "row_count": len(rows),
        "first_time": months[0] if months else None,
        "last_time": months[-1] if months else None,
        "source_min": str(min(values)) if values else None,
        "source_max": str(max(values)) if values else None,
        "normalized_min": str(min(normalized)) if normalized else None,
        "normalized_max": str(max(normalized)) if normalized else None,
        "row_keys": row_keys,
        "latest_rows": latest,
        "errors": sorted(set(errors)),
        "response_meta": {
            "status": record.get("status"),
            "bytes": record.get("bytes"),
            "error": record.get("error"),
        },
    }


def discover(key: str) -> dict[str, Any]:
    report: dict[str, Any] = {
        "mode": "exact_series_read_only_no_db_write",
        "base": BASE,
        "cycle": "M",
        "range": {"from": START_MONTH, "to": END_MONTH},
        "series": {},
    }
    for spec in SERIES:
        path = (
            f"StatisticSearch/{key}/json/kr/1/{PAGE_SIZE}"
            f"/{spec.stat_code}/M/{START_MONTH}/{END_MONTH}/{spec.item_code}"
        )
        report["series"][spec.key] = validate(spec, probe(path, key))
    return report


def main() -> int:
    key = os.environ.get(KEY_ENV, "").strip()
    if not key:
        print(f"{KEY_ENV} 환경변수가 없다.", file=sys.stderr)
        return 2

    report = discover(key)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(report, ensure_ascii=False, indent=2)
    if key in blob:
        blob = blob.replace(key, "[REDACTED]")
        print("경고: 인증키가 결과에 남아 저장 직전에 제거했다.")
    OUT.write_text(blob, encoding="utf-8")

    failed = False
    for name, result in report["series"].items():
        print(
            f"{name}: rows={result['row_count']} "
            f"range={result['first_time']}..{result['last_time']} "
            f"normalized={result['normalized_min']}..{result['normalized_max']} "
            f"errors={len(result['errors'])}"
        )
        if result["errors"]:
            failed = True
    print(f"기록: {OUT} ({len(blob):,} bytes)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
