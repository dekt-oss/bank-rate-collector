#!/usr/bin/env python3
"""Queue-targeted bank-direct evidence capture for source discrepancy audits.

This module intentionally has no DB, collector, canonical writer, or SQLAlchemy imports.
It consumes an already-built read-only discrepancy report, fetches only repository-configured
HTTPS surfaces, preserves raw response hashes, and emits supporting evidence JSON.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

USER_AGENT = "Mozilla/5.0 (compatible; bank-rate-collector-audit/1.0)"
SUPPORTED_PARSERS = {"daishin_fixed_installment", "dh_deposit"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self.parts: list[str] = []

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


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _decode(content: bytes, charset: str | None) -> str:
    candidates = [charset, "utf-8", "cp949", "euc-kr"]
    for candidate in candidates:
        if not candidate:
            continue
        try:
            return content.decode(candidate)
        except (LookupError, UnicodeDecodeError):
            continue
    return content.decode("utf-8", errors="replace")


def _html_text(content: bytes, charset: str | None = None) -> str:
    parser = _TextExtractor()
    parser.feed(_decode(content, charset))
    return re.sub(r"\s+", " ", " ".join(parser.parts)).strip()


def _decimal_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip().rstrip("%")
    return text or None


def _slice(text: str, start_marker: str, end_marker: str) -> str:
    start = text.find(start_marker)
    if start < 0:
        return ""
    end = text.find(end_marker, start + len(start_marker))
    if end < 0:
        end = len(text)
    return text[start:end]


def _parse_daishin_fixed_installment(text: str) -> dict[str, Any]:
    segment = _slice(text, "정기적금(정액식) 약정이율", "중도해지이율")
    rates: dict[str, dict[str, str | None]] = {}
    for term in (12, 24, 36):
        match = re.search(
            rf"{term}\s*개월\s*([0-9]+(?:\.[0-9]+)?)",
            segment,
        )
        if match:
            rates[str(term)] = {
                "nominal_rate": _decimal_text(match.group(1)),
                "annualized_yield": None,
            }
    reference = re.search(
        r"기준일\s*[:：]\s*(\d{4})[-./](\d{2})[-./](\d{2})",
        segment,
    )
    reference_date = (
        f"{reference.group(1)}-{reference.group(2)}-{reference.group(3)}"
        if reference
        else None
    )
    return {
        "parser": "daishin_fixed_installment",
        "rates": rates,
        "page_reference_date": reference_date,
    }


def _parse_dh_deposit(text: str) -> dict[str, Any]:
    segment = _slice(text, "금리정보표이며", "우대조건")
    rates: dict[str, dict[str, str | None]] = {}
    match = re.search(
        r"12개월\s*([0-9]+(?:\.[0-9]+)?)\s*([0-9]+(?:\.[0-9]+)?|-)",
        segment,
    )
    if match:
        rates["12"] = {
            "nominal_rate": _decimal_text(match.group(1)),
            "annualized_yield": (
                None if match.group(2) == "-" else _decimal_text(match.group(2))
            ),
        }
    return {
        "parser": "dh_deposit",
        "rates": rates,
        "page_reference_date": None,
    }


def parse_surface(
    parser_name: str,
    content: bytes,
    charset: str | None = None,
) -> dict[str, Any]:
    text = _html_text(content, charset)
    if parser_name == "daishin_fixed_installment":
        return _parse_daishin_fixed_installment(text)
    if parser_name == "dh_deposit":
        return _parse_dh_deposit(text)
    raise ValueError(f"unsupported official evidence parser: {parser_name}")


def _validate_config(config: dict[str, Any]) -> None:
    if config.get("version") != 1:
        raise ValueError("official evidence target config version must be 1")
    target_ids: set[str] = set()
    for target in config.get("targets", []):
        if not isinstance(target, dict):
            raise ValueError("official evidence target must be an object")
        target_id = str(target.get("target_id") or "").strip()
        if not target_id or target_id in target_ids:
            raise ValueError(f"invalid or duplicate target_id: {target_id!r}")
        target_ids.add(target_id)
        surface = target.get("surface")
        if not isinstance(surface, dict):
            raise ValueError(f"{target_id}: surface is required")
        url = str(surface.get("url") or "")
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError(f"{target_id}: only configured HTTPS URLs are allowed")
        parser_name = str(surface.get("parser") or "")
        if parser_name not in SUPPORTED_PARSERS:
            raise ValueError(f"{target_id}: unsupported parser {parser_name!r}")


def _matches_selector(item: dict[str, Any], selector: dict[str, Any]) -> bool:
    for field in ("institution", "product", "product_type"):
        expected = selector.get(field)
        if expected is not None and str(item.get(field) or "") != str(expected):
            return False
    terms = selector.get("terms")
    return terms is None or item.get("term_months") in terms


def _triage_queue(report: dict[str, Any]) -> list[dict[str, Any]]:
    triage = report.get("triage")
    if not isinstance(triage, dict):
        return []
    queue = triage.get("queue")
    if not isinstance(queue, list):
        return []
    return [dict(item) for item in queue if isinstance(item, dict)]


def _review_ambiguities(
    report: dict[str, Any],
    selectors: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not selectors:
        return []
    output: list[dict[str, Any]] = []
    for item in report.get("dimension_ambiguities", []):
        if not isinstance(item, dict):
            continue
        if any(_matches_selector(item, selector) for selector in selectors):
            output.append(dict(item))
    return output


def build_capture_plan(report: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    _validate_config(config)
    targets = [item for item in config.get("targets", []) if isinstance(item, dict)]
    queue = _triage_queue(report)
    ambiguity_selectors = [
        item
        for item in config.get("review_ambiguity_selectors", [])
        if isinstance(item, dict)
    ]
    ambiguities = _review_ambiguities(report, ambiguity_selectors)

    refs: list[dict[str, Any]] = [
        {"origin": "triage_queue", "item": item} for item in queue
    ]
    refs.extend({"origin": "dimension_ambiguity", "item": item} for item in ambiguities)

    planned: dict[str, dict[str, Any]] = {}
    unconfigured: list[dict[str, Any]] = []
    for ref in refs:
        item = ref["item"]
        matched = [
            target
            for target in targets
            if _matches_selector(item, target.get("selector") or {})
        ]
        if not matched:
            unconfigured.append(
                {
                    "origin": ref["origin"],
                    "rank": item.get("rank"),
                    "priority": item.get("priority"),
                    "institution": item.get("institution"),
                    "product": item.get("product"),
                    "product_type": item.get("product_type"),
                    "term_months": item.get("term_months"),
                    "join_channel": item.get("join_channel"),
                    "interest_method": item.get("interest_method"),
                    "status": "unconfigured",
                }
            )
            continue
        for target in matched:
            target_id = str(target["target_id"])
            plan = planned.setdefault(
                target_id,
                {
                    "target": target,
                    "references": [],
                },
            )
            plan["references"].append(ref)

    return {
        "queue_total": len(queue),
        "review_ambiguity_total": len(ambiguities),
        "plans": list(planned.values()),
        "unconfigured": unconfigured,
    }


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
    raise RuntimeError(f"official evidence fetch failed: {url}: {last_error}")


def _rate_for_reference(
    reference: dict[str, Any],
    parsed: dict[str, Any],
) -> tuple[str | None, str | None, str]:
    item = reference["item"]
    term = str(item.get("term_months"))
    rate = parsed.get("rates", {}).get(term)
    if not isinstance(rate, dict):
        return None, None, "missing_term_rate"
    method = str(item.get("interest_method") or "unknown").lower()
    nominal = rate.get("nominal_rate")
    annualized = rate.get("annualized_yield")
    if method == "compound":
        if annualized is None:
            return None, None, "missing_compound_annualized_yield"
        return None, str(annualized), "annualized_yield_only; nominal_not_inferred"
    if nominal is None:
        return None, None, "missing_nominal_rate"
    return str(nominal), None, "nominal_contract_rate"


def _evidence_record(
    reference: dict[str, Any],
    target: dict[str, Any],
    capture: dict[str, Any],
    parsed: dict[str, Any],
    *,
    captured_at: str,
    run_id: str | None,
) -> dict[str, Any]:
    item = reference["item"]
    surface = target["surface"]
    nominal, annualized, semantics = _rate_for_reference(reference, parsed)
    target_id = str(target["target_id"])
    term = int(item.get("term_months"))
    method = str(item.get("interest_method") or "unknown").lower()
    channel = str(surface.get("join_channel") or "unknown").lower()
    return {
        "evidence_id": (
            f"auto-{target_id}-{term}m-{channel}-{method}-"
            f"{hashlib.sha1(captured_at.encode('utf-8')).hexdigest()[:10]}"
        ),
        "evidence_group": f"auto:{target_id}:{term}:{channel}:{method}",
        "evidence_kind": surface.get("evidence_kind"),
        "evidence_surface": surface.get("evidence_surface"),
        "institution": item.get("institution"),
        "product": item.get("product"),
        "product_type": item.get("product_type"),
        "term_months": term,
        "join_channel": channel,
        "interest_method": method,
        "payment_method": item.get("payment_method"),
        "base_rate": nominal,
        "max_rate": nominal,
        "annualized_yield": annualized,
        "rate_semantics": semantics,
        "effective_at": None,
        "page_reference_date": parsed.get("page_reference_date"),
        "captured_at": captured_at,
        "url": surface.get("url"),
        "capture_method": surface.get("capture_method"),
        "capture_run_id": run_id,
        "capture_artifact_id": None,
        "capture_artifact_sha256": None,
        "raw_response_sha256": capture.get("sha256"),
        "raw_response_path": capture.get("path"),
        "http_status": capture.get("status"),
        "final_url": capture.get("final_url"),
        "content_type": capture.get("content_type"),
        "queue_origin": reference.get("origin"),
        "queue_rank": item.get("rank"),
        "queue_priority": item.get("priority"),
        "queue_classification": item.get("classification"),
        "queue_join_channel": item.get("join_channel"),
        "note": (
            "Automated read-only bank-direct supporting evidence. "
            "It does not select canonical authority."
        ),
    }


def capture_evidence(
    report: dict[str, Any],
    config: dict[str, Any],
    raw_dir: Path,
    *,
    fetcher: Callable[[str], dict[str, Any]] = fetch_https,
    captured_at: str | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    plan = build_capture_plan(report, config)
    captured_at = captured_at or datetime.now(UTC).isoformat()
    raw_dir.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, Any]] = []
    captures: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for entry in plan["plans"]:
        target = entry["target"]
        surface = target["surface"]
        target_id = str(target["target_id"])
        url = str(surface["url"])
        try:
            response = fetcher(url)
            body = response["body"]
            if not isinstance(body, bytes) or not body:
                raise ValueError("empty HTTP body")
            path = raw_dir / f"{target_id}.html"
            path.write_bytes(body)
            capture = {
                "target_id": target_id,
                "url": url,
                "status": response.get("status"),
                "final_url": response.get("final_url"),
                "content_type": response.get("content_type"),
                "charset": response.get("charset"),
                "path": str(path),
                "sha256": _sha256_bytes(body),
                "content_length": len(body),
            }
            parsed = parse_surface(
                str(surface["parser"]),
                body,
                response.get("charset"),
            )
            capture["parsed"] = parsed
            captures.append(capture)
            for reference in entry["references"]:
                record = _evidence_record(
                    reference,
                    target,
                    capture,
                    parsed,
                    captured_at=captured_at,
                    run_id=run_id,
                )
                records.append(record)
                if record["rate_semantics"].startswith("missing_"):
                    failures.append(
                        {
                            "target_id": target_id,
                            "reason": record["rate_semantics"],
                            "reference": reference,
                        }
                    )
        except Exception as exc:  # noqa: BLE001 - evidence failures must be surfaced verbatim.
            failures.append(
                {
                    "target_id": target_id,
                    "url": url,
                    "reason": f"{type(exc).__name__}: {exc}",
                }
            )

    configured_refs = sum(len(entry["references"]) for entry in plan["plans"])
    return {
        "captured_at": captured_at,
        "policy": config.get("policy"),
        "scope": {
            "mode": "queue_targeted_read_only_official_evidence",
            "canonical_mutated": False,
            "source_precedence_changed": False,
            "authority_selected": False,
            "production_state_mutated": False,
            "capture_artifact_finalized": False,
        },
        "coverage": {
            "queue_total": plan["queue_total"],
            "review_ambiguity_total": plan["review_ambiguity_total"],
            "configured_references": configured_refs,
            "unconfigured_references": len(plan["unconfigured"]),
            "configured_targets": len(plan["plans"]),
            "successful_captures": len(captures),
            "failures": len(failures),
        },
        "unconfigured": plan["unconfigured"],
        "capture_failures": failures,
        "captures": captures,
        "records": records,
    }


def finalize_capture_artifact(
    payload: dict[str, Any],
    *,
    artifact_id: str,
    artifact_digest: str,
) -> dict[str, Any]:
    output = json.loads(json.dumps(payload, ensure_ascii=False))
    scope = output.setdefault("scope", {})
    scope["capture_artifact_finalized"] = True
    scope["raw_capture_artifact_id"] = artifact_id
    scope["raw_capture_artifact_sha256"] = artifact_digest
    for record in output.get("records", []):
        if isinstance(record, dict):
            record["capture_artifact_id"] = artifact_id
            record["capture_artifact_sha256"] = artifact_digest
    return output


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _capture_command(args: argparse.Namespace) -> int:
    report = _load_json(args.report)
    config = _load_json(args.config)
    payload = capture_evidence(
        report,
        config,
        args.raw_dir,
        run_id=os.environ.get("GITHUB_RUN_ID"),
    )
    _write_json(args.out, payload)
    print(json.dumps(payload["coverage"], ensure_ascii=False, sort_keys=True))
    return 1 if payload["coverage"]["failures"] else 0


def _finalize_command(args: argparse.Namespace) -> int:
    payload = _load_json(args.input)
    finalized = finalize_capture_artifact(
        payload,
        artifact_id=args.artifact_id,
        artifact_digest=args.artifact_digest,
    )
    _write_json(args.out, finalized)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    capture = subparsers.add_parser("capture")
    capture.add_argument("--report", type=Path, required=True)
    capture.add_argument("--config", type=Path, required=True)
    capture.add_argument("--raw-dir", type=Path, required=True)
    capture.add_argument("--out", type=Path, required=True)
    capture.set_defaults(func=_capture_command)

    finalize = subparsers.add_parser("finalize")
    finalize.add_argument("--input", type=Path, required=True)
    finalize.add_argument("--out", type=Path, required=True)
    finalize.add_argument("--artifact-id", required=True)
    finalize.add_argument("--artifact-digest", required=True)
    finalize.set_defaults(func=_finalize_command)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
