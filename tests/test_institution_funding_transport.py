from __future__ import annotations

import json

import httpx
import pytest

from rate_monitor.collectors.data_go_funding.collector import CONTRACTS, FundingContractError
from rate_monitor.collectors.data_go_funding.transport import (
    PAGE_SIZE,
    fetch_month,
    request_params,
)


def _contract(sector: str):
    return next(contract for contract in CONTRACTS if contract.sector == sector)


def test_request_params_filter_only_verified_total_accounts():
    savings = request_params(
        _contract("savings_bank"),
        key="key",
        bas_ym="202506",
        page_no=1,
    )
    assert savings["numOfRows"] == "500"
    assert savings["dpsdbtDcd"] == "A11"

    agri = request_params(
        _contract("nh_local"),
        key="key",
        bas_ym="202506",
        page_no=1,
    )
    assert agri["numOfRows"] == "500"
    assert agri["astDebtSmryBlnshDcd"] == "A1"

    credit_union = request_params(
        _contract("cu"),
        key="key",
        bas_ym="202506",
        page_no=1,
    )
    assert credit_union["numOfRows"] == "500"
    assert "dpsdbtDcd" not in credit_union
    assert "astDebtSmryBlnshDcd" not in credit_union


def _payload(rows):
    return {
        "response": {
            "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE"},
            "body": {"items": {"item": rows}},
        }
    }


class _PagingClient:
    def __init__(self, page_lengths: list[int], *, repeat_page: bool = False):
        self.page_lengths = page_lengths
        self.repeat_page = repeat_page
        self.calls: list[dict[str, str]] = []
        self._first_raw: bytes | None = None

    def get(self, endpoint: str, *, params: dict[str, str]):
        self.calls.append(dict(params))
        page_no = int(params["pageNo"])
        length = self.page_lengths[min(page_no - 1, len(self.page_lengths) - 1)]
        rows = [
            {
                "basYm": "202506",
                "fncoCd": f"{page_no:02d}{index:05d}",
                "fncoNm": f"기관{page_no}-{index}",
                "astDebtSmryBlnshDcd": "A1",
                "astDebtSmryBlnshDcdNm": "예수부채",
                "astDebtSmryBlnshClsfAmt": "1000000",
            }
            for index in range(length)
        ]
        raw = json.dumps(_payload(rows), ensure_ascii=False).encode()
        if self.repeat_page and page_no > 1 and self._first_raw is not None:
            raw = self._first_raw
        elif page_no == 1:
            self._first_raw = raw
        request = httpx.Request("GET", endpoint, params=params)
        return httpx.Response(200, content=raw, request=request)


def test_fetch_month_paginates_until_short_page_and_preserves_filter_metadata():
    client = _PagingClient([PAGE_SIZE, PAGE_SIZE, 126])
    contract = _contract("nh_local")

    rows, artifacts = fetch_month(
        client,
        contract=contract,
        endpoint=contract.finance_endpoint or "https://example.test",
        key="key",
        bas_ym="202506",
    )

    assert len(rows) == 1126
    assert len(artifacts) == 3
    assert [call["pageNo"] for call in client.calls] == ["1", "2", "3"]
    assert all(call["numOfRows"] == "500" for call in client.calls)
    assert all(call["astDebtSmryBlnshDcd"] == "A1" for call in client.calls)
    assert artifacts[0].request_meta["numOfRows"] == 500
    assert artifacts[0].request_meta["astDebtSmryBlnshDcd"] == "A1"


def test_fetch_month_rejects_repeated_full_page_instead_of_silently_truncating():
    client = _PagingClient([PAGE_SIZE, PAGE_SIZE], repeat_page=True)
    contract = _contract("nh_local")

    with pytest.raises(FundingContractError, match="같은 page"):
        fetch_month(
            client,
            contract=contract,
            endpoint=contract.finance_endpoint or "https://example.test",
            key="key",
            bas_ym="202506",
        )
