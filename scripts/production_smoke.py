#!/usr/bin/env python3
"""Production smoke test for the published static site and health endpoint.

This script intentionally uses only the Python standard library so it can run in a
minimal GitHub Actions job after rate-data has been published. It distinguishes
three failure classes so an operator can tell whether the problem is deployment,
API contract, or stale/mismatched content.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

DEFAULT_BASE_URL = "https://bank-rate-collector.vercel.app/"
ROOT_MARKERS = ("업권", "수집 상태")
STRATEGY_MARKERS = (
    "수신상품 전략 대시보드",
    'id="strategy-workspace-script"',
    'id="strategy-brand-theme-script"',
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
SESSION_COOKIE = "__Host-rate_monitor_auth_v2"
SESSION_TOKEN_NAMESPACE = "bank-rate-collector:site-session:v1\0"


@dataclass(frozen=True)
class SmokeFailure(RuntimeError):
    category: str
    detail: str

    def __str__(self) -> str:
        return f"{self.category}: {self.detail}"


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001, ANN201
        return None


def _session_cookie(password: str) -> str:
    if not password:
        return ""
    digest = hashlib.sha256(f"{SESSION_TOKEN_NAMESPACE}{password}".encode()).digest()
    token = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return f"{SESSION_COOKIE}={token}"


def _get(
    url: str,
    *,
    timeout: float = 20.0,
    cookie: str = "",
) -> tuple[int, bytes, str]:
    headers = {"User-Agent": "bank-rate-collector-production-smoke/1"}
    if cookie:
        headers["Cookie"] = cookie
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed operator URL
            return response.status, response.read(), response.headers.get("content-type", "")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:300]
        raise SmokeFailure("deployment", f"GET {url} -> HTTP {exc.code}: {body}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise SmokeFailure("deployment", f"GET {url} failed: {exc}") from exc


def _get_no_redirect(
    url: str,
    *,
    timeout: float,
    accept: str,
) -> tuple[int, bytes, str, str]:
    request = Request(
        url,
        headers={
            "User-Agent": "bank-rate-collector-production-smoke/1",
            "Accept": accept,
        },
    )
    opener = build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=timeout) as response:  # noqa: S310
            return (
                response.status,
                response.read(),
                response.headers.get("content-type", ""),
                response.headers.get("location", ""),
            )
    except HTTPError as exc:
        return (
            exc.code,
            exc.read(),
            exc.headers.get("content-type", ""),
            exc.headers.get("location", ""),
        )
    except (URLError, TimeoutError, OSError) as exc:
        raise SmokeFailure("deployment", f"GET {url} failed: {exc}") from exc


def _same_origin_login_target(base_url: str, location: str) -> bool:
    if not location:
        return False
    base = urlparse(base_url.rstrip("/") + "/")
    target = urlparse(urljoin(base_url.rstrip("/") + "/", location))
    return (
        target.scheme == base.scheme
        and target.netloc == base.netloc
        and target.path == "/__login"
    )


def validate_anonymous_boundary(base_url: str, *, timeout: float) -> None:
    base = base_url.rstrip("/") + "/"
    root_url = urljoin(base, "/")
    status, _, _, location = _get_no_redirect(
        root_url,
        timeout=timeout,
        accept="text/html",
    )
    if status != 302:
        raise SmokeFailure(
            "auth-boundary",
            f"anonymous root expected HTTP 302, got {status}",
        )
    if not _same_origin_login_target(base_url, location):
        raise SmokeFailure(
            "auth-boundary",
            f"anonymous root redirect target invalid: {location!r}",
        )

    health_url = urljoin(base, "api/health")
    status, _, _, _ = _get_no_redirect(
        health_url,
        timeout=timeout,
        accept="application/json",
    )
    if status != 401:
        raise SmokeFailure(
            "auth-boundary",
            f"anonymous /api/health expected HTTP 401, got {status}",
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


def _require_strategy_file(manifest: dict[str, Any], label: str) -> None:
    files = manifest.get("files")
    if not isinstance(files, list) or "strategy.html" not in files:
        raise SmokeFailure(
            "content-mismatch", f"{label} manifest must include strategy.html"
        )


def validate_root(html: str) -> None:
    missing = [marker for marker in ROOT_MARKERS if marker not in html]
    if missing:
        raise SmokeFailure("content-mismatch", f"root missing UI markers: {', '.join(missing)}")


def validate_strategy(html: str) -> None:
    missing = [marker for marker in STRATEGY_MARKERS if marker not in html]
    if missing:
        raise SmokeFailure(
            "content-mismatch", f"strategy missing UI markers: {', '.join(missing)}"
        )


def validate_manifest(actual: dict[str, Any], expected: dict[str, Any]) -> None:
    _require_strategy_file(expected, "expected")
    _require_strategy_file(actual, "production")
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


def run_once(
    base_url: str,
    expected_manifest: dict[str, Any],
    *,
    timeout: float,
    password: str = "",
) -> None:
    base = base_url.rstrip("/") + "/"
    _require_strategy_file(expected_manifest, "expected")

    # 최신 manifest를 만족하는 동일 retry에서 익명 경계도 같이 확인한다.
    validate_anonymous_boundary(base_url, timeout=timeout)

    cookie = _session_cookie(password)
    root_url = urljoin(base, "/")
    status, body, _ = _get(root_url, timeout=timeout, cookie=cookie)
    if status != 200:
        raise SmokeFailure("deployment", f"GET {root_url} -> HTTP {status}")
    validate_root(body.decode("utf-8", errors="replace"))

    strategy_url = urljoin(base, "strategy.html")
    status, body, _ = _get(strategy_url, timeout=timeout, cookie=cookie)
    if status != 200:
        raise SmokeFailure("deployment", f"GET {strategy_url} -> HTTP {status}")
    validate_strategy(body.decode("utf-8", errors="replace"))

    manifest_url = urljoin(base, "site-manifest.json")
    status, body, _ = _get(manifest_url, timeout=timeout, cookie=cookie)
    if status != 200:
        raise SmokeFailure("deployment", f"GET {manifest_url} -> HTTP {status}")
    validate_manifest(_json_body(manifest_url, body), expected_manifest)

    health_url = urljoin(base, "api/health")
    status, body, _ = _get(health_url, timeout=timeout, cookie=cookie)
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

    password = os.environ.get("DASHBOARD_PASSWORD", "")
    last: SmokeFailure | None = None
    for attempt in range(1, args.attempts + 1):
        try:
            run_once(args.base_url, expected, timeout=args.timeout, password=password)
        except SmokeFailure as exc:
            last = exc
            print(f"attempt {attempt}/{args.attempts}: {exc}", file=sys.stderr)
            if attempt < args.attempts:
                time.sleep(args.interval)
            continue

        print(
            "production smoke PASS "
            f"url={args.base_url.rstrip('/')} expected_generated_at={expected.get('generated_at')}"
        )
        return 0

    assert last is not None
    print(f"production smoke FAIL: {last}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
