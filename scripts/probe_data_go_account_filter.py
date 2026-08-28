from __future__ import annotations

import json
import os
import time
from urllib.parse import unquote

import httpx

BASE = "https://apis.data.go.kr"
TIMEOUT = httpx.Timeout(connect=8.0, read=30.0, write=8.0, pool=8.0)


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


def _probe(*, label: str, path: str, api_key: str, code_field: str, total_code: str, add_filter: bool) -> dict[str, object]:
    params = {
        "serviceKey": api_key,
        "pageNo": "1",
        "numOfRows": "500",
        "resultType": "json",
        "basYm": "202506",
    }
    if add_filter:
        params[code_field] = total_code
    started = time.monotonic()
    try:
        with httpx.Client(timeout=TIMEOUT, trust_env=False) as client:
            response = client.get(f"{BASE}{path}", params=params)
        payload = response.json()
        nodes = list(_walk(payload))
        codes = sorted({str(node.get(code_field)) for node in nodes if node.get(code_field) is not None})
        matching = [node for node in nodes if str(node.get(code_field, "")) == total_code]
        total_counts = sorted({int(str(node.get("totalCount"))) for node in nodes if str(node.get("totalCount", "")).isdigit()})
        return {
            "label": label,
            "filtered": add_filter,
            "http_code": response.status_code,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "content_bytes": len(response.content),
            "total_counts": total_counts,
            "distinct_codes": codes[:50],
            "distinct_code_count": len(codes),
            "matching_total_code_rows": len(matching),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "label": label,
            "filtered": add_filter,
            "status": "error",
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "error_type": type(exc).__name__,
            "error": str(exc)[:240],
        }


def main() -> int:
    cases = [
        ("savings", "/1160100/service/GetMutuSaviBankInfoService/getMutuSaviBankFinaInfo", _key("DATA_GO_KR_SERVICE_KEY_SB", "DATA_GO_KR_SERVICE_KEY"), "dpsdbtDcd", "A11"),
        ("agri", "/1160100/service/GetAgriCoopInfoService/getAgriCoopFinaInfo", _key("DATA_GO_KR_SERVICE_KEY_NH", "DATA_GO_KR_SERVICE_KEY"), "astDebtSmryBlnshDcd", "A1"),
    ]
    results = []
    for name, path, api_key, code_field, total_code in cases:
        results.append(_probe(label=f"{name}_unfiltered_n500", path=path, api_key=api_key, code_field=code_field, total_code=total_code, add_filter=False))
        results.append(_probe(label=f"{name}_filtered_n500", path=path, api_key=api_key, code_field=code_field, total_code=total_code, add_filter=True))
    print(json.dumps(results, ensure_ascii=False, indent=2))
    with open("data-go-account-filter-probe.json", "w", encoding="utf-8") as handle:
        json.dump(results, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
