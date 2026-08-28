from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

import httpx

from rate_monitor.collectors.data_go_funding.collector import (
    CONTRACTS,
    DATA_GO_BASE,
    _service_key,
)

PROBE_TIMEOUT_SECONDS = 15.0


@dataclass(frozen=True)
class Probe:
    source_id: str
    sector: str
    endpoint: str
    bas_ym: str
    num_rows: int
    key_contract_sector: str
    label: str


def _contract(sector: str) -> Any:
    return next(contract for contract in CONTRACTS if contract.sector == sector)


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


def _run(probe: Probe) -> dict[str, Any]:
    key = _service_key(_contract(probe.key_contract_sector))
    params = {
        "serviceKey": key,
        "numOfRows": str(probe.num_rows),
        "pageNo": "1",
        "resultType": "json",
        "basYm": probe.bas_ym,
    }
    started = time.monotonic()
    try:
        with httpx.Client(
            timeout=PROBE_TIMEOUT_SECONDS,
            follow_redirects=True,
            headers={"User-Agent": "bank-rate-collector/1 funding-probe"},
        ) as client:
            response = client.get(probe.endpoint, params=params)
        elapsed = round(time.monotonic() - started, 3)
        payload: Any = None
        try:
            payload = response.json()
        except ValueError:
            payload = None
        result_codes = [str(value) for value in _metadata(payload, "resultCode")]
        result_messages = [str(value) for value in _metadata(payload, "resultMsg")]
        total_counts = [str(value) for value in _metadata(payload, "totalCount")]
        bas_yms = [str(value) for value in _metadata(payload, "basYm")]
        return {
            "label": probe.label,
            "source_id": probe.source_id,
            "sector": probe.sector,
            "basYm": probe.bas_ym,
            "num_rows": probe.num_rows,
            "status": "response",
            "http_status": response.status_code,
            "elapsed_seconds": elapsed,
            "content_length": len(response.content),
            "result_codes": result_codes[:3],
            "result_messages": result_messages[:3],
            "total_counts": total_counts[:3],
            "returned_basYm": bas_yms[:3],
        }
    except httpx.TimeoutException as exc:
        return {
            "label": probe.label,
            "source_id": probe.source_id,
            "sector": probe.sector,
            "basYm": probe.bas_ym,
            "num_rows": probe.num_rows,
            "status": "timeout",
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "error_type": type(exc).__name__,
        }
    except httpx.HTTPError as exc:
        return {
            "label": probe.label,
            "source_id": probe.source_id,
            "sector": probe.sector,
            "basYm": probe.bas_ym,
            "num_rows": probe.num_rows,
            "status": "http_error",
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "error_type": type(exc).__name__,
        }


def main() -> int:
    savings = _contract("savings_bank")
    agri = _contract("nh_local")
    probes = [
        Probe(
            savings.source_id,
            "savings_bank",
            str(savings.finance_endpoint),
            "202512",
            1,
            "savings_bank",
            "savings_finance_202512_n1",
        ),
        Probe(
            savings.source_id,
            "savings_bank",
            str(savings.finance_endpoint),
            "202506",
            1,
            "savings_bank",
            "savings_finance_202506_n1",
        ),
        Probe(
            "data_go_savings_bank_general_probe",
            "savings_bank",
            f"{DATA_GO_BASE}/GetMutuSaviBankInfoService/getMutuSaviBankGeneInfo",
            "202506",
            1,
            "savings_bank",
            "savings_general_202506_n1",
        ),
        Probe(
            agri.source_id,
            "nh_local",
            str(agri.finance_endpoint),
            "202512",
            1,
            "nh_local",
            "agri_finance_202512_n1",
        ),
        Probe(
            agri.source_id,
            "nh_local",
            str(agri.finance_endpoint),
            "202506",
            1,
            "nh_local",
            "agri_finance_202506_n1",
        ),
        Probe(
            agri.source_id,
            "nh_local",
            str(agri.finance_endpoint),
            "202506",
            100,
            "nh_local",
            "agri_finance_202506_n100",
        ),
        Probe(
            "data_go_credit_union_general_probe",
            "cu",
            f"{DATA_GO_BASE}/GetCredUnioInfoService/getCredUnioGeneInfo",
            "202506",
            1,
            "cu",
            "cu_general_202506_n1",
        ),
    ]
    results = [_run(probe) for probe in probes]
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
