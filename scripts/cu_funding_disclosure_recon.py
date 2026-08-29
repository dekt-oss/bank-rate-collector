#!/usr/bin/env python3
"""Read-only bounded reconnaissance for official CU management disclosures.

Goal: determine whether the central CU disclosure page exposes a deterministic
contract from the existing rate-source ``cuIngno`` (approval number) to a
management-disclosure listing/document that contains deposit liabilities.

This script performs only a handful of GET requests against public official CU
pages. It does not log in, bypass blocks, enumerate the nationwide population,
or write application data. It stores structural evidence/snippets only.
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path
from urllib.parse import urlencode

import httpx

OUT = Path("docs/source-recon/cu-funding-disclosure-recon-20260829.json")
BASE = "https://www.cu.co.kr"
DISCLOSURE_PATH = "/cu/ad/disclosureList.do"
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
    "disclosure",
    "경영공시",
    "요약공시",
    "공시자료",
    "file",
    "download",
    "ajax",
)


def _clean(text: str) -> str:
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _snippets(text: str, keyword: str, *, radius: int = 220, limit: int = 8) -> list[str]:
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


def _request(client: httpx.Client, params: dict[str, str], label: str) -> dict[str, object]:
    response = client.get(f"{BASE}{DISCLOSURE_PATH}", params=params)
    text = response.text
    return {
        "label": label,
        "request_path": DISCLOSURE_PATH,
        "request_params": params,
        "status": response.status_code,
        "content_type": response.headers.get("content-type"),
        "bytes": len(response.content),
        "title": _clean(re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S).group(1))
        if re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
        else None,
        "forms": _forms(text),
        "relevant_inputs": _inputs(text),
        "candidate_do_paths": _paths(text),
        "keyword_snippets": {
            keyword: _snippets(text, keyword) for keyword in KEYWORDS if keyword.lower() in text.lower()
        },
    }


def main() -> int:
    results: list[dict[str, object]] = []
    with httpx.Client(
        timeout=TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        results.append(
            _request(client, {"mi": "100518"}, "central_disclosure_base")
        )
        for cu_no, short_name in PROBES:
            params = {
                "mi": "100518",
                "cuSearchTab": "5",
                "cuNo": cu_no,
                "searchTxt": short_name,
            }
            results.append(_request(client, params, f"selected_{cu_no}_{short_name}"))

    report = {
        "mode": "read_only_bounded_no_application_db_write",
        "purpose": (
            "discover deterministic CU central management-disclosure contract from "
            "existing rate cuIngno without nationwide enumeration"
        ),
        "rate_fixture_controls": [
            {"cuIngno": cu_no, "cuNm": short_name} for cu_no, short_name in PROBES
        ],
        "requests": results,
        "notes": [
            "cuIngno values are sourced from the repository's captured official CU rate fixture.",
            "No credentials, cookies, personal data, or full disclosure documents are persisted.",
            "A later collector is forbidden until exact listing/document identity and amount semantics are live-verified.",
        ],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    for row in results:
        print(
            f"{row['label']}: status={row['status']} bytes={row['bytes']} "
            f"paths={len(row['candidate_do_paths'])} inputs={len(row['relevant_inputs'])}"
        )
    return 0 if all(row["status"] == 200 for row in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
