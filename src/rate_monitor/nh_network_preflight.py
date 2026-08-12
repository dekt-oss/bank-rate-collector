"""Lightweight NH network admission/forensic probe for GitHub-hosted runners.

The probe deliberately stops at TLS. It does not send an NH HTTP request, so a
healthy runner enters the real collector without downloading the 3 MiB outlet
list twice. Azure/egress/control probes are evidence only and never decide
admission; the NH DNS/TCP/TLS path is the gate.
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
CONNECT_TIMEOUT = 10.0
METADATA_TIMEOUT = 5.0
MAX_ERROR_CHARS = 800
CONTROL_URL = "https://example.com/"
EGRESS_IP_URL = "https://api.ipify.org?format=json"
AZURE_LOCATION_URL = (
    "http://169.254.169.254/metadata/instance/compute/location"
    "?api-version=2021-02-01&format=text"
)
USER_AGENT = "rate-monitor/1 (+public rate disclosure collector; 1 req/s)"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000.0, 2)


def _error(exc: BaseException) -> dict[str, str]:
    return {
        "type": type(exc).__name__,
        "message": str(exc).replace("\n", " ")[:MAX_ERROR_CHARS],
    }


def resolve_host(host: str = TARGET_HOST) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        answers = socket.getaddrinfo(host, TARGET_PORT, type=socket.SOCK_STREAM)
        ipv4: list[str] = []
        ipv6: list[str] = []
        for family, _socktype, _proto, _canonname, sockaddr in answers:
            address = str(sockaddr[0])
            bucket = ipv4 if family == socket.AF_INET else ipv6 if family == socket.AF_INET6 else None
            if bucket is not None and address not in bucket:
                bucket.append(address)
        return {
            "ok": bool(ipv4 or ipv6),
            "elapsed_ms": _elapsed_ms(started),
            "ipv4": ipv4,
            "ipv6": ipv6,
        }
    except Exception as exc:
        return {
            "ok": False,
            "elapsed_ms": _elapsed_ms(started),
            "ipv4": [],
            "ipv6": [],
            "error": _error(exc),
        }


def probe_tcp_tls(ip: str, family: int, host: str = TARGET_HOST) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ip": ip,
        "family": "ipv4" if family == socket.AF_INET else "ipv6",
    }
    raw: socket.socket | None = None
    tcp_started = time.perf_counter()
    try:
        raw = socket.socket(family, socket.SOCK_STREAM)
        raw.settimeout(CONNECT_TIMEOUT)
        endpoint: tuple[Any, ...] = (
            (ip, TARGET_PORT, 0, 0) if family == socket.AF_INET6 else (ip, TARGET_PORT)
        )
        raw.connect(endpoint)
        result["tcp_ok"] = True
        result["tcp_elapsed_ms"] = _elapsed_ms(tcp_started)
    except Exception as exc:
        result["tcp_ok"] = False
        result["tcp_elapsed_ms"] = _elapsed_ms(tcp_started)
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


def _simple_get(url: str, *, trust_env: bool = True, headers: dict[str, str] | None = None) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        with httpx.Client(
            timeout=METADATA_TIMEOUT,
            follow_redirects=True,
            trust_env=trust_env,
            headers={"User-Agent": USER_AGENT, **(headers or {})},
        ) as client:
            response = client.get(url)
        response.raise_for_status()
        return {
            "ok": True,
            "elapsed_ms": _elapsed_ms(started),
            "status_code": response.status_code,
            "text": response.text.strip()[:200],
        }
    except Exception as exc:
        return {
            "ok": False,
            "elapsed_ms": _elapsed_ms(started),
            "error": _error(exc),
        }


def get_azure_location() -> dict[str, Any]:
    result = _simple_get(
        AZURE_LOCATION_URL,
        trust_env=False,
        headers={"Metadata": "true"},
    )
    if result.get("ok"):
        result["location"] = result.pop("text", "")
    return result


def get_egress_ip() -> dict[str, Any]:
    result = _simple_get(EGRESS_IP_URL)
    if result.get("ok"):
        try:
            result["ip"] = json.loads(result.pop("text", "{}"))["ip"]
        except (KeyError, TypeError, ValueError) as exc:
            return {"ok": False, "error": _error(exc)}
    return result


def get_control_http() -> dict[str, Any]:
    result = _simple_get(CONTROL_URL)
    result.pop("text", None)
    return result


def classify_target(dns: dict[str, Any], endpoints: list[dict[str, Any]]) -> tuple[bool, str]:
    """Return whether this runner should enter the real NH collector."""
    if not dns.get("ok"):
        return False, "DNS_FAIL"
    if any(item.get("tls_ok") for item in endpoints):
        return True, "READY"
    if any(item.get("tcp_ok") for item in endpoints):
        return False, "TLS_FAIL"
    return False, "TCP_CONNECT_FAIL"


def run(attempt: int) -> dict[str, Any]:
    result: dict[str, Any] = {
        "attempt": attempt,
        "started_at": _now_iso(),
        "runner": {
            "name": os.getenv("RUNNER_NAME"),
            "os": os.getenv("RUNNER_OS"),
            "arch": os.getenv("RUNNER_ARCH"),
            "github_run_id": os.getenv("GITHUB_RUN_ID"),
            "github_run_attempt": os.getenv("GITHUB_RUN_ATTEMPT"),
            "github_job": os.getenv("GITHUB_JOB"),
        },
        "target": {
            "host": TARGET_HOST,
            "port": TARGET_PORT,
            "connect_timeout_seconds": CONNECT_TIMEOUT,
        },
    }

    # These three probes enrich the forensic record but never gate NH admission.
    result["azure_location"] = get_azure_location()
    result["egress_ip"] = get_egress_ip()
    result["control_http"] = get_control_http()

    dns = resolve_host()
    result["target_dns"] = dns
    endpoints: list[dict[str, Any]] = []
    for ip in dns.get("ipv4", []):
        endpoints.append(probe_tcp_tls(ip, socket.AF_INET))
    for ip in dns.get("ipv6", []):
        endpoints.append(probe_tcp_tls(ip, socket.AF_INET6))
    result["target_endpoints"] = endpoints

    admit, classification = classify_target(dns, endpoints)
    result["admit"] = admit
    result["classification"] = classification
    result["finished_at"] = _now_iso()
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m rate_monitor.nh_network_preflight")
    parser.add_argument("--attempt", type=int, required=True)
    parser.add_argument("--json", type=Path, required=True)
    args = parser.parse_args(argv)

    result = run(args.attempt)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    # Network unavailability is data, not a process error. The workflow reads admit.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
