"""Bounded Data.go transport for institution-funding collection.

The funding collector only needs the total deposit-liabilities account. Live
GitHub Actions probes verified that Data.go accepts account-code filters for
savings banks and agricultural cooperatives. Applying those filters server-side
avoids downloading the whole financial statement for every historical month.
"""

from __future__ import annotations

import hashlib
import json
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
    _flatten_items,
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


def fetch_month(
    client: httpx.Client,
    *,
    contract: SourceContract,
    endpoint: str,
    key: str,
    bas_ym: str,
) -> tuple[list[dict[str, Any]], list[RawArtifactData]]:
    """Fetch one reporting month with bounded page size and exact account filter."""
    rows: list[dict[str, Any]] = []
    artifacts: list[RawArtifactData] = []
    seen_page_hashes: set[str] = set()

    for page_no in range(1, MAX_PAGES + 1):
        payload, raw, params = _request_json(
            client,
            contract=contract,
            endpoint=endpoint,
            key=key,
            bas_ym=bas_ym,
            page_no=page_no,
        )
        digest = hashlib.sha256(raw).hexdigest()
        if digest in seen_page_hashes:
            raise FundingContractError(
                f"{contract.source_id}/{bas_ym}: pagination이 같은 page를 반복했다"
            )
        seen_page_hashes.add(digest)

        page_rows = _flatten_items(payload)
        rows.extend(page_rows)
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

        if not page_rows or len(page_rows) < PAGE_SIZE:
            break
    else:
        raise FundingContractError(
            f"{contract.source_id}/{bas_ym}: pagination이 {MAX_PAGES} page를 초과했다"
        )

    return rows, artifacts
