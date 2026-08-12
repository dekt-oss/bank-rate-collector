#!/usr/bin/env python3
"""Summarize per-runner NH network forensic JSON files."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


def _short_error(section: dict[str, Any]) -> str:
    error = section.get("error") or {}
    err_type = error.get("type")
    message = str(error.get("message") or "").strip()
    if not err_type:
        return "-"
    if len(message) > 80:
        message = message[:77] + "..."
    return f"{err_type}: {message}" if message else str(err_type)


def _http_result(section: dict[str, Any]) -> str:
    if section.get("ok"):
        return f"{section.get('status_code')} / {section.get('bytes')} B"
    return _short_error(section)


def _endpoint_result(items: list[dict[str, Any]]) -> str:
    if not items:
        return "none"
    tcp_ok = sum(1 for item in items if item.get("tcp_ok"))
    tls_ok = sum(1 for item in items if item.get("tls_ok"))
    return f"TCP {tcp_ok}/{len(items)}, TLS {tls_ok}/{len(items)}"


def _dns_result(section: dict[str, Any]) -> str:
    addresses = list(section.get("ipv4") or []) + list(section.get("ipv6") or [])
    return ", ".join(addresses) if addresses else _short_error(section)


def load_results(directory: Path) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for path in directory.rglob("result-*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["_path"] = str(path)
        results.append(payload)
    return sorted(results, key=lambda item: int(item.get("slot", 0)))


def build_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    classifications = Counter(str(item.get("classification") or "UNKNOWN") for item in results)
    egress_ips = sorted(
        {
            str(item.get("egress_ip", {}).get("ip"))
            for item in results
            if item.get("egress_ip", {}).get("ip")
        }
    )
    azure_locations = sorted(
        {
            str(item.get("azure_location", {}).get("location"))
            for item in results
            if item.get("azure_location", {}).get("location")
        }
    )
    dns_sets = sorted(
        {
            tuple(item.get("target_dns", {}).get("ipv4") or [])
            for item in results
            if item.get("target_dns", {}).get("ipv4")
        }
    )
    return {
        "runner_count": len(results),
        "classifications": dict(sorted(classifications.items())),
        "unique_egress_ips": egress_ips,
        "azure_locations": azure_locations,
        "unique_target_ipv4_sets": [list(value) for value in dns_sets],
        "results": results,
    }


def build_markdown(summary: dict[str, Any]) -> str:
    results = summary["results"]
    lines = [
        "# NH network forensic matrix",
        "",
        f"- runner results: {summary['runner_count']}",
        f"- classifications: `{json.dumps(summary['classifications'], ensure_ascii=False)}`",
        f"- unique egress IPs: {len(summary['unique_egress_ips'])}",
        f"- Azure locations from IMDS: {', '.join(summary['azure_locations']) or '-'}",
        "",
        (
            "| slot | Azure location | egress IP | NH DNS | direct endpoint | "
            "NH HTTP | control HTTP | class |"
        ),
        "|---:|---|---|---|---|---|---|---|",
    ]
    for item in results:
        azure = item.get("azure_location", {}).get("location") or "-"
        egress = item.get("egress_ip", {}).get("ip") or "-"
        dns = _dns_result(item.get("target_dns", {})).replace("|", "/")
        endpoint = _endpoint_result(item.get("target_endpoints", []))
        nh_http = _http_result(item.get("target_http", {})).replace("|", "/")
        control = _http_result(item.get("control_http", {})).replace("|", "/")
        classification = item.get("classification") or "UNKNOWN"
        lines.append(
            f"| {item.get('slot')} | {azure} | {egress} | {dns} | {endpoint} | "
            f"{nh_http} | {control} | **{classification}** |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", type=Path, required=True)
    parser.add_argument("--json", type=Path, required=True)
    parser.add_argument("--md", type=Path, required=True)
    args = parser.parse_args()

    results = load_results(args.dir)
    summary = build_summary(results)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.md.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown = build_markdown(summary)
    args.md.write_text(markdown, encoding="utf-8")
    print(markdown)
    return 0 if results else 2


if __name__ == "__main__":
    raise SystemExit(main())
