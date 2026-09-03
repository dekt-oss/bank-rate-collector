#!/usr/bin/env python3
"""Inspect FSB-provided official product URLs for historical special-offer evidence.

This is a read-only evidence harness. A positive page text signal is retained as
diagnostic source evidence, but absence of a signal never proves a normal product
and a page captured after ``as_of`` is never carried back to that historical date.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
from datetime import UTC, date, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx

from rate_monitor.collectors.fsb.adapter import (
    BASE_URL,
    CONNECT_TIMEOUT,
    READ_TIMEOUT,
    REQUEST_INTERVAL_SECONDS,
    USER_AGENT,
    FsbAdapter,
)
from rate_monitor.services.fsb_availability_service import SCREEN_PATH, _fetch_area_rows

RATE_FIELDS_12M = (
    "TOP_12M_DAN",
    "TOP_12M_BOK",
    "JUNG_12M_DAN",
    "JUNG_12M_BOK",
)
SPECIAL_SIGNALS = (
    "특판",
    "특별판매",
    "한정판매",
    "한도소진",
    "판매종료",
)
MAX_PAGE_BYTES = 2_000_000
MAX_REDIRECTS = 5


class _VisibleTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self.parts: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        del attrs
        if tag in {"script", "style", "noscript"}:
            self._ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth and data.strip():
            self.parts.append(data.strip())


def _clean(value: object) -> str:
    return str(value or "").strip()


def product_key(row: dict[str, Any]) -> str:
    institution = _clean(row.get("FINAN_COMP_CODE"))
    product = _clean(row.get("FINAN_PROD_CODE"))
    if not institution or not product:
        raise ValueError("FSB row requires exact institution and product codes")
    return f"{institution}:{product}"


def has_12m_rate(row: dict[str, Any]) -> bool:
    return any(_clean(row.get(field)) for field in RATE_FIELDS_12M)


def _normalized_host(value: str | None) -> str:
    host = str(value or "").strip().lower().rstrip(".")
    return host[4:] if host.startswith("www.") else host


def _host_related(left: str, right: str) -> bool:
    return left == right or left.endswith(f".{right}") or right.endswith(f".{left}")


def approved_product_url(row: dict[str, Any]) -> tuple[str | None, str]:
    """Return a bounded HTTPS URL only when FSB's bank and product hosts align."""

    raw_product_url = _clean(row.get("PRODUCT_URL"))
    raw_bank_url = _clean(row.get("URL"))
    if not raw_product_url:
        return None, "missing_product_url"
    product = urlparse(raw_product_url)
    bank = urlparse(raw_bank_url)
    if product.scheme not in {"http", "https"} or not product.hostname:
        return None, "invalid_product_url"
    product_host = _normalized_host(product.hostname)
    bank_host = _normalized_host(bank.hostname)
    fsb_host = product_host == "fsb.or.kr" or product_host.endswith(".fsb.or.kr")
    if not fsb_host and (not bank_host or not _host_related(product_host, bank_host)):
        return None, "product_bank_host_mismatch"
    if product.scheme == "http":
        product = product._replace(scheme="https")
        return urlunparse(product), "http_upgraded_to_https"
    return urlunparse(product), "approved_https"


def page_signal_evidence(text: str) -> dict[str, Any]:
    normalized = re.sub(r"\s+", " ", text).strip()
    signals: list[str] = []
    snippets: list[str] = []
    for signal in SPECIAL_SIGNALS:
        start = 0
        while True:
            index = normalized.find(signal, start)
            if index < 0:
                break
            if signal not in signals:
                signals.append(signal)
            left = max(0, index - 90)
            right = min(len(normalized), index + len(signal) + 120)
            snippet = normalized[left:right]
            if snippet not in snippets:
                snippets.append(snippet)
            start = index + len(signal)
            if len(snippets) >= 8:
                break
    return {
        "positive_special_signals": signals,
        "signal_snippets": snippets,
        "absence_means_normal": False,
        "historical_as_of_proven": False,
    }


def visible_html_text(html: str) -> str:
    parser = _VisibleTextExtractor()
    parser.feed(html)
    return " ".join(parser.parts)


def _decode(response: httpx.Response) -> str:
    content = response.content[:MAX_PAGE_BYTES]
    encoding = response.encoding or "utf-8"
    try:
        return content.decode(encoding)
    except (LookupError, UnicodeDecodeError):
        return content.decode("utf-8", errors="replace")


