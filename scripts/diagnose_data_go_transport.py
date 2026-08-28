from __future__ import annotations

import json
import os
import socket
import ssl
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import unquote

import httpx

HOST = "apis.data.go.kr"
BASE = f"https://{HOST}"
TIMEOUT = 12


def _env_key(*names: str) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value:
            return unquote(value)
    return None


def _sanitize(text: str, secrets: list[str]) -> str:
    sanitized = text
    for secret in secrets:
        if secret:
            sanitized = sanitized.replace(secret, "***")
    return sanitized[:240]


def dns_probe() -> dict[str, object]:
    started = time.monotonic()
    try:
        infos = socket.getaddrinfo(HOST, 443, type=socket.SOCK_STREAM)
        addresses = sorted({info[4][0] for info in infos})
        return {
            "status": "ok",
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "addresses": addresses,
        }
    except Exception as exc:  # noqa: BLE001 - diagnostic boundary
        return {
            "status": "error",
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "error_type": type(exc).__name__,
            "error": str(exc),
        }


def tcp_tls_probe(address: str) -> dict[str, object]:
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    result: dict[str, object] = {"address": address}

    tcp_started = time.monotonic()
    sock = socket.socket(family, socket.SOCK_STREAM)
    sock.settimeout(6)
    try:
        target = (address, 443, 0, 0) if family == socket.AF_INET6 else (address, 443)
        sock.connect(target)
        result["tcp"] = "ok"
        result["tcp_seconds"] = round(time.monotonic() - tcp_started, 3)
    except Exception as exc:  # noqa: BLE001
        result["tcp"] = "error"
        result["tcp_seconds"] = round(time.monotonic() - tcp_started, 3)
        result["tcp_error_type"] = type(exc).__name__
        sock.close()
        return result

    tls_started = time.monotonic()
    try:
        context = ssl.create_default_context()
        with context.wrap_socket(sock, server_hostname=HOST) as tls_sock:
            tls_sock.settimeout(8)
            result["tls"] = "ok"
            result["tls_seconds"] = round(time.monotonic() - tls_started, 3)
            result["tls_version"] = tls_sock.version()
    except Exception as exc:  # noqa: BLE001
        result["tls"] = "error"
        result["tls_seconds"] = round(time.monotonic() - tls_started, 3)
        result["tls_error_type"] = type(exc).__name__
        try:
            sock.close()
        except OSError:
            pass
    return result


def curl_probe(
    *,
    label: str,
    path: str,
    params: dict[str, str],
    secrets: list[str],
    resolve_ip: str | None = None,
) -> dict[str, object]:
    with tempfile.NamedTemporaryFile(delete=False) as body_file:
        body_path = Path(body_file.name)

    args = [
        "curl",
        "-4",
        "--silent",
        "--show-error",
        "--connect-timeout",
        "6",
        "--max-time",
        str(TIMEOUT),
        "--output",
        str(body_path),
        "--write-out",
        "%{http_code}|%{time_connect}|%{time_starttransfer}|%{remote_ip}",
    ]
    if resolve_ip:
        args += ["--resolve", f"{HOST}:443:{resolve_ip}"]
    args += ["--get", f"{BASE}{path}"]
    for key, value in params.items():
        args += ["--data-urlencode", f"{key}={value}"]

    started = time.monotonic()
    proc = subprocess.run(args, capture_output=True, text=True, timeout=TIMEOUT + 3, check=False)
    elapsed = round(time.monotonic() - started, 3)
    try:
        body = body_path.read_text(encoding="utf-8", errors="replace")
    finally:
        body_path.unlink(missing_ok=True)

    stdout = proc.stdout.strip()
    parts = stdout.split("|") if stdout else []
    return {
        "label": label,
        "client": "curl_ipv4",
        "resolve_ip": resolve_ip,
        "exit_code": proc.returncode,
        "elapsed_seconds": elapsed,
        "http_code": parts[0] if len(parts) > 0 else None,
        "connect_seconds": parts[1] if len(parts) > 1 else None,
        "starttransfer_seconds": parts[2] if len(parts) > 2 else None,
        "remote_ip": parts[3] if len(parts) > 3 else None,
        "stderr": _sanitize(proc.stderr.strip(), secrets),
        "body_length": len(body),
        "body_prefix": _sanitize(body.replace("\n", " "), secrets),
    }


def httpx_probe(
    *,
    label: str,
    path: str,
    params: dict[str, str],
    secrets: list[str],
    trust_env: bool,
) -> dict[str, object]:
    timeout = httpx.Timeout(connect=6.0, read=TIMEOUT, write=6.0, pool=6.0)
    started = time.monotonic()
    try:
        with httpx.Client(timeout=timeout, trust_env=trust_env) as client:
            response = client.get(f"{BASE}{path}", params=params)
        body = response.text
        return {
            "label": label,
            "client": "httpx",
            "trust_env": trust_env,
            "status": "response",
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "http_code": response.status_code,
            "body_length": len(body),
            "body_prefix": _sanitize(body.replace("\n", " "), secrets),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "label": label,
            "client": "httpx",
            "trust_env": trust_env,
            "status": "error",
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "error_type": type(exc).__name__,
            "error": _sanitize(str(exc), secrets),
        }


