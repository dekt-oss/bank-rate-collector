#!/usr/bin/env python3
"""Authenticated, read-only D1 probe for actual institution funding rows.

This script never opens the application DB. It exists only to prove exact
Data.go.kr operations and identify deposit-like source rows before a persistence
contract is created. Credentials are never written to the report.
"""

from __future__ import annotations

import contextlib
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

OUT = Path("docs/source-recon/market-funding-d1-actual-probe.json")
TIMEOUT = 25
PAGE_SIZE = 100
DEPOSIT_RE = re.compile(r"예수|수신|예금|저축성|요구불|기한부")

KEY_ENVS = {
    "savings_bank": "DATA_GO_KR_SERVICE_KEY_SB",
    "credit_union": "DATA_GO_KR_SERVICE_KEY_SH",
    "agri_coop": "DATA_GO_KR_SERVICE_KEY_NH",
}


@dataclass(frozen=True)
class Probe:
    sector: str
    label: str
    url: str
    contract_status: str


CU_CURRENT_SERVICE = "https://apis.data.go.kr/1160100/service/GetCredUnioInfoService"
# The official catalogue proves that a credit-union finance operation exists,
# while its crawler-visible page exposes only getCredUnioGeneInfo. Keep this a
# small, reviewable set of naming variants observed in the FSC statistics API
# family; this is operation discovery, not an unbounded brute-force scan.
CU_OPERATION_CANDIDATES = (
    "getCredUnioFinaInfo",
    "getCredUnioFinInfo",
    "getCredUnioFinaStatInfo",
    "getCredUnioFinStatInfo",
    "getCredUnioFinaStatusInfo",
    "getCredUnioFinStatusInfo",
    "getCrdtUnioFinaInfo",
    "getCrdtUnioFinInfo",
    "getCrdtUnioFinaStatInfo",
    "getCrdtUnioFinStatInfo",
    "getCredUnionFinaInfo",
    "getCredUnionFinInfo",
    "getCrdtUnionFinaInfo",
    "getCrdtUnionFinInfo",
)

PROBES = (
    Probe(
        "savings_bank",
        "general",
        "https://apis.data.go.kr/1160100/service/GetMutuSaviBankInfoService/getMutuSaviBankGeneInfo",
        "catalogue_verified",
    ),
    Probe(
        "savings_bank",
        "finance",
        "https://apis.data.go.kr/1160100/service/GetMutuSaviBankInfoService/getMutuSaviBankFinaInfo",
        "live_verified_33069947384",
    ),
    Probe(
        "credit_union",
        "general",
        f"{CU_CURRENT_SERVICE}/getCredUnioGeneInfo",
        "catalogue_verified",
    ),
    *(
        Probe(
            "credit_union",
            f"finance_candidate_{operation}",
            f"{CU_CURRENT_SERVICE}/{operation}",
            "discovery_only",
        )
        for operation in CU_OPERATION_CANDIDATES
    ),
    Probe(
        "credit_union",
        "finance_candidate_historical_service_crdt_union",
        "https://apis.data.go.kr/1160100/service/CrdtUnionInfoService/getCrdtUnionFinaInfo",
        "discovery_only",
    ),
    Probe(
        "credit_union",
        "finance_candidate_historical_get_service_crdt_union",
        "https://apis.data.go.kr/1160100/service/GetCrdtUnionInfoService/getCrdtUnionFinaInfo",
        "discovery_only",
    ),
    Probe(
        "credit_union",
        "finance_candidate_historical_get_service_crdt_unio",
        "https://apis.data.go.kr/1160100/service/GetCrdtUnioInfoService/getCrdtUnioFinaInfo",
        "discovery_only",
    ),
    Probe(
        "credit_union",
        "finance_candidate_historical_get_service_cred_union",
        "https://apis.data.go.kr/1160100/service/GetCredUnionInfoService/getCredUnionFinaInfo",
        "discovery_only",
    ),
    Probe(
        "agri_coop",
        "general",
        "https://apis.data.go.kr/1160100/service/GetAgriCoopInfoService/getAgriCoopGeneInfo",
        "catalogue_verified",
    ),
    Probe(
        "agri_coop",
        "finance",
        "https://apis.data.go.kr/1160100/service/GetAgriCoopInfoService/getAgriCoopFinaInfo",
        "live_verified_33069947384",
    ),
)


def _key(sector: str) -> str:
    return urllib.parse.unquote(os.environ.get(KEY_ENVS[sector], "").strip())


def _item_rows(value: object) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    return []


