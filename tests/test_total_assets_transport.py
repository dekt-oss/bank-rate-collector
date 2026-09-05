import json

import httpx
import pytest

from rate_monitor.collectors.data_go_funding import total_assets_transport as transport
from rate_monitor.collectors.data_go_funding.collector import (
    CONTRACTS,
    FundingContractError,
)


def _contract(source_id: str):
    return next(contract for contract in CONTRACTS if contract.source_id == source_id)


def _payload(title: str, total: int, rows: list[dict[str, str]]) -> dict[str, object]:
    return {
        "response": {
            "body": {
                "tableList": [
                    {
                        "title": title,
                        "totalCount": total,
                        "items": {"item": rows},
                    }
                ]
            }
        }
    }


def test_asset_request_uses_exact_asset_filter() -> None:
    savings = _contract("data_go_savings_bank_funding")
    params = transport.request_params(
        savings,
        key="secret",
        bas_ym="202512",
        page_no=1,
    )
    assert params["astSmryStfnpsAcitCd"] == "A"
    assert "debtCptlSmryStfnpsAcitCd" not in params


def test_fetch_month_follows_asset_table_total_count_beyond_funding_style_page_counts(
    monkeypatch,
) -> None:
    contract = _contract("data_go_agri_coop_funding")
    title = transport.TARGET_TABLE_TITLES[contract.source_id]
    calls: list[int] = []

    def fake_request(client, *, contract, endpoint, key, bas_ym, page_no):
        del client, endpoint, key
        calls.append(page_no)
        start = (page_no - 1) * transport.PAGE_SIZE
        end = min(start + transport.PAGE_SIZE, 1126)
        rows = [
            {
                "fncoCd": f"{i:013d}",
                "fncoNm": f"기관{i}",
                "basYm": bas_ym,
                "astSmryBlnshDcd": "A",
                "astSmryBlnshDcdNm": "자산총계",
                "astSmryBlnshClsfAmt": "1000000",
            }
            for i in range(start, end)
        ]
        payload = _payload(title, 1126, rows)
        raw = json.dumps(payload, ensure_ascii=False).encode()
        params = transport.request_params(
            contract,
            key="secret",
            bas_ym=bas_ym,
            page_no=page_no,
        )
        return payload, raw, params

    monkeypatch.setattr(transport, "_request_json", fake_request)
    with httpx.Client() as client:
        rows, artifacts = transport.fetch_month(
            client,
            contract=contract,
            endpoint="https://example.invalid/agri",
            key="secret",
            bas_ym="202512",
        )

    assert len(rows) == 1126
    assert len(artifacts) == 3
    assert calls == [1, 2, 3]
    assert all(artifact.request_meta["metric"] == "total_assets" for artifact in artifacts)


def test_asset_pagination_fails_closed_over_explicit_safety_cap(monkeypatch) -> None:
    contract = _contract("data_go_agri_coop_funding")
    title = transport.TARGET_TABLE_TITLES[contract.source_id]
    rows = [
        {
            "fncoCd": f"{i:013d}",
            "fncoNm": f"기관{i}",
            "basYm": "202512",
            "astSmryBlnshDcd": "A",
            "astSmryBlnshDcdNm": "자산총계",
            "astSmryBlnshClsfAmt": "1000000",
        }
        for i in range(transport.PAGE_SIZE)
    ]

    def fake_request(client, *, contract, endpoint, key, bas_ym, page_no):
        del client, endpoint, key
        payload = _payload(title, transport.PAGE_SIZE * transport.MAX_PAGES + 1, rows)
        raw = json.dumps(payload).encode()
        params = transport.request_params(
            contract,
            key="secret",
            bas_ym=bas_ym,
            page_no=page_no,
        )
        return payload, raw, params

    monkeypatch.setattr(transport, "_request_json", fake_request)
    with httpx.Client() as client, pytest.raises(FundingContractError, match="MAX_PAGES"):
        transport.fetch_month(
            client,
            contract=contract,
            endpoint="https://example.invalid/agri",
            key="secret",
            bas_ym="202512",
        )
