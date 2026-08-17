#!/usr/bin/env python3
"""Reproduce Stage G entry-gate evidence from immutable GitHub Actions artifacts.

This is deliberately independent from the production collectors. It reads the
captured official HTML directly so a parser bug cannot make the gate prove
itself.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_TR = re.compile(r"<tr[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
_TD = re.compile(r"<td([^>]*)>(.*?)</td>", re.IGNORECASE | re.DOTALL)
_SPAN = re.compile(
    r'<span[^>]+title=["\']([^"\']+)["\'][^>]*>(.*?)</span>',
    re.IGNORECASE | re.DOTALL,
)
_ROWSPAN = re.compile(r'rowspan\s*=\s*"?(\d+)', re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")
_TERM_MONTH = re.compile(r"(\d+)\s*개월")
_RATE = re.compile(r"(-?\d+(?:\.\d+)?)\s*%")
_NH_FILE = re.compile(r"/rate_(\d+)_(SFDPW016[34]R)\.html$")

NH_PREFERENCE_PRODUCT = "e-joy 인터넷예금 우대금리"
NH_PREFERENCE_NOTE = (
    "- 대상예금 <거치식> 정기예탁금, 복리식 정기예탁금 "
    "<적립식> 정기적금, 자유적립 적금, 자유로 부금 "
    "- 상품별 금리 + 우대금리 적용"
)
NH_TARGET_PRODUCTS = {
    "정기예탁금": "정기예탁금",
    "복리식 정기예탁금": "복리식정기예탁금",
    "정기적금": "정기적금",
    "자유적립 적금": "자유적립적금",
    "자유로 부금": "자유로부금",
}


def _text(raw: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(_TAG.sub(" ", raw))).strip()


@dataclass(frozen=True)
class RateEntry:
    product_name: str
    term_raw: str
    rate_raw: str
    note: str


@dataclass(frozen=True)
class MonthInterval:
    lower: int
    upper: int | None

    def contains(self, month: int) -> bool:
        if month < self.lower:
            return False
        return self.upper is None or month < self.upper


def _rate_entries(source: str) -> list[RateEntry]:
    entries: list[RateEntry] = []
    carried: dict[str, tuple[str, int]] = {}

    for block in _TR.findall(source):
        cells = [(attrs, _text(body)) for attrs, body in _TD.findall(block)]
        if not cells:
            continue

        if len(cells) >= 5:
            product, term, rate, note, _interest = (value for _, value in cells[:5])
            span = _ROWSPAN.search(cells[0][0])
            remaining = (int(span.group(1)) if span else 1) - 1
            carried = (
                {"product": (product, remaining), "note": (note, remaining)}
                if remaining > 0
                else {}
            )
        elif len(cells) == 2 and carried:
            term, rate = cells[0][1], cells[1][1]
            product = carried["product"][0]
            note = carried["note"][0]
            carried = {
                key: (value, left - 1)
                for key, (value, left) in carried.items()
                if left > 1
            }
        else:
            continue

        if term and rate:
            entries.append(RateEntry(product, term, rate, note))

    return entries


def _lower_month(term_raw: str) -> int | None:
    match = _TERM_MONTH.search(term_raw)
    return int(match.group(1)) if match else None


def _preference_interval(term_raw: str) -> MonthInterval | None:
    months = [int(value) for value in _TERM_MONTH.findall(term_raw)]
    if "이상" not in term_raw or not months:
        return None
    lower = months[0]
    upper = months[1] if "미만" in term_raw and len(months) >= 2 else None
    return MonthInterval(lower=lower, upper=upper)


def _parse_percent(rate_raw: str) -> str | None:
    match = _RATE.search(rate_raw)
    return match.group(1) if match else None


def audit_nh(path: Path) -> dict[str, Any]:
    by_brc: dict[str, dict[str, list[RateEntry]]] = defaultdict(
        lambda: defaultdict(list)
    )
    file_counts: Counter[str] = Counter()
    preference_notes: Counter[str] = Counter()
    preference_rates: Counter[str] = Counter()
    preference_intervals: Counter[str] = Counter()

    with zipfile.ZipFile(path) as archive:
        for member in archive.namelist():
            match = _NH_FILE.search(member)
            if match is None:
                continue
            brc, screen = match.groups()
            file_counts[screen] += 1
            source = archive.read(member).decode("utf-8", "ignore")
            for entry in _rate_entries(source):
                by_brc[brc][entry.product_name].append(entry)
                if entry.product_name != NH_PREFERENCE_PRODUCT:
                    continue
                preference_notes[entry.note] += 1
                rate = _parse_percent(entry.rate_raw)
                preference_rates[rate or "UNPARSED"] += 1
                interval = _preference_interval(entry.term_raw)
                preference_intervals[
                    f"{interval.lower}:{interval.upper}" if interval else "UNPARSED"
                ] += 1

    target_rows = Counter()
    linkable_rows = Counter()
    ambiguous_rows = Counter()
    unmatched_rows = Counter()
    preference_brcs: set[str] = set()
    brc_without_preference: list[str] = []

    for brc, products in by_brc.items():
        preference_entries = products.get(NH_PREFERENCE_PRODUCT, [])
        intervals = [
            (_preference_interval(entry.term_raw), entry)
            for entry in preference_entries
        ]
        if preference_entries:
            preference_brcs.add(brc)
        else:
            brc_without_preference.append(brc)

        for label, source_name in NH_TARGET_PRODUCTS.items():
            for target in products.get(source_name, []):
                target_rows[label] += 1
                month = _lower_month(target.term_raw)
                if month is None:
                    unmatched_rows[label] += 1
                    continue
                matches = [
                    entry
                    for interval, entry in intervals
                    if interval is not None and interval.contains(month)
                ]
                if len(matches) == 1:
                    linkable_rows[label] += 1
                elif not matches:
                    unmatched_rows[label] += 1
                else:
                    ambiguous_rows[label] += 1

    all_target_rows = sum(target_rows.values())
    all_linkable_rows = sum(linkable_rows.values())

    twelve_target_rows = Counter()
    twelve_linkable_rows = Counter()
    for _brc, products in by_brc.items():
        intervals = [
            (_preference_interval(entry.term_raw), entry)
            for entry in products.get(NH_PREFERENCE_PRODUCT, [])
        ]
        for label, source_name in NH_TARGET_PRODUCTS.items():
            for target in products.get(source_name, []):
                if _lower_month(target.term_raw) != 12:
                    continue
                twelve_target_rows[label] += 1
                matches = [
                    entry
                    for interval, entry in intervals
                    if interval is not None and interval.contains(12)
                ]
                if len(matches) == 1:
                    twelve_linkable_rows[label] += 1

    twelve_total = sum(twelve_target_rows.values())
    twelve_linkable = sum(twelve_linkable_rows.values())
    return {
        "artifact": str(path),
        "detail_files": dict(sorted(file_counts.items())),
        "unique_brc_with_any_parsed_rate": len(by_brc),
        "preference": {
            "product_name": NH_PREFERENCE_PRODUCT,
            "row_count": sum(preference_notes.values()),
            "brc_count": len(preference_brcs),
            "exact_expected_note_rows": preference_notes[NH_PREFERENCE_NOTE],
            "unique_notes": len(preference_notes),
            "intervals": dict(sorted(preference_intervals.items())),
            "rates": dict(sorted(preference_rates.items())),
        },
        "target_rows": dict(target_rows),
        "linkable_rows": dict(linkable_rows),
        "unmatched_rows": dict(unmatched_rows),
        "ambiguous_rows": dict(ambiguous_rows),
        "all_target_rows": all_target_rows,
        "all_linkable_rows": all_linkable_rows,
        "all_linkable_pct": (
            round(all_linkable_rows / all_target_rows * 100, 6)
            if all_target_rows
            else None
        ),
        "twelve_month_target_rows": dict(twelve_target_rows),
        "twelve_month_linkable_rows": dict(twelve_linkable_rows),
        "twelve_month_linkable_pct": (
            round(twelve_linkable / twelve_total * 100, 6) if twelve_total else None
        ),
        "brc_without_preference": sorted(brc_without_preference),
    }


def audit_kfcc(path: Path) -> dict[str, Any]:
    rows: list[dict[str, str]] = []
    list_files = 0

    with zipfile.ZipFile(path) as archive:
        for member in archive.namelist():
            if "/list_" not in member or not member.endswith(".html"):
                continue
            list_files += 1
            source = archive.read(member).decode("utf-8", "ignore")
            current: dict[str, str] = {}
            for title, value in _SPAN.findall(source):
                if title in current:
                    if current.get("gmgoCd"):
                        rows.append(current)
                    current = {}
                current[title] = _text(value)
            if current.get("gmgoCd"):
                rows.append(current)

    populated_fields: Counter[str] = Counter()
    url_like_values = 0
    for row in rows:
        for key, value in row.items():
            if value:
                populated_fields[key] += 1
            lowered = value.lower()
            if any(marker in lowered for marker in ("http", "www", ".com", ".kr")):
                url_like_values += 1

    return {
        "artifact": str(path),
        "regional_list_files": list_files,
        "outlet_rows": len(rows),
        "unique_gmgoCd": len({row["gmgoCd"] for row in rows}),
        "field_names": sorted({key for row in rows for key in row}),
        "populated_field_counts": dict(populated_fields),
        "url_like_values": url_like_values,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--nh-artifact", type=Path)
    parser.add_argument("--kfcc-artifact", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    if args.nh_artifact is None and args.kfcc_artifact is None:
        parser.error("at least one artifact is required")

    result: dict[str, Any] = {}
    if args.nh_artifact is not None:
        result["nh_local"] = audit_nh(args.nh_artifact)
    if args.kfcc_artifact is not None:
        result["kfcc"] = audit_kfcc(args.kfcc_artifact)

    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
