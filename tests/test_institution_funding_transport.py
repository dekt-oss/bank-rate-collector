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
    assert savings["debtCptlSmryStfnpsAcitCd"] == "A11"
    assert "dpsdbtDcd" not in savings

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
    assert "debtCptlSmryStfnpsAcitCd" not in credit_union
    assert "dpsdbtDcd" not in credit_union
    assert "astDebtSmryBlnshDcd" not in credit_union


def _agri_row(page_no: int, index: int) -> dict[str, str]:
    return {
        "basYm": "202506",
        "fncoCd": f"{page_no:02d}{index:05d}",
        "fncoNm": f"기관{page_no}-{index}",
        "astDebtSmryBlnshDcd": "A1",
        "astDebtSmryBlnshDcdNm": "예수부채",
        "astDebtSmryBlnshClsfAmt": "1000000",
    }


def _savings_total_row(index: int) -> dict[str, str]:
    return {
        "basYm": "202506",
        "fncoCd": f"001{index:04d}",
        "fncoNm": f"저축은행{index}",
        "debtCptlSmryStfnpsAcitCd": "A11",
        "debtCptlSmryStfnpsAcitCdNm": "예수부채",
        "debtCptlAmt": "5000000",
    }


def _savings_ordinary_deposit_row(index: int) -> dict[str, str]:
    return {
        "basYm": "202506",
        "fncoCd": f"001{index:04d}",
        "fncoNm": f"저축은행{index}",
        "dpsdbtDcd": "A11",
        "dpsdbtDcdNm": "예수부채_예수금_(보 통 예 금)",
        "dpsdbtClsfAmt": "1000000",
    }


def _table(title: str, total_count: int, rows: list[dict[str, str]]) -> dict:
    return {
        "title": title,
        "totalCount": total_count,
        "items": {"item": rows},
    }


def _payload(tables: list[dict]) -> dict:
    return {
        "response": {
            "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE"},
            "body": {"tableList": tables},
        }
    }


class _TablePagingClient:
    def __init__(
        self,
        page_lengths: list[int],
        *,
        total_count: int,
        sector: str = "nh_local",
        repeat_target_page: bool = False,
        change_total_on_page: int | None = None,
        omit_target_on_page: int | None = None,
        include_misleading_savings_table: bool = False,
    ):
        self.page_lengths = page_lengths
        self.total_count = total_count
        self.sector = sector
        self.repeat_target_page = repeat_target_page
        self.change_total_on_page = change_total_on_page
        self.omit_target_on_page = omit_target_on_page
        self.include_misleading_savings_table = include_misleading_savings_table
        self.calls: list[dict[str, str]] = []
        self._first_target_rows: list[dict[str, str]] | None = None

    def get(self, endpoint: str, *, params: dict[str, str]):
        self.calls.append(dict(params))
        page_no = int(params["pageNo"])
        length = self.page_lengths[min(page_no - 1, len(self.page_lengths) - 1)]
        if self.sector == "nh_local":
            target_title = "농협_재무현황_요약재무상태표(부채및자본)"
            target_rows = [_agri_row(page_no, index) for index in range(length)]
        else:
            target_title = "저축_재무현황_요약재무상태표(부채및자본)"
            target_rows = [_savings_total_row(index) for index in range(length)]

        if page_no == 1:
            self._first_target_rows = target_rows
        elif self.repeat_target_page and self._first_target_rows is not None:
            target_rows = self._first_target_rows

        total_count = self.total_count
        if self.change_total_on_page == page_no:
            total_count += 1

        tables = [
            _table(
                "관계없는_대형표",
                74316 if self.sector == "nh_local" else 15840,
                [{"basYm": "202506", "unrelated": f"page-{page_no}"}],
            )
        ]
        if self.include_misleading_savings_table and self.sector == "savings_bank":
            tables.append(
                _table(
                    "저축_재무현황_부채부문별현황_예수부채",
                    80,
                    [_savings_ordinary_deposit_row(index) for index in range(80)],
                )
            )
        if self.omit_target_on_page != page_no:
            tables.append(_table(target_title, total_count, target_rows))
        raw = json.dumps(_payload(tables), ensure_ascii=False).encode()
        request = httpx.Request("GET", endpoint, params=params)
        return httpx.Response(200, content=raw, request=request)


