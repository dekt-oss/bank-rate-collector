#!/usr/bin/env python3
"""Read-only official special-offer capture, terms extraction, and binding audit.

This script never writes canonical rate data or product_special_offer_evidence.
It fetches only repository-configured HTTPS pages, extracts explicit product-level
special-offer terms, keeps availability separate from classification, and can
audit existing FSB exact-code identity links using a read-only SQLite connection.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import urllib.parse
from datetime import UTC, date, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import httpx

USER_AGENT = "Mozilla/5.0 (compatible; bank-rate-collector-special-offer-audit/2.0)"
AVAILABILITY = frozenset({"confirmed_active", "confirmed_ended", "unknown"})
TERMS_PARSERS = frozenset(
    {"welcome_likit", "welcome_digiloca", "ibk_blue_dragon", "daishin_corporate_free"}
)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in {"script", "style"}:
            self._ignored += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._ignored:
            self._ignored -= 1

    def handle_data(self, data: str) -> None:
        if not self._ignored and data.strip():
            self.parts.append(data.strip())


def _text(body: bytes, charset: str | None = None) -> str:
    for encoding in (charset, "utf-8", "cp949", "euc-kr"):
        if not encoding:
            continue
        try:
            decoded = body.decode(encoding)
            break
        except (LookupError, UnicodeDecodeError):
            continue
    else:
        decoded = body.decode("utf-8", errors="replace")
    parser = _TextExtractor()
    parser.feed(decoded)
    return re.sub(r"\s+", " ", " ".join(parser.parts)).strip()


def _iso_date(value: str) -> str:
    parts = [part for part in re.split(r"[./-]", value) if part]
    if len(parts) != 3:
        raise ValueError(f"unsupported date token: {value}")
    year, month, day = (int(part) for part in parts)
    return date(year, month, day).isoformat()


def _period(text: str) -> tuple[str | None, str | None]:
    match = re.search(
        r"(20\d{2}[./-]\d{1,2}[./-]\d{1,2})\.?\s*(?:\([^)]*\))?\s*~\s*"
        r"(20\d{2}[./-]\d{1,2}[./-]\d{1,2})",
        text,
    )
    if not match:
        return None, None
    return _iso_date(match.group(1)), _iso_date(match.group(2))


def _first(pattern: str, text: str, *, flags: int = 0) -> str | None:
    match = re.search(pattern, text, flags)
    return match.group(1).strip() if match else None


def _amount_krw(text: str | None) -> int | None:
    if not text:
        return None
    match = re.search(r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*억", text)
    if not match:
        return None
    value = float(match.group(1).replace(",", ""))
    return int(value * 100_000_000)


def _quota_accounts(text: str | None) -> int | None:
    if not text:
        return None
    match = re.search(r"([0-9][0-9,]*)\s*만좌", text)
    if match:
        return int(match.group(1).replace(",", "")) * 10_000
    match = re.search(r"([0-9][0-9,]*)\s*좌", text)
    return int(match.group(1).replace(",", "")) if match else None


def _terms(parser_name: str, text: str) -> dict[str, Any]:
    sale_start, sale_end = _period(text)
    terms: dict[str, Any] = {
        "special_rate": None,
        "special_rate_basis": None,
        "sale_start": sale_start,
        "sale_end": sale_end,
        "quota_text": None,
        "quota_amount_krw": None,
        "quota_accounts": None,
        "eligibility_text": None,
        "early_termination_text": None,
    }

    if parser_name == "welcome_likit":
        quota = _first(r"(1만좌\s*한도)", text)
        eligibility = _first(r"가입대상\s+(.+?)\s+가입기간", text)
        early = _first(r"이벤트 기간\s*:\s*([^·※]+?한도\s*소진시까지)", text)
        terms.update(
            quota_text=quota,
            quota_accounts=_quota_accounts(quota),
            eligibility_text=eligibility,
            early_termination_text=early,
            special_rate_basis="explicit_special_rate_not_single-valued_on_product_detail",
        )
    elif parser_name == "welcome_digiloca":
        quota = _first(r"(1만좌\s*한도)", text)
        eligibility = _first(r"가입대상\s+(.+?)\s+가입기간", text)
        early = _first(r"(특판소진\s*시\s*조기\s*종료)", text)
        terms.update(
            quota_text=quota,
            quota_accounts=_quota_accounts(quota),
            eligibility_text=eligibility,
            early_termination_text=early,
            special_rate_basis="base_plus_explicit_bonus_conditions_not_collapsed",
        )
    elif parser_name == "ibk_blue_dragon":
        quota = _first(r"(계약고\s*[0-9,]+억원\s*한도)", text)
        rate = _first(r"금리\s*:\s*([0-9]+(?:\.[0-9]+)?)%", text)
        eligibility = _first(r"가입대상\s+(.+?)\s+이자지급", text)
        terms.update(
            special_rate=rate,
            special_rate_basis="explicit_special_section_rate",
            quota_text=quota,
            quota_amount_krw=_amount_krw(quota),
            eligibility_text=eligibility,
        )
    elif parser_name == "daishin_corporate_free":
        rate = _first(r"특판금리\s*:\s*연\s*([0-9]+(?:\.[0-9]+)?)%", text)
        quota = _first(r"([0-9][0-9,]*억\s*한도)", text)
        target = _first(r"대상\s*:\s*(.+?)\s*상품안내", text)
        account = _first(r"가입대상\s*:\s*(.+?)\s+나\.", text)
        early = _first(r"([0-9][0-9,]*억\s*한도\s*소진시\s*조기마감)", text)
        eligibility = " / ".join(part for part in (target, account) if part) or None
        terms.update(
            special_rate=rate,
            special_rate_basis="explicit_notice_special_rate",
            quota_text=quota,
            quota_amount_krw=_amount_krw(quota),
            eligibility_text=eligibility,
            early_termination_text=early,
        )
    else:
        raise ValueError(f"unsupported terms_parser: {parser_name}")
    return terms


def _validate_config(config: dict[str, Any]) -> None:
    if config.get("version") != 2:
        raise ValueError("special-offer official target config version must be 2")
    seen: set[str] = set()
    for target in config.get("targets", []):
        target_id = str(target.get("target_id") or "").strip()
        if not target_id or target_id in seen:
            raise ValueError(f"invalid or duplicate target_id: {target_id!r}")
        seen.add(target_id)
        url = str(target.get("url") or "")
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError(f"{target_id}: only configured HTTPS URLs are allowed")
        if str(target.get("terms_parser") or "") not in TERMS_PARSERS:
            raise ValueError(f"{target_id}: unsupported terms_parser")
        if not str(target.get("official_product_key") or "").strip():
            raise ValueError(f"{target_id}: official_product_key is required")
        phrases = target.get("required_phrases")
        if not isinstance(phrases, list) or not phrases:
            raise ValueError(f"{target_id}: required_phrases must be non-empty")
        availability = target.get("availability_source")
        if availability is not None:
            aurl = str(availability.get("url") or "")
            aparsed = urllib.parse.urlparse(aurl)
            if aparsed.scheme != "https" or not aparsed.hostname:
                raise ValueError(f"{target_id}: availability source must use HTTPS")
            if availability.get("status") not in AVAILABILITY - {"unknown"}:
                raise ValueError(f"{target_id}: availability source status is invalid")


def fetch_https(url: str, *, timeout: float = 30.0) -> dict[str, Any]:
    # httpx uses the project's certifi trust store while keeping TLS verification ON.
    # Do not fall back to verify=False for source-specific certificate-chain problems.
    with httpx.Client(
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
        timeout=timeout,
    ) as client:
        response = client.get(url)
        response.raise_for_status()
        body = response.content
        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip() or None
        return {
            "body": body,
            "status": response.status_code,
            "final_url": str(response.url),
            "charset": response.encoding,
            "content_type": content_type,
        }


def _identity_ok(target: dict[str, Any], final_url: str) -> bool:
    official_key = str(target["official_product_key"])
    if official_key.startswith("notice:"):
        notice_id = official_key.split(":", 1)[1]
        query = urllib.parse.parse_qs(urllib.parse.urlparse(final_url).query)
        return notice_id in query.get("no", [])
    return official_key in final_url


def _availability_from_period(
    terms: dict[str, Any], *, observed_at: datetime
) -> tuple[str, str | None]:
    end = terms.get("sale_end")
    if end and date.fromisoformat(str(end)) < observed_at.date():
        return "confirmed_ended", f"explicit sale period ended on {end}"
    return "unknown", None


def _availability_from_surface(
    target: dict[str, Any],
    response: dict[str, Any] | None,
    *,
    observed_at: datetime,
    terms: dict[str, Any],
) -> dict[str, Any]:
    status, assertion = _availability_from_period(terms, observed_at=observed_at)
    source_locator = None
    availability = target.get("availability_source")
    if availability and response is not None:
        text = _text(response["body"], response.get("charset"))
        product = str(target["product_name"])
        product_at = text.find(product)
        required = str(availability.get("required_phrase") or "")
        if product_at >= 0:
            local = text[product_at : product_at + 500]
            if required and required in local:
                status = str(availability["status"])
                assertion = f"{product} / {required}"
                source_locator = str(response.get("final_url") or availability["url"])
    return {
        "status": status,
        "assertion_text": assertion,
        "observed_at": observed_at.isoformat(),
        "source_locator": source_locator,
    }


def evaluate_target(
    target: dict[str, Any],
    response: dict[str, Any],
    *,
    observed_at: datetime,
    availability_response: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body = response["body"]
    if not isinstance(body, bytes) or not body:
        raise ValueError("empty HTTP body")
    page_text = _text(body, response.get("charset"))
    missing = [
        phrase
        for phrase in target["required_phrases"]
        if str(phrase).strip() not in page_text
    ]
    final_url = str(response.get("final_url") or target["url"])
    identity_ok = _identity_ok(target, final_url)
    terms = _terms(str(target["terms_parser"]), page_text)
    availability = _availability_from_surface(
        target,
        availability_response,
        observed_at=observed_at,
        terms=terms,
    )
    return {
        "target_id": target["target_id"],
        "institution": target["institution"],
        "product_name": target["product_name"],
        "official_product_key": target["official_product_key"],
        "source_locator": final_url,
        "http_status": response.get("status"),
        "content_type": response.get("content_type"),
        "content_sha256": "sha256:" + hashlib.sha256(body).hexdigest(),
        "identity_marker_present": identity_ok,
        "explicit_phrases_present": not missing,
        "missing_required_phrases": missing,
        "classification_candidate": (
            "confirmed_special_candidate" if identity_ok and not missing else "unverified"
        ),
        "evidence_kind_candidate": (
            "versioned_product_scope_observation"
            if terms.get("sale_start")
            else "explicit_source_field"
        ),
        "special_offer_terms": terms,
        "availability": availability,
        "fsb_binding_status": "not_checked",
        "canonical_mutated": False,
    }


def capture(config: dict[str, Any], raw_dir: Path) -> dict[str, Any]:
    _validate_config(config)
    raw_dir.mkdir(parents=True, exist_ok=True)
    observed_at = datetime.now(UTC)
    captures: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    availability_failures: list[dict[str, Any]] = []
    for target in config["targets"]:
        try:
            response = fetch_https(str(target["url"]))
            body = response["body"]
            raw_path = raw_dir / f"{target['target_id']}.html"
            raw_path.write_bytes(body)
            availability_response = None
            availability = target.get("availability_source")
            if availability:
                try:
                    availability_response = fetch_https(str(availability["url"]))
                    (raw_dir / f"{target['target_id']}-availability.html").write_bytes(
                        availability_response["body"]
                    )
                except Exception as exc:  # noqa: BLE001 - availability fails closed.
                    availability_failures.append(
                        {
                            "target_id": target["target_id"],
                            "reason": f"{type(exc).__name__}: {exc}",
                        }
                    )
            result = evaluate_target(
                target,
                response,
                observed_at=observed_at,
                availability_response=availability_response,
            )
            result["raw_path"] = str(raw_path)
            captures.append(result)
        except Exception as exc:  # noqa: BLE001 - audit failure is output evidence.
            failures.append(
                {
                    "target_id": target.get("target_id"),
                    "reason": f"{type(exc).__name__}: {exc}",
                }
            )
    return {
        "observed_at": observed_at.isoformat(),
        "policy": config.get("policy"),
        "scope": {
            "mode": "configured_official_read_only_capture",
            "production_state_mutated": False,
            "canonical_rate_state_mutated": False,
            "special_offer_registry_mutated": False,
            "availability_inferred_from_future_end_date": False,
        },
        "coverage": {
            "configured_targets": len(config["targets"]),
            "successful_captures": len(captures),
            "failures": len(failures),
            "availability_failures": len(availability_failures),
        },
        "captures": captures,
        "failures": failures,
        "availability_failures": availability_failures,
    }


def audit_fsb_bindings(config: dict[str, Any], db_path: Path) -> dict[str, Any]:
    _validate_config(config)
    if not db_path.exists():
        raise FileNotFoundError(db_path)
    conn = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT p.id AS product_id, p.name AS product_name, "
            "i.canonical_name AS institution_name, l.source_entity_key "
            "FROM products p "
            "JOIN institutions i ON i.id=p.institution_id "
            "JOIN source_entity_links l ON l.entity_id=p.id "
            " AND l.source_id='fsb' AND l.entity_type='product' "
            " AND l.match_method='exact_code' AND l.valid_to IS NULL"
        ).fetchall()
    finally:
        conn.close()

    results: list[dict[str, Any]] = []
    for target in config["targets"]:
        institutions = set(target.get("fsb_institution_names") or [])
        products = set(target.get("fsb_product_names") or [])
        matched = [
            {
                "product_id": str(row["product_id"]),
                "product_name": str(row["product_name"]),
                "institution_name": str(row["institution_name"]),
                "source_entity_key": str(row["source_entity_key"]),
            }
            for row in rows
            if row["institution_name"] in institutions and row["product_name"] in products
        ]
        results.append(
            {
                "target_id": target["target_id"],
                "match_count": len(matched),
                "binding_status": (
                    "unique_candidate"
                    if len(matched) == 1
                    else "no_exact_alias_match"
                    if not matched
                    else "ambiguous_exact_alias_match"
                ),
                "matches": matched,
                "confirmation_written": False,
            }
        )
    return {
        "scope": {
            "db_mode": "read_only",
            "confirmation_written": False,
            "exact_code_required": True,
            "alias_match_is_confirmation": False,
        },
        "targets": results,
        "unique_candidate_count": sum(
            item["binding_status"] == "unique_candidate" for item in results
        ),
    }


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    capture_parser = sub.add_parser("capture")
    capture_parser.add_argument("--config", type=Path, required=True)
    capture_parser.add_argument("--raw-dir", type=Path, required=True)
    capture_parser.add_argument("--out", type=Path, required=True)
    audit_parser = sub.add_parser("audit-bindings")
    audit_parser.add_argument("--config", type=Path, required=True)
    audit_parser.add_argument("--db", type=Path, required=True)
    audit_parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    if args.command == "capture":
        result = capture(config, args.raw_dir)
    else:
        result = audit_fsb_bindings(config, args.db)
    _write(args.out, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
