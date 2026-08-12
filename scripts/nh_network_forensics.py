#!/usr/bin/env python3
"""One-shot NH network path forensic probe for GitHub-hosted runners.

This is diagnostic-only. It makes one normal GET to the NH outlet-list page,
plus tiny control/metadata requests, and records evidence by network layer.
It never writes production state and never iterates NH outlet detail pages.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import ssl
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

TARGET_HOST = "wmall.nonghyup.com"
TARGET_PORT = 443
TARGET_URL = f"https://{TARGET_HOST}/servlet/SFDPW0161R.view"
CONTROL_URL = "https://example.com/"
EGRESS_IP_URL = "https://api.ipify.org?format=json"
AZURE_LOCATION_URL = (
    "http://169.254.169.254/metadata/instance/compute/location"
    "?api-version=2021-02-01&format=text"
)
USER_AGENT = "rate-monitor/1 (+public rate disclosure collector; 1 req/s)"
CONNECT_TIMEOUT = 10.0
READ_TIMEOUT = 60.0
MAX_ERROR_CHARS = 800


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _elapsed_ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000.0, 2)


def _error(exc: BaseException) -> dict[str, str]:
    message = str(exc).replace("\n", " ")[:MAX_ERROR_CHARS]
    return {"type": type(exc).__name__, "message": message}


def _remote_address(response: httpx.Response) -> str | None:
    stream = response.extensions.get("network_stream")
    if stream is None:
        return None
    try:
        peer = stream.get_extra_info("server_addr")
    except Exception:
        return None
    if not peer:
        return None
    if isinstance(peer, tuple):
        return str(peer[0])
    return str(peer)


def resolve_host(host: str) -> dict[str, Any]:
    start = time.perf_counter()
    try:
        answers = socket.getaddrinfo(host, TARGET_PORT, type=socket.SOCK_STREAM)
        ipv4: list[str] = []
        ipv6: list[str] = []
        for family, _socktype, _proto, _canonname, sockaddr in answers:
            address = str(sockaddr[0])
            if family == socket.AF_INET:
                bucket = ipv4
            elif family == socket.AF_INET6:
                bucket = ipv6
            else:
                bucket = None
            if bucket is not None and address not in bucket:
                bucket.append(address)
        return {
            "ok": bool(ipv4 or ipv6),
            "elapsed_ms": _elapsed_ms(start),
            "ipv4": ipv4,
            "ipv6": ipv6,
        }
    except Exception as exc:
        return {
            "ok": False,
            "elapsed_ms": _elapsed_ms(start),
            "ipv4": [],
            "ipv6": [],
            "error": _error(exc),
        }


def probe_tcp_tls(ip: str, host: str, family: int) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ip": ip,
        "family": "ipv4" if family == socket.AF_INET else "ipv6",
    }
    started = time.perf_counter()
    raw: socket.socket | None = None
    try:
        raw = socket.socket(family, socket.SOCK_STREAM)
        raw.settimeout(CONNECT_TIMEOUT)
        endpoint: tuple[Any, ...]
        if family == socket.AF_INET6:
            endpoint = (ip, TARGET_PORT, 0, 0)
        else:
            endpoint = (ip, TARGET_PORT)
        raw.connect(endpoint)
        result["tcp_ok"] = True
        result["tcp_elapsed_ms"] = _elapsed_ms(started)
    except Exception as exc:
        result["tcp_ok"] = False
        result["tcp_elapsed_ms"] = _elapsed_ms(started)
        result["tcp_error"] = _error(exc)
        if raw is not None:
            raw.close()
        return result

    tls_started = time.perf_counter()
    try:
        context = ssl.create_default_context()
        assert raw is not None
        with context.wrap_socket(raw, server_hostname=host) as tls:
            result["tls_ok"] = True
            result["tls_elapsed_ms"] = _elapsed_ms(tls_started)
            result["tls_version"] = tls.version()
            cipher = tls.cipher()
            result["cipher"] = cipher[0] if cipher else None
            cert = tls.getpeercert()
            result["cert_subject"] = cert.get("subject", []) if cert else []
            result["cert_issuer"] = cert.get("issuer", []) if cert else []
    except Exception as exc:
        result["tls_ok"] = False
        result["tls_elapsed_ms"] = _elapsed_ms(tls_started)
        result["tls_error"] = _error(exc)
        try:
            if raw is not None:
                raw.close()
        except Exception:
            pass
    return result


def http_get(url: str, *, user_agent: str, timeout: httpx.Timeout) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        with httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": user_agent},
        ) as client:
            response = client.get(url)
            remote = _remote_address(response)
            return {
                "ok": 200 <= response.status_code < 400,
                "elapsed_ms": _elapsed_ms(started),
                "status_code": response.status_code,
                "bytes": len(response.content),
                "final_url": str(response.url),
                "remote_ip": remote,
                "history": [r.status_code for r in response.history],
                "server": response.headers.get("server"),
                "content_type": response.headers.get("content-type"),
            }
    except Exception as exc:
        return {
            "ok": False,
            "elapsed_ms": _elapsed_ms(started),
            "error": _error(exc),
        }


def get_egress_ip() -> dict[str, Any]:
    started = time.perf_counter()
    try:
        response = httpx.get(
            EGRESS_IP_URL,
            timeout=httpx.Timeout(10.0),
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        )
        response.raise_for_status()
        payload = response.json()
        return {
            "ok": True,
            "elapsed_ms": _elapsed_ms(started),
            "ip": payload.get("ip"),
        }
    except Exception as exc:
        return {
            "ok": False,
            "elapsed_ms": _elapsed_ms(started),
            "error": _error(exc),
        }


def get_azure_location() -> dict[str, Any]:
    started = time.perf_counter()
    try:
        with httpx.Client(timeout=2.0, trust_env=False) as client:
            response = client.get(AZURE_LOCATION_URL, headers={"Metadata": "true"})
        response.raise_for_status()
        return {
            "ok": True,
            "elapsed_ms": _elapsed_ms(started),
            "location": response.text.strip(),
        }
    except Exception as exc:
        return {
            "ok": False,
            "elapsed_ms": _elapsed_ms(started),
            "error": _error(exc),
        }


def classify(result: dict[str, Any]) -> str:
    control = result["control_http"]
    dns = result["target_dns"]
    target = result["target_http"]
    endpoints = result["target_endpoints"]

    if not control.get("ok"):
        return "CONTROL_HTTP_FAIL"
    if not dns.get("ok"):
        return "DNS_FAIL"
    if target.get("ok"):
        return "TARGET_HTTP_OK"
    if any(item.get("tls_ok") for item in endpoints):
        return "HTTP_LAYER_FAIL"
    if any(item.get("tcp_ok") for item in endpoints):
        return "TLS_FAIL"
    return "TCP_CONNECT_FAIL"


def run(slot: int) -> dict[str, Any]:
    timeout = httpx.Timeout(
        connect=CONNECT_TIMEOUT,
        read=READ_TIMEOUT,
        write=READ_TIMEOUT,
        pool=CONNECT_TIMEOUT,
    )
    result: dict[str, Any] = {
        "slot": slot,
        "started_at": _now_iso(),
        "runner": {
            "name": os.getenv("RUNNER_NAME"),
            "os": os.getenv("RUNNER_OS"),
            "arch": os.getenv("RUNNER_ARCH"),
            "github_run_id": os.getenv("GITHUB_RUN_ID"),
            "github_run_attempt": os.getenv("GITHUB_RUN_ATTEMPT"),
            "github_job": os.getenv("GITHUB_JOB"),
            "proxy_env_present": {
                key: bool(os.getenv(key))
                for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY")
            },
        },
        "target": {
            "host": TARGET_HOST,
            "url": TARGET_URL,
            "user_agent": USER_AGENT,
            "connect_timeout_seconds": CONNECT_TIMEOUT,
            "read_timeout_seconds": READ_TIMEOUT,
        },
    }

    result["azure_location"] = get_azure_location()
    result["egress_ip"] = get_egress_ip()
    result["control_http"] = http_get(
        CONTROL_URL,
        user_agent=USER_AGENT,
        timeout=httpx.Timeout(10.0),
    )

    dns = resolve_host(TARGET_HOST)
    result["target_dns"] = dns
    endpoint_results: list[dict[str, Any]] = []
    for ip in dns.get("ipv4", [])[:4]:
        endpoint_results.append(probe_tcp_tls(ip, TARGET_HOST, socket.AF_INET))
    for ip in dns.get("ipv6", [])[:2]:
        endpoint_results.append(probe_tcp_tls(ip, TARGET_HOST, socket.AF_INET6))
    result["target_endpoints"] = endpoint_results

    result["target_http"] = http_get(TARGET_URL, user_agent=USER_AGENT, timeout=timeout)
    result["classification"] = classify(result)
    result["finished_at"] = _now_iso()
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slot", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    result = run(args.slot)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
