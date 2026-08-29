from __future__ import annotations

import json
import re
import time
from pathlib import Path

import httpx

from rate_monitor.collectors.cu.funding import (
    BASE,
    LIST_PATH,
    REQUEST_TIMEOUT,
    SUMMARY_PATH,
    USER_AGENT,
    _list_rows,
    extract_table_rows,
)

TARGETS = ("02022", "10154")
YEAR = re.compile(r"(20\d{2})")


def _fetch_list(client: httpx.Client, cu_ingno: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for page in range(1, 21):
        response = client.post(
            f"{BASE}{LIST_PATH}",
            data={"usrId": cu_ingno, "currPage": str(page), "srchVal": "", "btnChk": "N"},
        )
        response.raise_for_status()
        page_rows = _list_rows(response.json())
        rows.extend(page_rows)
        totals = {
            int(str(row.get("listTotalCount")))
            for row in page_rows
            if str(row.get("listTotalCount") or "").isdigit()
        }
        total = next(iter(totals)) if len(totals) == 1 else None
        if not page_rows or (total is not None and len(rows) >= total):
            break
        time.sleep(0.5)
    return rows


def _row_payload(row: dict[str, object]) -> dict[str, object]:
    name = str(row.get("disclosureName") or "")
    return {
        "disclosureNo": row.get("disclosureNo"),
        "disclosureTy": row.get("disclosureTy"),
        "disclosureName": name,
        "regDate": row.get("regDate"),
        "bogoTy": row.get("bogoTy"),
        "chkYn3": row.get("chkYn3"),
        "shortFileName_present": bool(str(row.get("shortFileName") or "").strip()),
        "listTotalCount": row.get("listTotalCount"),
        "explicit_year": int(YEAR.search(name).group(1)) if YEAR.search(name) else None,
    }


def _summary_probe(client: httpx.Client, cu_ingno: str, row: dict[str, object]) -> dict[str, object]:
    params = {
        "cu_ingno": cu_ingno,
        "busi_ty": "610",
        "disclosure_no": str(row.get("disclosureNo")),
        "disclosure_ty": str(row.get("disclosureTy")),
    }
    response = client.get(f"{BASE}{SUMMARY_PATH}", params=params)
    response.raise_for_status()
    table_rows = extract_table_rows(response.text)
    header = next((cells for cells in table_rows if cells and cells[0].replace(" ", "") == "구분"), None)
    deposit = next((cells for cells in table_rows if cells and cells[0].replace(" ", "") == "예수부채"), None)
    return {
        "disclosureNo": row.get("disclosureNo"),
        "disclosureTy": row.get("disclosureTy"),
        "disclosureName": row.get("disclosureName"),
        "status": response.status_code,
        "header": header,
        "deposit_row": deposit,
        "unit_million_krw_present": "백만원" in response.text,
    }


def main() -> int:
    output: dict[str, object] = {"mode": "bounded_read_only", "targets": {}}
    with httpx.Client(timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT}) as client:
        for cu_ingno in TARGETS:
            rows = _fetch_list(client, cu_ingno)
            qualifying = [
                row
                for row in rows
                if str(row.get("disclosureTy") or "") in {"1", "2"}
                and str(row.get("bogoTy") or "") == "Y"
                and str(row.get("chkYn3") or "") == "Y"
                and bool(str(row.get("shortFileName") or "").strip())
            ]
            target: dict[str, object] = {
                "row_count": len(rows),
                "qualifying_count": len(qualifying),
                "qualifying_rows": [_row_payload(row) for row in qualifying],
            }
            if cu_ingno == "10154":
                probes = []
                for row in qualifying[:12]:
                    probes.append(_summary_probe(client, cu_ingno, row))
                    time.sleep(0.5)
                target["summary_probes"] = probes
            output["targets"][cu_ingno] = target

    path = Path("publish/cu-funding-edge-probe.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
