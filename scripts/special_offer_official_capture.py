#!/usr/bin/env python3
"""Read-only capture of explicit official special-offer product evidence.

This script never writes canonical rate data or product_special_offer_evidence.
It fetches only repository-configured HTTPS pages and emits evidence candidates
that still require exact FSB SourceEntityLink binding before confirmation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

USER_AGENT = "Mozilla/5.0 (compatible; bank-rate-collector-special-offer-audit/1.0)"


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


def _validate_config(config: dict[str, Any]) -> None:
    if config.get("version") != 1:
        raise ValueError("special-offer official target config version must be 1")
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
        if not str(target.get("official_product_key") or "").strip():
            raise ValueError(f"{target_id}: official_product_key is required")
        phrases = target.get("required_phrases")
        if not isinstance(phrases, list) or not phrases:
            raise ValueError(f"{target_id}: required_phrases must be non-empty")


def fetch_https(url: str, *, timeout: float = 30.0) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read()
        return {
            "body": body,
            "status": int(getattr(response, "status", 200)),
            "final_url": response.geturl(),
            "charset": response.headers.get_content_charset(),
            "content_type": response.headers.get_content_type(),
        }


def evaluate_target(target: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
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
    official_key = str(target["official_product_key"])
    identity_ok = official_key in final_url or official_key.startswith("notice:")
    return {
        "target_id": target["target_id"],
        "institution": target["institution"],
        "product_name": target["product_name"],
        "official_product_key": official_key,
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
            if target.get("effective_from")
            else "explicit_source_field"
        ),
        "effective_from": target.get("effective_from"),
        "effective_to": target.get("effective_to"),
        "fsb_binding_status": "not_checked",
        "canonical_mutated": False,
    }


def capture(config: dict[str, Any], raw_dir: Path) -> dict[str, Any]:
    _validate_config(config)
    raw_dir.mkdir(parents=True, exist_ok=True)
    observed_at = datetime.now(UTC).isoformat()
    captures: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for target in config["targets"]:
        try:
            response = fetch_https(str(target["url"]))
            body = response["body"]
            raw_path = raw_dir / f"{target['target_id']}.html"
            raw_path.write_bytes(body)
            result = evaluate_target(target, response)
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
        "observed_at": observed_at,
        "policy": config.get("policy"),
        "scope": {
            "mode": "configured_official_read_only_capture",
            "production_state_mutated": False,
            "canonical_rate_state_mutated": False,
            "special_offer_registry_mutated": False,
        },
        "captures": captures,
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    result = capture(config, args.raw_dir)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
