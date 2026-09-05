"""Bounded Data.go transport for the canonical total-assets tables.

Funding and total-assets live in different statement tables and have very
different pagination sizes. This module deliberately does not reuse the funding
transport's 20-page cap. It pins the authenticated asset table title and exact
`A / 자산총계` code, follows that table's own `totalCount`, and fails closed on
schema drift, repeated pages, or an unexpectedly large request.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from typing import Any

import httpx

from rate_monitor.collectors.data_go_funding.collector import (
    RETRY_DELAYS,
    FundingContractError,
    FundingSourceUnavailable,
    FundingTransportError,
    SourceContract,
    _accepted,
    _unknown_operation,
)
from rate_monitor.domain.schemas import RawArtifactData

PAGE_SIZE = 500
MAX_PAGES = 120

ASSET_ACCOUNT_FILTERS: dict[str, tuple[str, str]] = {
    "data_go_savings_bank_funding": ("astSmryStfnpsAcitCd", "A"),
    "data_go_agri_coop_funding": ("astSmryBlnshDcd", "A"),
}

TARGET_TABLE_TITLES: dict[str, str] = {
    "data_go_savings_bank_funding": "저축_재무현황_요약재무상태표(자산)",
    "data_go_agri_coop_funding": "농협_재무현황_요약재무상태표(자산)",
}


def request_params(
    contract: SourceContract,
    *,
    key: str,
    bas_ym: str,
    page_no: int,
    num_rows: int = PAGE_SIZE,
) -> dict[str, str]:
    try:
        field, value = ASSET_ACCOUNT_FILTERS[contract.source_id]
    except KeyError as exc:
        raise FundingContractError(
            f"total-assets source contract 미지원: {contract.source_id}"
        ) from exc
    return {
        "serviceKey": key,
        "numOfRows": str(num_rows),
        "pageNo": str(page_no),
        "resultType": "json",
        "basYm": bas_ym,
        field: value,
    }


def _request_json(
    client: httpx.Client,
    *,
    contract: SourceContract,
    endpoint: str,
    key: str,
    bas_ym: str,
    page_no: int,
) -> tuple[dict[str, Any], bytes, dict[str, str]]:
    params = request_params(
        contract,
        key=key,
        bas_ym=bas_ym,
        page_no=page_no,
    )
    last_error: Exception | None = None
    for delay in (0.0, *RETRY_DELAYS):
        if delay:
            time.sleep(delay)
        try:
            response = client.get(endpoint, params=params)
            raw = response.content
            text = raw.decode("utf-8", "replace")
            try:
                payload: Any = json.loads(text)
            except json.JSONDecodeError as exc:
                raise FundingTransportError(
                    f"JSON이 아닌 응답: status={response.status_code} endpoint={endpoint}"
                ) from exc
            if _unknown_operation(payload, text, response.status_code):
                raise FundingSourceUnavailable(f"unknown operation: {endpoint}")
            if response.status_code >= 500:
                raise FundingTransportError(
                    f"Data.go 서버 오류 {response.status_code}: {endpoint}"
                )
            if not _accepted(payload, text):
                raise FundingContractError(
                    f"Data.go 정상응답 계약 불일치 status={response.status_code}: {endpoint}"
                )
            if not isinstance(payload, dict):
                raise FundingContractError("Data.go JSON root가 object가 아니다")
            return payload, raw, params
        except (FundingSourceUnavailable, FundingContractError):
            raise
        except (httpx.HTTPError, FundingTransportError) as exc:
            last_error = exc
    raise FundingTransportError(f"Data.go transport retry 소진: {last_error}")


def _artifact(
    *,
    contract: SourceContract,
    endpoint: str,
    bas_ym: str,
    page_no: int,
    raw: bytes,
    params: dict[str, str],
) -> RawArtifactData:
    digest = hashlib.sha256(raw).hexdigest()
    filter_field, _ = ASSET_ACCOUNT_FILTERS[contract.source_id]
    return RawArtifactData(
        artifact_type="json",
        content=raw,
        filename=(
            f"{contract.source_id}-total-assets-{bas_ym}-p{page_no:03d}-{digest[:12]}.json"
        ),
        request_meta={
            "dataset_id": contract.dataset_id,
            "endpoint": endpoint,
            "metric": "total_assets",
            "basYm": bas_ym,
            "pageNo": page_no,
            "numOfRows": int(params["numOfRows"]),
            filter_field: params[filter_field],
        },
        schema_fingerprint=digest,
        source_role="secondary_official",
        trust_level="official_direct",
    )


def _integer(value: Any, *, field: str, context: str) -> int:
    text = str(value if value is not None else "").strip()
    if not text.isdigit():
        raise FundingContractError(f"{context}: {field}가 정수가 아니다: {value!r}")
    return int(text)


def _table_list(payload: dict[str, Any], *, context: str) -> list[dict[str, Any]]:
    response = payload.get("response")
    if not isinstance(response, dict):
        raise FundingContractError(f"{context}: response object가 없다")
    body = response.get("body")
    if not isinstance(body, dict):
        raise FundingContractError(f"{context}: response.body object가 없다")
    tables = body.get("tableList")
    if not isinstance(tables, list) or any(not isinstance(table, dict) for table in tables):
        raise FundingContractError(f"{context}: response.body.tableList 계약 불일치")
    return tables


def _table_rows(table: dict[str, Any], *, context: str) -> list[dict[str, Any]]:
    items = table.get("items")
    if items is None:
        return []
    if not isinstance(items, dict):
        raise FundingContractError(f"{context}: table.items가 object가 아니다")
    item = items.get("item")
    if item in (None, []):
        return []
    if isinstance(item, dict):
        rows = [item]
    elif isinstance(item, list):
        rows = item
    else:
        raise FundingContractError(f"{context}: table.items.item 계약 불일치")
    if any(not isinstance(row, dict) for row in rows):
        raise FundingContractError(f"{context}: object가 아닌 row가 있다")
    return rows


def _select_asset_table(
    payload: dict[str, Any],
    *,
    contract: SourceContract,
    bas_ym: str,
) -> tuple[int, list[dict[str, Any]]]:
    try:
        title = TARGET_TABLE_TITLES[contract.source_id]
        code_field, total_code = ASSET_ACCOUNT_FILTERS[contract.source_id]
    except KeyError as exc:
        raise FundingContractError(
            f"total-assets source contract 미지원: {contract.source_id}"
        ) from exc

    context = f"{contract.source_id}/{bas_ym}"
    matches = [table for table in _table_list(payload, context=context) if table.get("title") == title]
    if len(matches) != 1:
        raise FundingContractError(f"{context}: asset target table {title!r}가 {len(matches)}개다")
    table = matches[0]
    rows = _table_rows(table, context=f"{context}/{title}")
    total_count = _integer(table.get("totalCount"), field="totalCount", context=context)
    if total_count < len(rows):
        raise FundingContractError(
            f"{context}/{title}: totalCount={total_count} < rows={len(rows)}"
        )
    if any(str(row.get(code_field) or "").strip() != total_code for row in rows):
        raise FundingContractError(
            f"{context}/{title}: total-assets account filter 밖의 row가 섞였다"
        )
    return total_count, rows


def _rows_hash(rows: list[dict[str, Any]]) -> str:
    encoded = json.dumps(
        rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def fetch_month(
    client: httpx.Client,
    *,
    contract: SourceContract,
    endpoint: str,
    key: str,
    bas_ym: str,
) -> tuple[list[dict[str, Any]], list[RawArtifactData]]:
    """Fetch the complete exact asset table for one reporting month."""
    rows: list[dict[str, Any]] = []
    artifacts: list[RawArtifactData] = []
    target_total: int | None = None
    expected_pages: int | None = None
    seen_hashes: set[str] = set()

    for page_no in range(1, MAX_PAGES + 1):
        payload, raw, params = _request_json(
            client,
            contract=contract,
            endpoint=endpoint,
            key=key,
            bas_ym=bas_ym,
            page_no=page_no,
        )
        page_total, page_rows = _select_asset_table(
            payload,
            contract=contract,
            bas_ym=bas_ym,
        )
        artifacts.append(
            _artifact(
                contract=contract,
                endpoint=endpoint,
                bas_ym=bas_ym,
                page_no=page_no,
                raw=raw,
                params=params,
            )
        )

        if target_total is None:
            target_total = page_total
            expected_pages = math.ceil(target_total / PAGE_SIZE) if target_total else 1
            if expected_pages > MAX_PAGES:
                raise FundingContractError(
                    f"{contract.source_id}/{bas_ym}: totalCount={target_total} requires "
                    f"{expected_pages} pages > MAX_PAGES={MAX_PAGES}"
                )
        elif page_total != target_total:
            raise FundingContractError(
                f"{contract.source_id}/{bas_ym}: totalCount changed {target_total}->{page_total}"
            )

        assert expected_pages is not None
        assert target_total is not None
        expected_rows = min(PAGE_SIZE, max(target_total - (page_no - 1) * PAGE_SIZE, 0))
        if len(page_rows) != expected_rows:
            raise FundingContractError(
                f"{contract.source_id}/{bas_ym}: page {page_no} rows={len(page_rows)} "
                f"expected={expected_rows} totalCount={target_total}"
            )
        digest = _rows_hash(page_rows)
        if page_rows and digest in seen_hashes:
            raise FundingContractError(
                f"{contract.source_id}/{bas_ym}: pagination이 같은 asset page를 반복했다"
            )
        if page_rows:
            seen_hashes.add(digest)
        rows.extend(page_rows)

        if page_no >= expected_pages:
            if len(rows) != target_total:
                raise FundingContractError(
                    f"{contract.source_id}/{bas_ym}: collected={len(rows)} != totalCount={target_total}"
                )
            return rows, artifacts

    raise FundingContractError(
        f"{contract.source_id}/{bas_ym}: asset pagination이 {MAX_PAGES} page를 초과했다"
    )
