from __future__ import annotations

import json
import os
import time
from urllib.parse import unquote

import httpx

BASE = "https://apis.data.go.kr"
TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)


def _key(*names: str) -> str:
    for name in names:
        if value := os.environ.get(name):
            return unquote(value)
    raise RuntimeError(f"missing key: {names}")


def _walk(node: object):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def _probe(
    *,
    label: str,
    path: str,
    api_key: str,
    code_field: str,
    total_code: str,
) -> dict[str, object]:
    params = {
        "serviceKey": api_key,
        "pageNo": "1",
        "numOfRows": "9999",
        "resultType": "json",
        "basYm": "202506",
    }
    started = time.monotonic()
    try:
        with httpx.Client(timeout=TIMEOUT, trust_env=False) as client:
            response = client.get(f"{BASE}{path}", params=params)
        elapsed = round(time.monotonic() - started, 3)
        payload = response.json()
        dicts = list(_walk(payload))
        bas_yms = sorted({str(item.get("basYm")) for item in dicts if item.get("basYm") is not None})
        matching_code_rows = [item for item in dicts if str(item.get(code_field, "")) == total_code]
        return {
            "label": label,
            "status": "response",
            "http_code": response.status_code,
            "elapsed_seconds": elapsed,
            "content_bytes": len(response.content),
            "dict_nodes": len(dicts),
            "bas_yms": bas_yms,
            "code_field": code_field,
            "total_code": total_code,
            "matching_total_code_rows": len(matching_code_rows),
            "sample_total_keys": sorted(matching_code_rows[0].keys()) if matching_code_rows else [],
        }
    except Exception as exc:  # noqa: BLE001 - diagnostic boundary
        return {
            "label": label,
            "status": "error",
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "error_type": type(exc).__name__,
            "error": str(exc)[:240],
        }


def main() -> int:
    results = [
        _probe(
            label="savings_finance_202506_n9999",
            path="/1160100/service/GetMutuSaviBankInfoService/getMutuSaviBankFinaInfo",
            api_key=_key("DATA_GO_KR_SERVICE_KEY_SB", "DATA_GO_KR_SERVICE_KEY"),
            code_field="dpsdbtDcd",
            total_code="A11",
        ),
        _probe(
            label="agri_finance_202506_n9999",
            path="/1160100/service/GetAgriCoopInfoService/getAgriCoopFinaInfo",
            api_key=_key("DATA_GO_KR_SERVICE_KEY_NH", "DATA_GO_KR_SERVICE_KEY"),
            code_field="astDebtSmryBlnshDcd",
            total_code="A1",
        ),
    ]
    print(json.dumps(results, ensure_ascii=False, indent=2))
    with open("data-go-page-size-probe.json", "w", encoding="utf-8") as handle:
        json.dump(results, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
