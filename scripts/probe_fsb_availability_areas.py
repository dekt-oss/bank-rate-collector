"""Read-only FSB availability-area evidence probe.

Queries the official savings-bank term-deposit disclosure with the exact AREA
values captured by the repository's 2026-08-05 source reconnaissance.  It does
not write the application DB and does not infer geography from head-office
addresses.  The goal is to establish whether AREA membership is stable at the
institution or product level before creating a pricing comparison key.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any

import httpx

BASE_URL = "https://www.fsb.or.kr"
SCREEN_PATH = "/ratedepo_0100.act"
DATA_PATH = "/ratedepo_0100_01.jct"
USER_AGENT = "rate-monitor/1 (+public rate disclosure evidence probe; 1 req/s)"
REQUEST_INTERVAL_SECONDS = 1.0
PAGE_LIMIT = 500

# Exact values extracted from the official page and recorded in
# docs/source-recon/fsb-recon.json on 2026-08-05.  Do not rename from intuition.
AREAS: tuple[tuple[str, str], ...] = (
    ("YN_Kangwon", "강원"),
    ("YN_Kyungki", "경기"),
    ("YN_Kyungnam", "경남"),
    ("YN_Kyungbuk", "경북"),
    ("YN_Kwangju", "광주"),
    ("YN_Deaku", "대구"),
    ("YN_Deajeon", "대전"),
    ("YN_Busan", "부산"),
    ("YN_Seoul", "서울"),
    ("YN_Saejong", "세종"),
    ("YN_Ulsan", "울산"),
    ("YN_Incheon", "인천"),
    ("YN_Jeonnam", "전남"),
    ("YN_Jeonbuk", "전북"),
    ("YN_Jeju", "제주"),
    ("YN_Chungnam", "충남"),
    ("YN_Chungbuk", "충북"),
)


def _body(query_date: str, area: str) -> dict[str, str]:
    year, month, day = query_date.split("-")
    return {
        "REG_DATE": query_date,
        "CHG_DATE": query_date,
        "AREA": area,
        "SELECT_YEAR": year,
        "SELECT_MONTH": month,
        "SELECT_DAY": day,
        "TB_SEQ1": "",
        "TB_SEQ2": "",
        "TB_SEQ3": "",
        "ORDERBY": "",
        "JOIN_LOCATION": "1|2|3|4|5|9",
        "CHK_MONTH": "12",
        "END_NUM": str(PAGE_LIMIT),
        "START_NUM": "1",
        "SEARCH_CODE": "",
        "SEARCH_SELECT_IN": "",
        "SEARCH_TEXT_IN": "",
    }


def _clean(value: object) -> str:
    return str(value or "").strip()


def _keys(rows: list[dict[str, Any]]) -> tuple[set[str], set[tuple[str, str]]]:
    institutions: set[str] = set()
    products: set[tuple[str, str]] = set()
    for row in rows:
        institution = _clean(row.get("FINAN_COMP_CODE"))
        product = _clean(row.get("FINAN_PROD_CODE"))
        if not institution or not product:
            raise RuntimeError("FSB response lost FINAN_COMP_CODE/FINAN_PROD_CODE")
        institutions.add(institution)
        products.add((institution, product))
    return institutions, products


async def _query(client: httpx.AsyncClient, query_date: str, area: str) -> list[dict[str, Any]]:
    response = await client.post(f"{BASE_URL}{DATA_PATH}", json=_body(query_date, area))
    response.raise_for_status()
    payload = response.json()
    rows = payload.get("REC")
    if not isinstance(rows, list):
        raise RuntimeError(f"FSB response has no REC list for area={area!r}")
    total_raw = _clean(rows[0].get("CNT")) if rows else "0"
    total = int(total_raw) if total_raw.isdigit() else len(rows)
    if total > PAGE_LIMIT:
        raise RuntimeError(
            f"FSB area={area!r} total={total} exceeds probe PAGE_LIMIT={PAGE_LIMIT}; "
            "refuse partial evidence"
        )
    if len(rows) != total:
        raise RuntimeError(
            f"FSB area={area!r} returned {len(rows)} rows but CNT says {total}; "
            "refuse partial evidence"
        )
    return rows


async def probe(query_date: str) -> dict[str, Any]:
    timeout = httpx.Timeout(30.0, connect=10.0)
    headers = {"User-Agent": USER_AGENT, "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
        page = await client.get(f"{BASE_URL}{SCREEN_PATH}")
        page.raise_for_status()
        await asyncio.sleep(REQUEST_INTERVAL_SECONDS)

        all_rows = await _query(client, query_date, "")
        all_institutions, all_products = _keys(all_rows)
        await asyncio.sleep(REQUEST_INTERVAL_SECONDS)

        area_institutions: dict[str, set[str]] = {}
        area_products: dict[str, set[tuple[str, str]]] = {}
        area_counts: dict[str, dict[str, int]] = {}
        for area_code, label in AREAS:
            rows = await _query(client, query_date, area_code)
            institutions, products = _keys(rows)
            if not institutions.issubset(all_institutions) or not products.issubset(all_products):
                raise RuntimeError(f"area {area_code} contains rows absent from 지역전체")
            area_institutions[area_code] = institutions
            area_products[area_code] = products
            area_counts[area_code] = {
                "label": label,
                "institution_count": len(institutions),
                "product_count": len(products),
                "row_count": len(rows),
            }
            await asyncio.sleep(REQUEST_INTERVAL_SECONDS)

    institution_membership: dict[str, tuple[str, ...]] = {}
    for institution in sorted(all_institutions):
        institution_membership[institution] = tuple(
            code for code, _label in AREAS if institution in area_institutions[code]
        )

    product_membership: dict[tuple[str, str], tuple[str, ...]] = {}
    for product in sorted(all_products):
        product_membership[product] = tuple(
            code for code, _label in AREAS if product in area_products[code]
        )

    products_by_institution: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for product in all_products:
        products_by_institution[product[0]].append(product)

    inconsistent_institutions: dict[str, list[dict[str, Any]]] = {}
    for institution, products in sorted(products_by_institution.items()):
        patterns = {product_membership[product] for product in products}
        if len(patterns) > 1:
            inconsistent_institutions[institution] = [
                {
                    "product_code": product[1],
                    "areas": list(product_membership[product]),
                }
                for product in sorted(products)
            ]

    full_area_set = tuple(code for code, _label in AREAS)
    institution_patterns = Counter(institution_membership.values())
    product_patterns = Counter(product_membership.values())

    return {
        "evidence_type": "official_fsb_read_only_area_filter_probe",
        "query_date": query_date,
        "screen": "ratedepo_0100",
        "endpoint": DATA_PATH,
        "area_dimension_source": "docs/source-recon/fsb-recon.json",
        "area_count": len(AREAS),
        "all": {
            "row_count": len(all_rows),
            "institution_count": len(all_institutions),
            "product_count": len(all_products),
        },
        "by_area": area_counts,
        "institution_membership": {
            institution: list(pattern)
            for institution, pattern in sorted(institution_membership.items())
        },
        "institution_pattern_counts": [
            {"areas": list(pattern), "institution_count": count}
            for pattern, count in sorted(institution_patterns.items())
        ],
        "product_pattern_counts": [
            {"areas": list(pattern), "product_count": count}
            for pattern, count in sorted(product_patterns.items())
        ],
        "institutions_in_all_17_areas": sum(
            pattern == full_area_set for pattern in institution_membership.values()
        ),
        "products_in_all_17_areas": sum(
            pattern == full_area_set for pattern in product_membership.values()
        ),
        "product_membership_consistent_within_institution": not inconsistent_institutions,
        "inconsistent_institutions": inconsistent_institutions,
        "write_performed": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of", default=date.today().isoformat())
    parser.add_argument("--output", type=Path, default=Path("fsb-availability-probe.json"))
    args = parser.parse_args()
    result = asyncio.run(probe(args.as_of))
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
