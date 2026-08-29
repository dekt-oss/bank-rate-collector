#!/usr/bin/env python3
"""Read-only bounded reconnaissance for official CU management disclosures.

Goal: prove a deterministic contract from the existing rate-source ``cuIngno``
to the central CU management-disclosure list and its structured disclosure
identifiers. This probe is intentionally tiny: two repository-captured control
institutions, page 1 only, no document download, no nationwide enumeration and
no application DB write.
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any

import httpx

OUT = Path("docs/source-recon/cu-funding-disclosure-recon-20260829.json")
BASE = "https://www.cu.co.kr"
DISCLOSURE_PATH = "/cu/ad/disclosureList.do"
LIST_PATH = "/cu/ad/dis/getDisclosureList.do"
TIMEOUT = 25.0
USER_AGENT = "rate-monitor/1 (+public CU disclosure contract reconnaissance)"

# Existing official CU rate fixture contains these exact cuIngno/name pairs.
PROBES = (
    ("02002", "광안"),
    ("02022", "HJ중공업"),
)

DO_PATH = re.compile(r"[\"']([^\"']*?\.do(?:\?[^\"']*)?)[\"']")
INPUT = re.compile(
    r"<input\b[^>]*\bname=[\"']([^\"']+)[\"'][^>]*>", re.I
)
VALUE = re.compile(r"\bvalue=[\"']([^\"']*)[\"']", re.I)
FORM = re.compile(r"<form\b([^>]*)>", re.I)
ACTION = re.compile(r"\baction=[\"']([^\"']*)[\"']", re.I)
METHOD = re.compile(r"\bmethod=[\"']([^\"']*)[\"']", re.I)

KEYWORDS = (
    "cuNo",
    "cuMbrCd",
    "cuSearchTab",
    "getDisclosureList.do",
    "dwldDisData.do",
    "GSSP020000.do",
    "GSSP040000.do",
    "경영공시",
    "요약공시",
)

LIST_SAFE_FIELDS = (
    "cuIngno",
    "disclosureName",
    "regDate",
    "disclosureNo",
    "disclosureTy",
    "bogoTy",
    "chkYn1",
    "chkYn2",
    "chkYn3",
    "disclosureFileName",
    "auditFileName",
    "shortFileName",
    "listTotalCount",
)


def _clean(text: str) -> str:
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _snippets(text: str, keyword: str, *, radius: int = 420, limit: int = 12) -> list[str]:
    lower = text.lower()
    needle = keyword.lower()
    out: list[str] = []
    start = 0
    while len(out) < limit:
        index = lower.find(needle, start)
        if index < 0:
            break
        left = max(0, index - radius)
        right = min(len(text), index + len(keyword) + radius)
        snippet = _clean(text[left:right])
        if snippet and snippet not in out:
            out.append(snippet)
        start = index + len(keyword)
    return out


def _inputs(text: str) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    for match in INPUT.finditer(text):
        tag = match.group(0)
        name = match.group(1)
        if not any(token.lower() in name.lower() for token in ("cu", "search", "page")):
            continue
        value_match = VALUE.search(tag)
        found.append({"name": name, "value": value_match.group(1) if value_match else ""})
    return found[:80]


def _forms(text: str) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for match in FORM.finditer(text):
        attrs = match.group(1)
        action = ACTION.search(attrs)
        method = METHOD.search(attrs)
        result.append(
            {
                "action": action.group(1) if action else "",
                "method": (method.group(1) if method else "GET").upper(),
            }
        )
    return result[:20]


def _paths(text: str) -> list[str]:
    paths = sorted({html.unescape(match.group(1)) for match in DO_PATH.finditer(text)})
    return [path for path in paths if "disclos" in path.lower() or "/cu/ad/" in path][:120]


def _page_request(
    client: httpx.Client, params: dict[str, str], label: str
) -> dict[str, object]:
    response = client.get(f"{BASE}{DISCLOSURE_PATH}", params=params)
    text = response.text
    title_match = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
    return {
        "label": label,
        "request_path": DISCLOSURE_PATH,
        "request_params": params,
        "status": response.status_code,
        "content_type": response.headers.get("content-type"),
        "bytes": len(response.content),
        "title": _clean(title_match.group(1)) if title_match else None,
        "forms": _forms(text),
        "relevant_inputs": _inputs(text),
        "candidate_do_paths": _paths(text),
        "keyword_snippets": {
            keyword: _snippets(text, keyword)
            for keyword in KEYWORDS
            if keyword.lower() in text.lower()
        },
    }


def _json_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("list", "data", "items", "result"):
            value = payload.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
    return []


def _list_request(
    client: httpx.Client, *, cu_no: str, expected_name: str
) -> dict[str, object]:
    request_data = {
        "usrId": cu_no,
        "currPage": "1",
        "srchVal": "",
        "btnChk": "N",
    }
    response = client.post(f"{BASE}{LIST_PATH}", data=request_data)
    content_type = response.headers.get("content-type")
    payload: Any = None
    parse_error: str | None = None
    try:
        payload = response.json()
    except ValueError as exc:
        parse_error = f"{type(exc).__name__}: {exc}"

    rows = _json_rows(payload)
    sampled = [
        {field: row.get(field) for field in LIST_SAFE_FIELDS if field in row}
        for row in rows[:10]
    ]
    returned_ids = sorted(
        {
            str(row.get("cuIngno") or "").strip()
            for row in rows
            if str(row.get("cuIngno") or "").strip()
        }
    )
    row_keys = sorted({key for row in rows for key in row})
    total_values = sorted(
        {
            int(str(row.get("listTotalCount")))
            for row in rows
            if str(row.get("listTotalCount") or "").isdigit()
        }
    )
    return {
        "label": f"disclosure_list_{cu_no}_{expected_name}",
        "request_path": LIST_PATH,
        "request_data": request_data,
        "status": response.status_code,
        "content_type": content_type,
        "bytes": len(response.content),
        "parse_error": parse_error,
        "payload_type": type(payload).__name__ if payload is not None else None,
        "row_count": len(rows),
        "row_keys": row_keys,
        "returned_cu_ingno": returned_ids,
        "identity_exact": returned_ids == [cu_no] if rows else False,
        "list_total_count_values": total_values,
        "sample_rows": sampled,
    }


def main() -> int:
    pages: list[dict[str, object]] = []
    lists: list[dict[str, object]] = []
    with httpx.Client(
        timeout=TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        pages.append(_page_request(client, {"mi": "100518"}, "central_disclosure_base"))
        for cu_no, short_name in PROBES:
            params = {
                "mi": "100518",
                "cuSearchTab": "5",
                "cuNo": cu_no,
                "searchTxt": short_name,
            }
            pages.append(_page_request(client, params, f"selected_{cu_no}_{short_name}"))
            lists.append(_list_request(client, cu_no=cu_no, expected_name=short_name))

    report = {
        "mode": "read_only_bounded_no_application_db_write",
        "purpose": (
            "prove CU central disclosure list contract from existing rate cuIngno, "
            "without nationwide enumeration or document downloads"
        ),
        "rate_fixture_controls": [
            {"cuIngno": cu_no, "cuNm": short_name} for cu_no, short_name in PROBES
        ],
        "page_contract": pages,
        "list_contract": lists,
        "notes": [
            "cuIngno values are sourced from the repository's captured official CU rate fixture.",
            "Only two control institutions and page 1 are requested.",
            "No disclosure files or application DB rows are downloaded/written by this stage.",
            "Production persistence remains forbidden until amount/date/unit semantics are separately verified.",
        ],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    for row in pages:
        print(
            f"{row['label']}: status={row['status']} bytes={row['bytes']} "
            f"paths={len(row['candidate_do_paths'])} inputs={len(row['relevant_inputs'])}"
        )
    for row in lists:
        print(
            f"{row['label']}: status={row['status']} rows={row['row_count']} "
            f"returned={row['returned_cu_ingno']} identity_exact={row['identity_exact']}"
        )

    page_ok = all(row["status"] == 200 for row in pages)
    list_ok = all(
        row["status"] == 200
        and row["parse_error"] is None
        and row["row_count"] > 0
        and row["identity_exact"] is True
        for row in lists
    )
    return 0 if page_ok and list_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