def test_fetch_month_uses_summary_total_not_dedicated_ordinary_deposit_table():
    client = _TablePagingClient(
        [80],
        total_count=80,
        sector="savings_bank",
        include_misleading_savings_table=True,
    )
    contract = _contract("savings_bank")

    rows, artifacts = fetch_month(
        client,
        contract=contract,
        endpoint=contract.finance_endpoint or "https://example.test",
        key="key",
        bas_ym="202506",
    )

    assert len(rows) == 80
    assert len(artifacts) == 1
    assert [call["pageNo"] for call in client.calls] == ["1"]
    assert client.calls[0]["debtCptlSmryStfnpsAcitCd"] == "A11"
    assert "dpsdbtDcd" not in client.calls[0]
    assert all(row["debtCptlSmryStfnpsAcitCdNm"] == "예수부채" for row in rows)
    assert all("dpsdbtDcd" not in row for row in rows)


def test_fetch_month_paginates_by_target_table_total_count_and_preserves_metadata():
    client = _TablePagingClient([PAGE_SIZE, PAGE_SIZE, 126], total_count=1126)
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


def test_fetch_month_rejects_repeated_target_page_even_when_response_bytes_change():
    client = _TablePagingClient(
        [PAGE_SIZE, PAGE_SIZE, 126],
        total_count=1126,
        repeat_target_page=True,
    )
    contract = _contract("nh_local")

    with pytest.raises(FundingContractError, match="같은 target page"):
        fetch_month(
            client,
            contract=contract,
            endpoint=contract.finance_endpoint or "https://example.test",
            key="key",
            bas_ym="202506",
        )


def test_fetch_month_rejects_target_total_count_change_between_pages():
    client = _TablePagingClient(
        [PAGE_SIZE, PAGE_SIZE, 126],
        total_count=1126,
        change_total_on_page=2,
    )
    contract = _contract("nh_local")

    with pytest.raises(FundingContractError, match="totalCount changed"):
        fetch_month(
            client,
            contract=contract,
            endpoint=contract.finance_endpoint or "https://example.test",
            key="key",
            bas_ym="202506",
        )


def test_fetch_month_rejects_target_table_disappearing_mid_pagination():
    client = _TablePagingClient(
        [PAGE_SIZE, PAGE_SIZE, 126],
        total_count=1126,
        omit_target_on_page=2,
    )
    contract = _contract("nh_local")

    with pytest.raises(FundingContractError, match="target table"):
        fetch_month(
            client,
            contract=contract,
            endpoint=contract.finance_endpoint or "https://example.test",
            key="key",
            bas_ym="202506",
        )


def test_fetch_month_accepts_empty_reporting_month_without_paginating_unrelated_tables():
    contract = _contract("savings_bank")

    class EmptyTargetClient:
        calls = 0

        def get(self, endpoint: str, *, params: dict[str, str]):
            self.calls += 1
            raw = json.dumps(
                _payload(
                    [
                        _table("관계없는_표", 1000, [{"basYm": "202606", "foo": "bar"}]),
                        _table("저축_재무현황_요약재무상태표(부채및자본)", 0, []),
                    ]
                ),
                ensure_ascii=False,
            ).encode()
            return httpx.Response(
                200,
                content=raw,
                request=httpx.Request("GET", endpoint, params=params),
            )

    client = EmptyTargetClient()
    rows, artifacts = fetch_month(
        client,
        contract=contract,
        endpoint=contract.finance_endpoint or "https://example.test",
        key="key",
        bas_ym="202606",
    )
    assert rows == []
    assert len(artifacts) == 1
    assert client.calls == 1