def _redirect_allowed(source_host: str, target_url: str) -> bool:
    target = urlparse(target_url)
    if target.scheme != "https" or not target.hostname:
        return False
    target_host = _normalized_host(target.hostname)
    return (
        _host_related(source_host, target_host)
        or target_host == "fsb.or.kr"
        or target_host.endswith(".fsb.or.kr")
    )


async def fetch_bounded_page(
    client: httpx.AsyncClient,
    url: str,
) -> tuple[httpx.Response | None, str]:
    current = url
    source_host = _normalized_host(urlparse(url).hostname)
    for _ in range(MAX_REDIRECTS + 1):
        response = await client.get(current, follow_redirects=False)
        if not response.is_redirect:
            return response, "fetched"
        location = response.headers.get("location")
        if not location:
            return None, "redirect_without_location"
        target = str(response.url.join(location))
        if not _redirect_allowed(source_host, target):
            return None, "redirect_host_rejected"
        current = target
    return None, "redirect_limit_exceeded"


async def collect(as_of: date, area: str) -> dict[str, Any]:
    captured_at = datetime.now(UTC)
    timeout = httpx.Timeout(READ_TIMEOUT, connect=CONNECT_TIMEOUT)
    headers = {"User-Agent": USER_AGENT, "Content-Type": "application/json"}
    adapter = FsbAdapter()
    async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
        screen = await client.get(f"{BASE_URL}{SCREEN_PATH}")
        screen.raise_for_status()
        await asyncio.sleep(REQUEST_INTERVAL_SECONDS)
        rows = await _fetch_area_rows(client, adapter, as_of, area)
        candidates = [row for row in rows if has_12m_rate(row)]
        evidence: list[dict[str, Any]] = []
        for row in candidates:
            url, url_status = approved_product_url(row)
            item: dict[str, Any] = {
                "product_key": product_key(row),
                "bank_name": _clean(row.get("BANK_NAME")),
                "product_name": _clean(row.get("PRODUCT_NAME")),
                "product_url": _clean(row.get("PRODUCT_URL")) or None,
                "bank_url": _clean(row.get("URL")) or None,
                "url_status": url_status,
                "fetch_status": "not_attempted",
                "historical_special_offer_flag": None,
                "promotion_allowed": False,
            }
            if url is None:
                evidence.append(item)
                continue
            try:
                response, fetch_status = await fetch_bounded_page(client, url)
            except httpx.HTTPError as exc:
                item["fetch_status"] = f"network_error:{type(exc).__name__}"
                evidence.append(item)
                continue
            item["fetch_status"] = fetch_status
            if response is not None:
                text = visible_html_text(_decode(response))
                item.update(
                    {
                        "http_status": response.status_code,
                        "final_url": str(response.url),
                        "content_type": response.headers.get("content-type"),
                        "content_sha256": hashlib.sha256(response.content).hexdigest(),
                        "page_signals": page_signal_evidence(text),
                    }
                )
            evidence.append(item)
            await asyncio.sleep(REQUEST_INTERVAL_SECONDS)

    fetched = [item for item in evidence if item.get("http_status") == 200]
    signaled = [
        item
        for item in fetched
        if item.get("page_signals", {}).get("positive_special_signals")
    ]
    return {
        "evidence_status": "complete",
        "source": "FSB historical ratedepo PRODUCT_URL and bank-direct page",
        "as_of": as_of.isoformat(),
        "captured_at": captured_at.isoformat(),
        "area": area,
        "production_write": False,
        "raw_area_rows": len(rows),
        "candidate_12m_products": len(candidates),
        "approved_or_upgraded_urls": sum(
            item["url_status"] in {"approved_https", "http_upgraded_to_https"}
            for item in evidence
        ),
        "fetched_http_200": len(fetched),
        "positive_text_signal_pages": len(signaled),
        "historical_classified_products": 0,
        "historical_special_offer_gate": "blocked",
        "gate_reason": "page_capture_after_as_of_cannot_be_carried_back",
        "contract": {
            "positive_text_signal_is_diagnostic_only": True,
            "absence_means_normal": False,
            "page_capture_carryback_allowed": False,
            "name_only_mapping_allowed": False,
        },
        "products": evidence,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of", required=True, type=date.fromisoformat)
    parser.add_argument("--area", default="YN_Busan")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = asyncio.run(collect(args.as_of, args.area))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    summary = {key: value for key, value in result.items() if key != "products"}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
