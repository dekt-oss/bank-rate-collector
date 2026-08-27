#!/usr/bin/env python3
"""D1 read-only reconnaissance for institution-level deposit balances.

This probe targets the Financial Services Commission statistics Open APIs on
Data.go.kr for savings banks, credit unions, and agricultural cooperatives.
It does not open the application DB and never persists a guessed metric.

The public catalogue verifies each service base and the general-information
operation, but the rendered catalogue does not expose all operation paths at
once. D1 therefore treats non-general operation names as discovery candidates:
a candidate is usable only when the live gateway accepts it and returns data.

Source-specific Data.go.kr credentials are supported because access approval is
service-scoped in the portal. A legacy generic key is accepted only as a
fallback. The portal can display either an encoded or decoded service key, so
keys are normalized to their decoded form once before query-string encoding.
Credentials are redacted from all URLs, payload diagnostics, and errors before
a report is written.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

GENERIC_KEY_ENV = "DATA_GO_KR_SERVICE_KEY"
KEY_ENVS = {
    "savings_bank": "DATA_GO_KR_SERVICE_KEY_SB",
    "credit_union": "DATA_GO_KR_SERVICE_KEY_SH",
    "agri_coop": "DATA_GO_KR_SERVICE_KEY_NH",
}
OUT = Path("docs/source-recon/market-funding-d1-institution-recon.json")
TIMEOUT = 25
INTERVAL = 0.3
PAGE_SIZE = 100
DEPOSIT_PATTERNS = (
    r"예수",
    r"수신",
    r"예금",
    r"요구불",
    r"기한부",
)


@dataclass(frozen=True)
class Service:
    key: str
    base: str
    prefix: str
    general_operation: str


SERVICES = (
    Service(
        key="savings_bank",
        base=(
            "https://apis.data.go.kr/1160100/service/"
            "GetMutuSaviBankInfoService"
        ),
        prefix="getMutuSaviBank",
        general_operation="getMutuSaviBankGeneInfo",
    ),
    Service(
        key="credit_union",
        base="https://apis.data.go.kr/1160100/service/GetCredUnioInfoService",
        prefix="getCredUnio",
        general_operation="getCredUnioGeneInfo",
    ),
    Service(
        key="agri_coop",
        base="https://apis.data.go.kr/1160100/service/GetAgriCoopInfoService",
        prefix="getAgriCoop",
        general_operation="getAgriCoopGeneInfo",
    ),
)

# The general operation is official catalogue evidence. The remaining suffixes
# are *discovery only*: no candidate becomes a contract until a live response
# proves that the gateway accepts it and provides rows.
DISCOVERY_SUFFIXES = (
    "GeneInfo",
    "FinaInfo",
    "FinInfo",
    "FinaStatInfo",
    "FinStatInfo",
    "FinaStat",
    "FinaStatusInfo",
    "MainIndiInfo",
    "MajorIndiInfo",
    "MngmIndiInfo",
    "MngmtIndiInfo",
    "MainMngmIndiInfo",
    "MainMngmtIndiInfo",
    "ManaInfo",
)


def _normalize_credential(raw: str) -> str:
    """Accept either portal 'Encoding' or 'Decoding' service-key representation."""
    value = raw.strip()
    if not value:
        return ""
    # Data.go.kr's encoded key commonly contains %2B/%2F/%3D. Decoding once and
    # letting urlencode encode the query parameter prevents accidental %25xx
    # double-encoding while leaving an already-decoded key unchanged.
    return urllib.parse.unquote(value)


def _credential(service_key: str) -> tuple[str, str | None]:
    source_env = KEY_ENVS[service_key]
    source_key = _normalize_credential(os.environ.get(source_env, ""))
    if source_key:
        return source_key, source_env
    generic_key = _normalize_credential(os.environ.get(GENERIC_KEY_ENV, ""))
    if generic_key:
        return generic_key, GENERIC_KEY_ENV
    return "", None


def _mask(text: str, keys: tuple[str, ...]) -> str:
    masked = text
    for key in keys:
        if not key:
            continue
        variants = {
            key,
            urllib.parse.quote_plus(key),
            urllib.parse.quote(key, safe=""),
        }
        for variant in variants:
            masked = masked.replace(variant, "[REDACTED]")
    return masked


def _request(url: str, all_keys: tuple[str, ...]) -> dict[str, Any]:
    record: dict[str, Any] = {"url": _mask(url, all_keys)}
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "rate-monitor/1 (+public financial-data recon)"},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            body = response.read()
            record["http_status"] = response.status
            record["bytes"] = len(body)
            text = body.decode("utf-8", "replace")
            try:
                record["payload"] = json.loads(text)
            except json.JSONDecodeError:
                record["text"] = _mask(text[:4000], all_keys)
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", "replace")
        record["http_status"] = error.code
        record["text"] = _mask(body[:4000], all_keys)
    except Exception as error:  # noqa: BLE001 - diagnostic must preserve failure class
        record["error"] = f"{type(error).__name__}: {_mask(str(error), all_keys)}"
    time.sleep(INTERVAL)
    return record


def _flatten_items(value: Any) -> list[dict[str, Any]]:
    """Find public-data item dictionaries without assuming one wrapper shape."""
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "item" and isinstance(child, dict):
                found.append(child)
            elif key == "item" and isinstance(child, list):
                found.extend(row for row in child if isinstance(row, dict))
            else:
                found.extend(_flatten_items(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_flatten_items(child))
    return found


def _gateway_signature(record: dict[str, Any]) -> str:
    blob = json.dumps(record.get("payload"), ensure_ascii=False)
    blob += " " + str(record.get("text") or "")
    upper = blob.upper()
    if "SERVICE_KEY_IS_NULL" in upper or "SERVICE KEY IS NULL" in upper:
        return "service_key_required"
    if "SERVICE_ACCESS_DENIED" in upper or "PERMISSION_DENIED" in upper:
        return "permission_denied"
    if "SERVICE_KEY_IS_NOT_REGISTERED" in upper:
        return "unregistered_key"
    if "NO_OPENAPI_SERVICE" in upper:
        return "unknown_operation"
    if "NORMAL SERVICE" in upper or '"RESULTCODE": "00"' in upper:
        return "accepted"
    if _flatten_items(record.get("payload")):
        return "accepted"
    if record.get("http_status") == 404:
        return "unknown_operation"
    if record.get("error"):
        return "transport_error"
    return "other"


def _operation_url(service: Service, operation: str, key: str) -> str:
    params = {
        "numOfRows": str(PAGE_SIZE),
        "pageNo": "1",
        "resultType": "json",
    }
    if key:
        params["serviceKey"] = key
    return f"{service.base}/{operation}?{urllib.parse.urlencode(params)}"


def _operation_candidates(service: Service) -> list[str]:
    operations = [service.general_operation]
    for suffix in DISCOVERY_SUFFIXES:
        operation = service.prefix + suffix
        if operation not in operations:
            operations.append(operation)
    return operations


def _row_text(row: dict[str, Any]) -> str:
    useful = []
    for field, value in row.items():
        if value is None:
            continue
        if field.lower() in {
            "title",
            "acntnm",
            "acntitmnm",
            "acctnm",
            "itemnm",
            "itmnm",
            "fnconm",
        }:
            useful.append(str(value))
    if useful:
        return " ".join(useful)
    return " ".join(str(value) for value in row.values() if value is not None)


def _deposit_hits(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for row in rows:
        text = _row_text(row)
        matched = [pattern for pattern in DEPOSIT_PATTERNS if re.search(pattern, text)]
        if matched:
            hits.append({"row": row, "matched_patterns": matched})
    return hits[:50]


def _safe_sample(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # All rows are public source data. Cap volume because the report is evidence,
    # not a mirror of the upstream API.
    return rows[:8]


def discover_service(
    service: Service,
    key: str,
    credential_env: str | None,
    all_keys: tuple[str, ...],
) -> dict[str, Any]:
    operations: list[dict[str, Any]] = []
    for operation in _operation_candidates(service):
        record = _request(_operation_url(service, operation, key), all_keys)
        rows = _flatten_items(record.get("payload"))
        operations.append(
            {
                "operation": operation,
                "catalogue_verified_general": operation == service.general_operation,
                "signature": _gateway_signature(record),
                "http_status": record.get("http_status"),
                "bytes": record.get("bytes"),
                "row_count_first_page": len(rows),
                "row_keys": sorted({field for row in rows for field in row}),
                "deposit_hits": _deposit_hits(rows),
                "sample_rows": _safe_sample(rows),
                "error": record.get("error"),
                "text_head": record.get("text"),
            }
        )
    accepted = [row for row in operations if row["signature"] == "accepted"]
    deposit_operations = [row for row in accepted if row["deposit_hits"]]
    return {
        "service": service.key,
        "base": service.base,
        "credential_env": credential_env,
        "credential_present": bool(key),
        "operations": operations,
        "accepted_operations": [row["operation"] for row in accepted],
        "deposit_operations": [row["operation"] for row in deposit_operations],
        "deposit_hit_count": sum(len(row["deposit_hits"]) for row in deposit_operations),
    }


def main() -> int:
    credentials = {service.key: _credential(service.key) for service in SERVICES}
    raw_keys = {
        _normalize_credential(os.environ.get(env_name, ""))
        for env_name in (*KEY_ENVS.values(), GENERIC_KEY_ENV)
    }
    all_keys = tuple(key for key in raw_keys if key)
    report = {
        "mode": "read_only_no_db_write",
        "source": "Financial Services Commission statistics via Data.go.kr",
        "credential_envs": {
            service_key: env_name for service_key, env_name in KEY_ENVS.items()
        },
        "generic_fallback_env": GENERIC_KEY_ENV,
        "credential_present_by_service": {
            service_key: bool(key)
            for service_key, (key, _env_name) in credentials.items()
        },
        "services": {},
    }
    for service in SERVICES:
        key, credential_env = credentials[service.key]
        report["services"][service.key] = discover_service(
            service,
            key,
            credential_env,
            all_keys,
        )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(report, ensure_ascii=False, indent=2)
    if any(
        key in blob
        or urllib.parse.quote_plus(key) in blob
        or urllib.parse.quote(key, safe="") in blob
        for key in all_keys
    ):
        blob = _mask(blob, all_keys)
        print("warning: credential residue removed before persistence")
    OUT.write_text(blob, encoding="utf-8")

    print(
        "credential_present="
        + ",".join(
            f"{service.key}:{bool(credentials[service.key][0])}"
            for service in SERVICES
        )
    )
    for service in SERVICES:
        result = report["services"][service.key]
        print(
            f"{service.key}: accepted={len(result['accepted_operations'])} "
            f"deposit_ops={len(result['deposit_operations'])} "
            f"deposit_hits={result['deposit_hit_count']}"
        )
    print(f"report={OUT} bytes={len(blob):,}")

    # A missing credential remains evidence, not a CI failure. Once a source key
    # is configured, however, that source's verified general endpoint must work.
    failed_controls = []
    for service in SERVICES:
        key, _credential_env = credentials[service.key]
        if not key:
            continue
        result = report["services"][service.key]
        if service.general_operation not in result["accepted_operations"]:
            failed_controls.append(service.key)
    if failed_controls:
        print(
            "configured credential could not read verified general endpoints: "
            + ", ".join(failed_controls),
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