def _flatten(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "item":
                found.extend(_item_rows(child))
            else:
                found.extend(_flatten(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_flatten(child))
    return found


def _response_context(value: Any, path: str = "$") -> list[dict[str, Any]]:
    """Capture wrapper metadata that `_flatten` deliberately discards.

    Data.go.kr often places `title`, pagination and result metadata next to the
    `item` container rather than inside each row. Those values are part of the
    source contract, so the probe retains a small sanitized structural summary
    without persisting credentials or the request URL query string.
    """
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if "item" in value:
            rows = _item_rows(value["item"])
            found.append(
                {
                    "path": path,
                    "container_keys": sorted(value),
                    "row_count": len(rows),
                    "row_keys": sorted({key for row in rows for key in row}),
                    "metadata": {
                        key: value[key]
                        for key in (
                            "resultCode",
                            "resultMsg",
                            "pageNo",
                            "numOfRows",
                            "totalCount",
                            "title",
                        )
                        if key in value
                    },
                }
            )
        for key, child in value.items():
            if key != "item":
                found.extend(_response_context(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_response_context(child, f"{path}[{index}]"))
    return found


def _metadata_values(value: Any, path: str = "$") -> list[dict[str, Any]]:
    """Retain non-secret source metadata even when it is not beside `item`."""
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in {
                "resultCode",
                "resultMsg",
                "pageNo",
                "numOfRows",
                "totalCount",
                "title",
            } and not isinstance(child, (dict, list)):
                found.append({"path": child_path, "value": child})
            else:
                found.extend(_metadata_values(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_metadata_values(child, f"{path}[{index}]"))
    return found


def _signature(payload: Any, text: str, status: int | None) -> str:
    blob = (json.dumps(payload, ensure_ascii=False) if payload is not None else "") + text
    upper = blob.upper()
    if "NORMAL SERVICE" in upper or '"RESULTCODE": "00"' in upper:
        return "accepted"
    if "NO_OPENAPI_SERVICE" in upper or status == 404:
        return "unknown_operation"
    if "SERVICE_ACCESS_DENIED" in upper or "PERMISSION_DENIED" in upper:
        return "permission_denied"
    if "SERVICE_KEY_IS_NOT_REGISTERED" in upper:
        return "unregistered_key"
    if "SERVICE_KEY_IS_NULL" in upper:
        return "service_key_required"
    return "other"


def _request(probe: Probe, key: str) -> dict[str, Any]:
    params = urllib.parse.urlencode(
        {
            "serviceKey": key,
            "numOfRows": str(PAGE_SIZE),
            "pageNo": "1",
            "resultType": "json",
        }
    )
    url = f"{probe.url}?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "rate-monitor/1 D1 actual-row probe"})
    status: int | None = None
    payload: Any = None
    text = ""
    error_text: str | None = None
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
            status = response.status
            text = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        status = error.code
        text = error.read().decode("utf-8", "replace")
    except Exception as error:  # noqa: BLE001 - evidence must retain transport class
        error_text = f"{type(error).__name__}: {error}"
    if text:
        with contextlib.suppress(json.JSONDecodeError):
            payload = json.loads(text)
    rows = _flatten(payload)
    hits = []
    for row in rows:
        matched_fields = {
            field: value
            for field, value in row.items()
            if value is not None and DEPOSIT_RE.search(str(value))
        }
        if matched_fields:
            hits.append({"matched_fields": matched_fields, "row": row})
    return {
        "sector": probe.sector,
        "label": probe.label,
        "endpoint": probe.url,
        "contract_status": probe.contract_status,
        "http_status": status,
        "signature": _signature(payload, text, status) if error_text is None else "transport_error",
        "row_count_flattened": len(rows),
        "row_keys": sorted({field for row in rows for field in row}),
        "response_context": _response_context(payload),
        "response_metadata": _metadata_values(payload),
        "deposit_hit_count": len(hits),
        "deposit_hits": hits[:30],
        "sample_rows": rows[:5],
        "error": error_text,
        "text_head": None if payload is not None else text[:1000],
    }


def main() -> int:
    missing = [sector for sector in KEY_ENVS if not _key(sector)]
    if missing:
        print("missing credentials: " + ", ".join(missing), file=sys.stderr)
        return 2

    results = []
    for probe in PROBES:
        result = _request(probe, _key(probe.sector))
        results.append(result)
        print(
            f"{probe.sector}/{probe.label}: {result['signature']} "
            f"rows={result['row_count_flattened']} deposit_hits={result['deposit_hit_count']}"
        )
        time.sleep(0.25)

    report = {
        "mode": "authenticated_read_only_no_db_write",
        "purpose": "exact operation and deposit-row evidence before persistence",
        "results": results,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    required = {
        ("savings_bank", "general"),
        ("savings_bank", "finance"),
        ("credit_union", "general"),
        ("agri_coop", "general"),
        ("agri_coop", "finance"),
    }
    failed = [
        f"{row['sector']}/{row['label']}"
        for row in results
        if (row["sector"], row["label"]) in required
        and (row["signature"] != "accepted" or row["row_count_flattened"] == 0)
    ]
    if failed:
        print("verified controls failed: " + ", ".join(failed), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
