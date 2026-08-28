"""Bounded Data.go transport for institution-funding collection.

The funding finance APIs return a ``response.body.tableList`` containing many
financial-statement tables. ``numOfRows``/``pageNo`` paginate each table, while
each table carries its own ``totalCount``. The collector only needs the
source-specific canonical deposit-liabilities table. Pagination must therefore
follow that table's own count; recursively counting every ``item`` in the
response mixes unrelated tables and can create a false endless pagination.
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
MAX_PAGES = 20

# Verified against the live Data.go finance operations on 2026-08-28.
ACCOUNT_FILTERS: dict[str, tuple[str, str]] = {
    "data_go_savings_bank_funding": ("dpsdbtDcd", "A11"),
    "data_go_agri_coop_funding": ("astDebtSmryBlnshDcd", "A1"),
}

# A total account code can also appear in a summary balance-sheet table. The
# dedicated funding table is the canonical source when Data.go returns both.
# These titles were verified from authenticated finance payloads on 2026-08-28.
TARGET_TABLE_TITLES: dict[str, str] = {
    "data_go_savings_bank_funding": "저축_재무현황_부채부문별현황_예수부채",
    "data_go_agri_coop_funding": "농협_재무현황_요약재무상태표(부채및자본)",
}


def request_params(
    contract: SourceContract,
    *,
    key: str,
    bas_ym: str,
    page_no: int,
    num_rows: int = PAGE_SIZE,
) -> dict[str, str]:
    """Build the smallest verified request contract for one reporting month."""
    params = {
        "serviceKey": key,
        "numOfRows": str(num_rows),
        "pageNo": str(page_no),
        "resultType": "json",
        "basYm": bas_ym,
    }
    account_filter = ACCOUNT_FILTERS.get(contract.source_id)
    if account_filter is not None:
        field, value = account_filter
        params[field] = value
    return params


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
            payload: Any = None
            try:
                payload = json.loads(text)
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
        except FundingSourceUnavailable:
            raise
        except FundingContractError:
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
    request_meta = {
        "dataset_id": contract.dataset_id,
        "endpoint": endpoint,
        "basYm": bas_ym,
        "pageNo": page_no,
        "numOfRows": int(params["numOfRows"]),
    }
    account_filter = ACCOUNT_FILTERS.get(contract.source_id)
    if account_filter is not None:
        field, _value = account_filter
        request_meta[field] = params[field]
    return RawArtifactData(
        artifact_type="json",
        content=raw,
        filename=(
            f"{contract.source_id}-{bas_ym}-p{page_no:03d}-{digest[:12]}.json"
        ),
        request_meta=request_meta,
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
    table_list = body.get("tableList")
    if not isinstance(table_list, list):
        raise FundingContractError(f"{context}: response.body.tableList가 list가 아니다")
    if any(not isinstance(table, dict) for table in table_list):
        raise FundingContractError(f"{context}: tableList에 object가 아닌 항목이 있다")
    return table_list


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
        raise FundingContractError(f"{context}: table.items.item이 row/list가 아니다")
    if any(not isinstance(row, dict) for row in rows):
        raise FundingContractError(f"{context}: table.items.item에 object가 아닌 row가 있다")
    return rows


def _row_matches_target(contract: SourceContract, row: dict[str, Any]) -> bool:
    return any(
        str(row.get(schema.code_field, "")).strip() == schema.total_code
        for schema in contract.account_schemas
    )


def _row_uses_account_schema(contract: SourceContract, row: dict[str, Any]) -> bool:
    return any(schema.code_field in row for schema in contract.account_schemas)


def _select_target_table(
    payload: dict[str, Any],
    *,
    contract: SourceContract,
    bas_ym: str,
    target_title: str | None,
) -> tuple[str | None, int, list[dict[str, Any]]]:
    """Return the canonical paginated table for the verified total account.

    Data.go can return the same total account code in both a summary statement
    and a dedicated deposit-liabilities table. The source-specific canonical
    table title wins when present. After page 1 the title is pinned, so a schema
    drift or table disappearance fails closed instead of switching populations.
    """
    context = f"{contract.source_id}/{bas_ym}"
    tables = _table_list(payload, context=context)

    parsed: list[tuple[str, int, list[dict[str, Any]]]] = []
    for index, table in enumerate(tables):
        title = table.get("title")
        if not isinstance(title, str) or not title.strip():
            raise FundingContractError(f"{context}: tableList[{index}].title이 비어 있다")
        rows = _table_rows(table, context=f"{context}/{title}")
        total_count = _integer(
            table.get("totalCount"), field="totalCount", context=f"{context}/{title}"
        )
        if total_count < len(rows):
            raise FundingContractError(
                f"{context}/{title}: totalCount={total_count} < rows={len(rows)}"
            )
        parsed.append((title, total_count, rows))

    if target_title is not None:
        matches = [entry for entry in parsed if entry[0] == target_title]
        if len(matches) != 1:
            raise FundingContractError(
                f"{context}: target table {target_title!r}가 {len(matches)}개다"
            )
        title, total_count, rows = matches[0]
        if any(not _row_matches_target(contract, row) for row in rows):
            raise FundingContractError(
                f"{context}/{title}: account filter 밖의 row가 섞였다"
            )
        return title, total_count, rows

    target_tables = [
        entry for entry in parsed if any(_row_matches_target(contract, row) for row in entry[2])
    ]
    preferred_title = TARGET_TABLE_TITLES.get(contract.source_id)
    if preferred_title is not None:
        preferred = [entry for entry in target_tables if entry[0] == preferred_title]
        if len(preferred) > 1:
            raise FundingContractError(
                f"{context}: canonical target table {preferred_title!r}가 {len(preferred)}개다"
            )
        if len(preferred) == 1:
            title, total_count, rows = preferred[0]
            if any(not _row_matches_target(contract, row) for row in rows):
                raise FundingContractError(
                    f"{context}/{title}: account filter 밖의 row가 섞였다"
                )
            return title, total_count, rows

    if len(target_tables) > 1:
        raise FundingContractError(
            f"{context}: canonical table을 특정할 수 없는 total account 중복: "
            f"{[entry[0] for entry in target_tables]}"
        )
    if len(target_tables) == 1:
        title, total_count, rows = target_tables[0]
        if any(not _row_matches_target(contract, row) for row in rows):
            raise FundingContractError(
                f"{context}/{title}: account filter 밖의 row가 섞였다"
            )
        return title, total_count, rows

    schema_rows = [
        row for _title, _count, table_rows in parsed for row in table_rows
        if _row_uses_account_schema(contract, row)
    ]
    if schema_rows:
        codes = sorted(
            {
                str(row.get(schema.code_field))
                for row in schema_rows
                for schema in contract.account_schemas
                if schema.code_field in row
            }
        )
        raise FundingContractError(
            f"{context}: account filter가 total code를 반환하지 않았다. codes={codes[:20]}"
        )

    # A reporting month may legitimately precede/source-lag the target account.
    # Do not use unrelated tables' totalCount to invent target pagination.
    return None, 0, []


def _rows_hash(rows: list[dict[str, Any]]) -> str:
    encoded = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def fetch_month(
    client: httpx.Client,
    *,
    contract: SourceContract,
    endpoint: str,
    key: str,
    bas_ym: str,
) -> tuple[list[dict[str, Any]], list[RawArtifactData]]:
    """Fetch one reporting month using the target statement table's totalCount."""
    rows: list[dict[str, Any]] = []
    artifacts: list[RawArtifactData] = []
    seen_target_hashes: set[str] = set()
    target_title: str | None = None
    target_total: int | None = None
    expected_pages: int | None = None

    for page_no in range(1, MAX_PAGES + 1):
        payload, raw, params = _request_json(
            client,
            contract=contract,
            endpoint=endpoint,
            key=key,
            bas_ym=bas_ym,
            page_no=page_no,
        )
        page_title, page_total, page_rows = _select_target_table(
            payload,
            contract=contract,
            bas_ym=bas_ym,
            target_title=target_title,
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

        if page_no == 1 and page_title is None:
            return [], artifacts
        if page_title is None:
            raise FundingContractError(
                f"{contract.source_id}/{bas_ym}: target table이 pagination 중 사라졌다"
            )

        if target_title is None:
            target_title = page_title
            target_total = page_total
            expected_pages = math.ceil(target_total / PAGE_SIZE) if target_total else 1
            if expected_pages > MAX_PAGES:
                raise FundingContractError(
                    f"{contract.source_id}/{bas_ym}/{target_title}: "
                    f"totalCount={target_total} requires {expected_pages} pages "
                    f"> MAX_PAGES={MAX_PAGES}"
                )
        elif page_total != target_total:
            raise FundingContractError(
                f"{contract.source_id}/{bas_ym}/{target_title}: totalCount changed "
                f"{target_total}->{page_total}"
            )

        assert target_total is not None
        assert expected_pages is not None
        expected_rows = min(PAGE_SIZE, max(target_total - (page_no - 1) * PAGE_SIZE, 0))
        if len(page_rows) != expected_rows:
            raise FundingContractError(
                f"{contract.source_id}/{bas_ym}/{target_title}: page {page_no} "
                f"rows={len(page_rows)} expected={expected_rows} totalCount={target_total}"
            )

        digest = _rows_hash(page_rows)
        if page_rows and digest in seen_target_hashes:
            raise FundingContractError(
                f"{contract.source_id}/{bas_ym}: pagination이 같은 target page를 반복했다"
            )
        if page_rows:
            seen_target_hashes.add(digest)
        rows.extend(page_rows)

        if page_no >= expected_pages:
            if len(rows) != target_total:
                raise FundingContractError(
                    f"{contract.source_id}/{bas_ym}/{target_title}: collected={len(rows)} "
                    f"!= totalCount={target_total}"
                )
            return rows, artifacts

    raise FundingContractError(
        f"{contract.source_id}/{bas_ym}: pagination이 {MAX_PAGES} page를 초과했다"
    )