def main() -> int:
    sb_key = _env_key("DATA_GO_KR_SERVICE_KEY_SB", "DATA_GO_KR_SERVICE_KEY")
    nh_key = _env_key("DATA_GO_KR_SERVICE_KEY_NH", "DATA_GO_KR_SERVICE_KEY")
    sh_key = _env_key("DATA_GO_KR_SERVICE_KEY_SH", "DATA_GO_KR_SERVICE_KEY")
    secrets = [value for value in (sb_key, nh_key, sh_key) if value]

    savings_finance = "/1160100/service/GetMutuSaviBankInfoService/getMutuSaviBankFinaInfo"
    savings_general = "/1160100/service/GetMutuSaviBankInfoService/getMutuSaviBankInfo"
    agri_finance = "/1160100/service/GetAgriCoopInfoService/getAgriCoopFinaInfo"
    cu_general = "/1160100/service/GetCUInfoService/getCUInfo"

    output: dict[str, object] = {
        "proxy_env_names_present": [
            name
            for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY")
            if os.environ.get(name)
        ],
        "keys_present": {"savings": bool(sb_key), "agri": bool(nh_key), "cu": bool(sh_key)},
    }

    dns = dns_probe()
    output["dns"] = dns
    addresses = dns.get("addresses", []) if isinstance(dns, dict) else []
    output["tcp_tls"] = [tcp_tls_probe(address) for address in addresses[:6]]

    cases: list[tuple[str, str, dict[str, str]]] = [
        ("savings_finance_no_key", savings_finance, {"pageNo": "1", "numOfRows": "1", "resultType": "json"}),
    ]
    if sb_key:
        cases.extend(
            [
                ("savings_finance_key_no_basym", savings_finance, {"serviceKey": sb_key, "pageNo": "1", "numOfRows": "1", "resultType": "json"}),
                ("savings_finance_key_202506", savings_finance, {"serviceKey": sb_key, "pageNo": "1", "numOfRows": "1", "resultType": "json", "basYm": "202506"}),
                ("savings_general_key_202506", savings_general, {"serviceKey": sb_key, "pageNo": "1", "numOfRows": "1", "resultType": "json", "basYm": "202506"}),
            ]
        )
    if nh_key:
        cases.extend(
            [
                ("agri_finance_key_no_basym", agri_finance, {"serviceKey": nh_key, "pageNo": "1", "numOfRows": "1", "resultType": "json"}),
                ("agri_finance_key_202506", agri_finance, {"serviceKey": nh_key, "pageNo": "1", "numOfRows": "1", "resultType": "json", "basYm": "202506"}),
            ]
        )
    if sh_key:
        cases.append(
            ("cu_general_key_202506", cu_general, {"serviceKey": sh_key, "pageNo": "1", "numOfRows": "1", "resultType": "json", "basYm": "202506"})
        )

    curl_results: list[dict[str, object]] = []
    # Two hostname attempts reveal intermittency without launching a backfill.
    for label, path, params in cases:
        for attempt in (1, 2):
            curl_results.append(
                curl_probe(
                    label=f"{label}_attempt{attempt}",
                    path=path,
                    params=params,
                    secrets=secrets,
                )
            )
            time.sleep(1)
    # Pin up to three resolved IPv4 backends, without a key, to separate DNS/LB from backend reachability.
    ipv4 = [address for address in addresses if ":" not in address]
    for address in ipv4[:3]:
        curl_results.append(
            curl_probe(
                label="savings_finance_no_key_pinned",
                path=savings_finance,
                params={"pageNo": "1", "numOfRows": "1", "resultType": "json"},
                secrets=secrets,
                resolve_ip=address,
            )
        )
    output["curl"] = curl_results

    httpx_results: list[dict[str, object]] = []
    for trust_env in (False, True):
        httpx_results.append(
            httpx_probe(
                label="savings_finance_no_key",
                path=savings_finance,
                params={"pageNo": "1", "numOfRows": "1", "resultType": "json"},
                secrets=secrets,
                trust_env=trust_env,
            )
        )
        if sb_key:
            httpx_results.append(
                httpx_probe(
                    label="savings_finance_key_202506",
                    path=savings_finance,
                    params={"serviceKey": sb_key, "pageNo": "1", "numOfRows": "1", "resultType": "json", "basYm": "202506"},
                    secrets=secrets,
                    trust_env=trust_env,
                )
            )
    output["httpx"] = httpx_results

    Path("data-go-diagnosis.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
