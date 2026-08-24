#!/usr/bin/env python3
"""Production smoke test for the published static site and health endpoint.

This script intentionally uses only the Python standard library so it can run in a
minimal GitHub Actions job after rate-data has been published. It distinguishes
three failure classes so an operator can tell whether the problem is deployment,
API contract, or stale/mismatched content.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

DEFAULT_BASE_URL = "https://bank-rate-collector.vercel.app/"
ROOT_MARKERS = ("업권", "수집 상태")
STRATEGY_NAV_MARKER = 'href="strategy.html"'
STRATEGY_PUBLIC_FILES = frozenset(
    {
        "strategy.html",
        "data/strategy-table.json",
        "data/strategy-table.json.gz",
    }
)
HEALTH_KEYS = {
    "latest_collection",
    "active_collection",
    "active_publish",
    "latest_publish",
    "source_steps",
    "pipeline_steps",
}
MANIFEST_KEYS = ("generated_at", "rows", "data_bytes")


@dataclass(frozen=True)
class SmokeFailure(RuntimeError):
    category: str
    detail: str

    def __str__(self) -> str:
        return f"{self.category}: {self.detail}"


def _request(url: str) -> Request:
    return Request(url, headers={"User-Agent": "bank-rate-collector-production-smoke/1"})


def _get(url: str, *, timeout: float = 20.0) -> tuple[int, bytes, str]:
    try:
        with urlopen(_request(url), timeout=timeout) as response:  # noqa: S310 - fixed operator URL
            return response.status, response.read(), response.headers.get("content-type", "")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:300]
        raise SmokeFailure("deployment", f"GET {url} -> HTTP {exc.code}: {body}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise SmokeFailure("deployment", f"GET {url} failed: {exc}") from exc


def _expect_absent(url: str, *, timeout: float = 20.0) -> None:
    """Fail if a release-gated Strategy URL is still publicly retrievable."""
    try:
        with urlopen(_request(url), timeout=timeout) as response:  # noqa: S310 - fixed operator URL
            status = response.status
            body = response.read(300).decode("utf-8", errors="replace")
    except HTTPError as exc:
        if exc.code in {404, 410}:
            return
        body = exc.read().decode("utf-8", errors="replace")[:300]
        raise SmokeFailure("deployment", f"GET {url} -> HTTP {exc.code}: {body}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise SmokeFailure("deployment", f"GET {url} failed: {exc}") from exc

    raise SmokeFailure(
        "content-mismatch",
        "Strategy gate is OFF but the public endpoint is still available: "
        f"GET {url} -> HTTP {status}: {body}",
    )


def _json_body(url: str, body: bytes) -> dict[str, Any]:
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SmokeFailure("endpoint", f"GET {url} did not return valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise SmokeFailure("endpoint", f"GET {url} JSON root is not an object")
    return value


def _generated_at(manifest: dict[str, Any], label: str) -> datetime:
    value = manifest.get("generated_at")
    if not isinstance(value, str) or not value:
        raise SmokeFailure("content-mismatch", f"{label} manifest missing generated_at")
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise SmokeFailure(
            "content-mismatch", f"{label} manifest has invalid generated_at: {value!r}"
        ) from exc


def _require_strategy_absent(manifest: dict[str, Any], label: str) -> None:
    files = manifest.get("files")
    if not isinstance(files, list):
        raise SmokeFailure("content-mismatch", f"{label} manifest files is not a list")
    leaked = sorted(STRATEGY_PUBLIC_FILES.intersection(str(item) for item in files))
    if leaked:
        raise SmokeFailure(
            "content-mismatch",
            f"{label} manifest leaks Strategy while gate OFF: {', '.join(leaked)}",
        )


def validate_root(html: str) -> None:
    missing = [marker for marker in ROOT_MARKERS if marker not in html]
    if missing:
        raise SmokeFailure("content-mismatch", f"root missing UI markers: {', '.join(missing)}")
    if STRATEGY_NAV_MARKER in html:
        raise SmokeFailure(
            "content-mismatch",
            "root still exposes Strategy navigation while release gate is OFF",
        )


def validate_manifest(actual: dict[str, Any], expected: dict[str, Any]) -> None:
    _require_strategy_absent(expected, "expected")
    _require_strategy_absent(actual, "production")
    for key in MANIFEST_KEYS:
        if key not in actual:
            raise SmokeFailure("content-mismatch", f"production manifest missing {key}")
        if key not in expected:
            raise SmokeFailure("content-mismatch", f"expected manifest missing {key}")

    actual_time = _generated_at(actual, "production")
    expected_time = _generated_at(expected, "expected")
    if actual_time < expected_time:
        raise SmokeFailure(
            "content-mismatch",
            "production manifest stale for generated_at: "
            f"expected>={expected['generated_at']!r} actual={actual['generated_at']!r}",
        )

    # A second successful writer may publish while this smoke is already running.
    # Treat a newer production generation as fresh rather than a false failure,
    # but Strategy absence above remains mandatory for every generation.
    if actual_time > expected_time:
        return

    for key in ("rows", "data_bytes"):
        if actual[key] != expected[key]:
            raise SmokeFailure(
                "content-mismatch",
                f"production manifest mismatch for {key}: "
                f"expected={expected[key]!r} actual={actual[key]!r}",
            )


def validate_health(payload: dict[str, Any]) -> None:
    if payload.get("ok") is not True:
        raise SmokeFailure("endpoint", f"/api/health ok != true: {payload.get('error') or payload}")
    missing = sorted(HEALTH_KEYS - payload.keys())
    if missing:
        raise SmokeFailure("endpoint", f"/api/health missing keys: {', '.join(missing)}")
    if not isinstance(payload.get("source_steps"), dict):
        raise SmokeFailure("endpoint", "/api/health source_steps is not an object")
    if not isinstance(payload.get("pipeline_steps"), dict):
        raise SmokeFailure("endpoint", "/api/health pipeline_steps is not an object")


def run_once(base_url: str, expected_manifest: dict[str, Any], *, timeout: float) -> None:
    base = base_url.rstrip("/") + "/"
    _require_strategy_absent(expected_manifest, "expected")

    root_url = urljoin(base, "/")
    status, body, _ = _get(root_url, timeout=timeout)
    if status != 200:
        raise SmokeFailure("deployment", f"GET {root_url} -> HTTP {status}")
    validate_root(body.decode("utf-8", errors="replace"))

    strategy_url = urljoin(base, "strategy.html")
    _expect_absent(strategy_url, timeout=timeout)

    manifest_url = urljoin(base, "site-manifest.json")
    status, body, _ = _get(manifest_url, timeout=timeout)
    if status != 200:
        raise SmokeFailure("deployment", f"GET {manifest_url} -> HTTP {status}")
    validate_manifest(_json_body(manifest_url, body), expected_manifest)

    health_url = urljoin(base, "api/health")
    status, body, _ = _get(health_url, timeout=timeout)
    if status != 200:
        raise SmokeFailure("endpoint", f"GET {health_url} -> HTTP {status}")
    validate_health(_json_body(health_url, body))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--expected-manifest", required=True, type=Path)
    parser.add_argument("--attempts", type=int, default=12)
    parser.add_argument("--interval", type=float, default=15.0)
    parser.add_argument("--timeout", type=float, default=20.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.attempts < 1:
        raise SystemExit("--attempts must be >= 1")

    expected = json.loads(args.expected_manifest.read_text(encoding="utf-8"))
    if not isinstance(expected, dict):
        raise SystemExit("expected manifest must contain a JSON object")

    last: SmokeFailure | None = None
    for attempt in range(1, args.attempts + 1):
        try:
            run_once(args.base_url, expected, timeout=args.timeout)
        except SmokeFailure as exc:
            last = exc
            print(f"attempt {attempt}/{args.attempts}: {exc}", file=sys.stderr)
            if attempt < args.attempts:
                time.sleep(args.interval)
            continue

        print(
            "production smoke PASS "
            f"url={args.base_url.rstrip('/')} "
            f"expected_generated_at={expected.get('generated_at')} strategy_gate=off"
        )
        return 0

    assert last is not None
    print(f"production smoke FAIL: {last}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
