#!/usr/bin/env python3
"""Bounded check: does a bogoTy=N CU disclosure expose GSSP020000 finance rows?"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path

import httpx

OUT = Path("docs/source-recon/cu-funding-bogoty-probe-20260829.json")
URL = "https://www.cu.co.kr/GSSP020000.do"
PARAMS = {
    "cu_ingno": "02002",
    "busi_ty": "610",
    "disclosure_no": "24856",
    "disclosure_ty": "2",
}
TAG = re.compile(r"<[^>]+>")
TR = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.I | re.S)
CELL = re.compile(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", re.I | re.S)


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", TAG.sub(" ", html.unescape(value))).strip()


def rows(text: str) -> list[list[str]]:
    result = []
    for match in TR.finditer(text):
        cells = [clean(cell.group(1)) for cell in CELL.finditer(match.group(1))]
        cells = [cell for cell in cells if cell]
        if cells:
            result.append(cells)
    return result


def main() -> int:
    with httpx.Client(
        timeout=25.0,
        follow_redirects=True,
        headers={"User-Agent": "rate-monitor/1 (+public CU disclosure reconnaissance)"},
    ) as client:
        response = client.get(URL, params=PARAMS)
    table_rows = rows(response.text)
    deposit_rows = [
        row for row in table_rows if row and re.sub(r"\s+", "", row[0]) == "예수부채"
    ]
    header_rows = [row for row in table_rows if row and row[0] == "구분"]
    payload = {
        "mode": "bounded_read_only",
        "source_list_contract": {
            "cuIngno": "02002",
            "disclosureNo": 24856,
            "disclosureTy": "2",
            "disclosureName": "2026년도 상반기 결산공시",
            "bogoTy": "N",
            "chkYn3": "Y",
            "shortFileName_present": True,
        },
        "request": {"path": "/GSSP020000.do", "params": PARAMS},
        "status": response.status_code,
        "content_type": response.headers.get("content-type"),
        "bytes": len(response.content),
        "unit_million_krw_present": "백만원" in clean(response.text),
        "header_rows": header_rows,
        "deposit_rows": deposit_rows,
        "table_row_count": len(table_rows),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    ok = (
        response.status_code == 200
        and payload["unit_million_krw_present"]
        and bool(header_rows)
        and len(deposit_rows) == 1
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
