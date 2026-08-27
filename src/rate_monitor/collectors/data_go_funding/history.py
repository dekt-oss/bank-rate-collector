"""Historical reporting-month helpers for Data.go institution funding.

Data.go ``basYm`` is an explicit request parameter.  The source contracts report on
quarterly or half-year cadences, so a backfill range means "all expected reporting
months inside the inclusive calendar range", not every calendar month.
"""

from __future__ import annotations

import re
from datetime import date

from rate_monitor.collectors.data_go_funding.collector import SourceContract

_MONTH_RE = re.compile(r"^(\d{4})(\d{2})$")


def validate_month_key(value: str) -> str:
    """Validate and normalize a ``YYYYMM`` request month."""
    text = str(value or "").strip().replace("-", "")
    match = _MONTH_RE.fullmatch(text)
    if match is None:
        raise ValueError(f"기준월은 YYYYMM 또는 YYYY-MM 형식이어야 한다: {value!r}")
    month = int(match.group(2))
    if not 1 <= month <= 12:
        raise ValueError(f"기준월의 월 범위가 잘못됐다: {value!r}")
    return text


def historical_months(
    contract: SourceContract,
    start_month: str,
    end_month: str,
) -> list[str]:
    """Return expected source reporting months in descending order, inclusive."""
    start = validate_month_key(start_month)
    end = validate_month_key(end_month)
    if start > end:
        raise ValueError(f"backfill 시작월이 종료월보다 늦다: {start} > {end}")

    start_year, start_num = int(start[:4]), int(start[4:])
    end_year, end_num = int(end[:4]), int(end[4:])
    out: list[str] = []
    for year in range(end_year, start_year - 1, -1):
        for month in sorted(contract.cadence_months, reverse=True):
            value = f"{year:04d}{month:02d}"
            if start <= value <= end:
                out.append(value)
    if not out:
        raise ValueError(
            f"{contract.source_id}: {start}~{end}에 예상 보고월이 없다 "
            f"(cadence={contract.cadence_months})"
        )
    return out


def shift_month(month_key: str, delta: int) -> str:
    """Shift a ``YYYYMM`` key by calendar months."""
    key = validate_month_key(month_key)
    absolute = int(key[:4]) * 12 + int(key[4:]) - 1 + delta
    if absolute < 12:
        raise ValueError("지원하지 않는 기준월 범위")
    year, month0 = divmod(absolute, 12)
    return f"{year:04d}{month0 + 1:02d}"


def latest_completed_reporting_month(
    contract: SourceContract,
    today: date | None = None,
) -> str:
    """Resolve the latest cadence month not later than ``today``."""
    cursor = today or date.today()
    year = cursor.year
    while True:
        candidates = [
            month
            for month in contract.cadence_months
            if year < cursor.year or month <= cursor.month
        ]
        if candidates:
            return f"{year:04d}{max(candidates):02d}"
        year -= 1
