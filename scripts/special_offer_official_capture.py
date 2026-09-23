#!/usr/bin/env python3
"""Read-only official special-offer evidence candidate capture.

This script intentionally does not import collector writers, SQLAlchemy, or special-offer
append services. It captures only configured HTTPS bank-direct surfaces, preserves raw
hashes, fails closed unless the exact configured product and explicit source assertion
are present, and can audit existing FSB exact-code identity links in a read-only DB.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

USER_AGENT = "Mozilla/5.0 (compatible; bank-rate-collector-special-offer-evidence/1.0)"
SUPPORTED_PARSERS = {
    "welcome_product_special",
    "ibk_product_special",
    "daishin_special_notice",
}


class EvidenceCaptureError(RuntimeError):
    pass


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in {"script", "style"}:
            self._ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth and data.strip():
            self.parts.append(data.strip())


def _decode(content: bytes, charset: str | None) -> str:
    for candidate in (charset, "utf-8", "cp949", "euc-kr"):
        if not candidate:
            continue
        try:
            return content.decode(candidate)
        except (LookupError, UnicodeDecodeError):
            continue
    return content.decode("utf-8", errors="replace")


def _text(content: bytes, charset: str | None) -> str:
    parser = _TextExtractor()
    parser.feed(_decode(content, charset))
    return re.sub(r"\s+", " ", " ".join(parser.parts)).strip()


def _sha256(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _date_token(value: str) -> str:
    return value.replace(".", "-").replace("/", "-").strip("- ")


def _period(text: str) -> tuple[str | None, str | None]:
    match = re.search(
        r"(20\d{2}[./-]\d{1,2}[./-]\d{1,2})\s*(?:\([^)]*\))?\s*~\s*"
        r"(20\d{2}[./-]\d{1,2}[./-]\d{1,2})",
        text,
    )
    if not match:
        return None, None
    return _date_token(match.group(1)), _date_token(match.group(2))


def _require_product(text: str, product_name: str) -> None:
    if product_name not in text:
        raise EvidenceCaptureError(f"exact configured product title missing: {product_name}")


def parse_surface(target: dict[str, Any], content: bytes, charset: str | None) -> dict[str, Any]:
    surface = target["surface"]
    parser_name = str(surface["parser"])
    product_name = str(target["product_name"])
    text = _text(content, charset)
    _require_product(text, product_name)

    effective_from: str | None = None
    effective_to: str | None = None
    assertion_marker: str

    if parser_name == "welcome_product_special":
        markers = (
            "웰컴 한정 특판",
            "한정 특판",
            "특판 상품",
        )
        assertion_marker = next((marker for marker in markers if marker in text), "")
        if not assertion_marker:
            raise EvidenceCaptureError("Welcome product page has no explicit special-sale assertion")
        effective_from, effective_to = _period(text)
    elif parser_name == "ibk_product_special":
        if "특판내용" not in text:
            raise EvidenceCaptureError("IBK product detail has no structured 특판내용 section")
        if f"특판 {product_name.removeprefix('특판 ')}" not in text and not product_name.startswith("특판 "):
            raise EvidenceCaptureError("IBK product title is not explicitly marked as special sale")
        assertion_marker = "특판내용"
        effective_from, effective_to = _period(text)
    elif parser_name == "daishin_special_notice":
        if "특판 안내" not in text or product_name not in text:
            raise EvidenceCaptureError("Daishin notice lacks explicit product-level special-sale notice")
        assertion_marker = "특판 안내"
        effective_from, effective_to = _period(text)
        if not effective_from or not effective_to:
            raise EvidenceCaptureError("Daishin versioned special notice lacks explicit effective period")
    else:
        raise EvidenceCaptureError(f"unsupported parser: {parser_name}")

    return {
        "classification": "confirmed_special",
        "identity_scope": "exact_product",
        "explicit_assertion": "confirmed_special",
        "assertion_marker": assertion_marker,
        "source_effective_from": effective_from,
        "source_effective_to": effective_to,
        "availability": "not_inferred",
    }


def _validate_config(config: dict[str, Any]) -> None:
    if config.get("version") != 1:
        raise ValueError("special-offer target config version must be 1")
    seen: set[str] = set()
    for target in config.get("targets", []):
        target_id = str(target.get("target_id") or "").strip()
        if not target_id or target_id in seen:
            raise ValueError(f"invalid or duplicate target_id: {target_id!r}")
        seen.add(target_id)
        if not str(target.get("product_name") or "").strip():
            raise ValueError(f"{target_id}: product_name is required")
        surface = target.get("surface")
        if not isinstance(surface, dict):
            raise ValueError(f"{target_id}: surface is required")
        url = str(surface.get("url") or "")
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError(f"{target_id}: only configured HTTPS URLs are allowed")
        if surface.get("parser") not in SUPPORTED_PARSERS:
            raise ValueError(f"{target_id}: unsupported parser")


def fetch_https(url: str, *, timeout: float = 30.0) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read()
                return {
                    "body": body,
                    "status": int(getattr(response, "status", 200)),
                    "final_url": response.geturl(),
                    "content_type": response.headers.get_content_type(),
                    "charset": response.headers.get_content_charset(),
                }
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(2)
    raise EvidenceCaptureError(f"official evidence fetch failed: {url}: {last_error}")


def capture_candidates(
    config: dict[str, Any],
    raw_dir: Path,
    *,
    captured_at: str | None = None,
) -> dict[str, Any]:
    _validate_config(config)
    raw_dir.mkdir(parents=True, exist_ok=True)
    captured_at = captured_at or datetime.now(UTC).isoformat()

    candidates: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    captures: list[dict[str, Any]] = []

    for target in config["targets"]:
        surface = target["surface"]
        target_id = str(target["target_id"])
        url = str(surface["url"])
        try:
            response = fetch_https(url)
            body = response["body"]
            if not isinstance(body, bytes) or not body:
                raise EvidenceCaptureError("empty HTTP body")
            raw_path = raw_dir / f"{target_id}.html"
            raw_path.write_bytes(body)
            parsed = parse_surface(target, body, response.get("charset"))
            capture = {
                "target_id": target_id,
                "url": url,
                "final_url": response.get("final_url"),
                "http_status": response.get("status"),
                "content_type": response.get("content_type"),
                "charset": response.get("charset"),
                "raw_path": str(raw_path),
                "content_hash": _sha256(body),
                "content_length": len(body),
            }
            captures.append(capture)
            candidates.append(
                {
                    "target_id": target_id,
                    "institution": target["institution"],
                    "product_name": target["product_name"],
                    "product_locator": surface["product_locator"],
                    "evidence_kind": surface["evidence_kind"],
                    "source_locator": url,
                    "captured_at": captured_at,
                    **parsed,
                    "content_hash": capture["content_hash"],
                    "db_write": False,
                }
            )
        except Exception as exc:  # noqa: BLE001 - evidence failure must remain explicit.
            failures.append(
                {
                    "target_id": target_id,
                    "url": url,
                    "reason": f"{type(exc).__name__}: {exc}",
                }
            )

    return {
        "captured_at": captured_at,
        "policy": config["policy"],
        "scope": {
            "mode": "configured_bank_direct_read_only_candidate_capture",
            "db_write": False,
            "canonical_mutated": False,
            "source_precedence_changed": False,
            "availability_inferred": False,
        },
        "coverage": {
            "configured_targets": len(config["targets"]),
            "successful_captures": len(captures),
            "candidate_evidence": len(candidates),
            "failures": len(failures),
        },
        "captures": captures,
        "candidates": candidates,
        "failures": failures,
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
                "binding_status": "unique_candidate" if len(matched) == 1 else (
                    "no_exact_alias_match" if not matched else "ambiguous_exact_alias_match"
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


def _load(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object: {path}")
    return data


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    capture = sub.add_parser("capture")
    capture.add_argument("--config", type=Path, required=True)
    capture.add_argument("--raw-dir", type=Path, required=True)
    capture.add_argument("--out", type=Path, required=True)

    audit = sub.add_parser("audit-bindings")
    audit.add_argument("--config", type=Path, required=True)
    audit.add_argument("--db", type=Path, required=True)
    audit.add_argument("--out", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    config = _load(args.config)
    if args.command == "capture":
        payload = capture_candidates(config, args.raw_dir)
        _write(args.out, payload)
        print(json.dumps(payload["coverage"], ensure_ascii=False, sort_keys=True))
        return 1 if payload["coverage"]["failures"] else 0
    payload = audit_fsb_bindings(config, args.db)
    _write(args.out, payload)
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
