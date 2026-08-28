from __future__ import annotations

import json
import time
from typing import Any

import httpx

from rate_monitor.collectors.data_go_funding.collector import (
    CONTRACTS,
    _service_key,
    candidate_months,
)

PROBE_TIMEOUT_SECONDS = 15.0


def _metadata(value: Any, key: str) -> list[Any]:
    found: list[Any] = []
    if isinstance(value, dict):
        for name, child in value.items():
            if name == key and not isinstance(child, (dict, list)):
                found.append(child)
            else:
                found.extend(_metadata(child, key))
    elif isinstance(value, list):
        for child in value:
            found.extend(_metadata(child, key))
    return found


def _probe(contract: Any) -> dict[str, Any]:
    if not contract.finance_endpoint:
        return {
            "source_id": contract.source_id,
            "sector": contract.sector,
            "status": "skipped_unverified_endpoint",
        }

    bas_ym = candidate_months(contract, 1)[0]
    key = _service_key(contract)
    params = {
        "serviceKey": key,
        "numOfRows": "1",
        "pageNo": "1",
        "resultType": "json",
        "basYm": bas_ym,
    }
    started = time.monotonic()
    try:
        with httpx.Client(
            timeout=PROBE_TIMEOUT_SECONDS,
            follow_redirects=True,
            headers={"User-Agent": "bank-rate-collector/1 funding-probe"},
        ) as client:
            response = client.get(contract.finance_endpoint, params=params)
        elapsed = round(time.monotonic() - started, 3)
        payload: Any = None
        try:
            payload = response.json()
        except ValueError:
            payload = None
        result_codes = [str(value) for value in _metadata(payload, "resultCode")]
        result_messages = [str(value) for value in _metadata(payload, "resultMsg")]
        total_counts = [str(value) for value in _metadata(payload, "totalCount")]
        return {
            "source_id": contract.source_id,
            "sector": contract.sector,
            "basYm": bas_ym,
            "status": "response",
            "http_status": response.status_code,
            "elapsed_seconds": elapsed,
            "content_length": len(response.content),
            "result_codes": result_codes[:3],
            "result_messages": result_messages[:3],
            "total_counts": total_counts[:3],
        }
    except httpx.TimeoutException as exc:
        return {
            "source_id": contract.source_id,
            "sector": contract.sector,
            "basYm": bas_ym,
            "status": "timeout",
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "error_type": type(exc).__name__,
        }
    except httpx.HTTPError as exc:
        return {
            "source_id": contract.source_id,
            "sector": contract.sector,
            "basYm": bas_ym,
            "status": "http_error",
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "error_type": type(exc).__name__,
        }


def main() -> int:
    results = [
        _probe(contract)
        for contract in CONTRACTS
        if contract.sector in {"savings_bank", "nh_local"}
    ]
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
