import json

import httpx
import pytest

from rate_monitor.collectors.data_go_funding import total_assets_transport as transport
from rate_monitor.collectors.data_go_funding.collector import (
    CONTRACTS,
    FundingContractError,
    FundingTransportError,
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


def _accepted_payload() -> dict[str, object]:
    return {
        "response": {
            "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."},
            "body": {"tableList": []},
        }
    }


def test_asset_request_uses_documented_title_and_month_filters() -> None:
    savings = _contract("data_go_savings_bank_funding")
    params = transport.request_params(
        savings,
        key="secret",
        bas_ym="202512",
        page_no=1,
    )
    assert params["title"] == transport.TARGET_TABLE_TITLES[savings.source_id]
    assert params["basYm"] == "202512"
    # Account codes are response fields; they are validated locally rather than
    # sent as undocumented server-side request parameters.
    assert "astSmryStfnpsAcitCd" not in params
    assert "debtCptlSmryStfnpsAcitCd" not in params


def test_asset_request_has_bounded_longer_timeout_and_recovers_from_transient_timeout(
    monkeypatch,
) -> None:
    contract = _contract("data_go_savings_bank_funding")
    attempts: list[float] = []

    class FakeClient:
        def get(self, endpoint, *, params, timeout):
            del params
            attempts.append(timeout)
            if len(attempts) < len(transport.ASSET_RETRY_DELAYS):
                raise httpx.ReadTimeout("timed out")
            request = httpx.Request("GET", endpoint)
            return httpx.Response(200, json=_accepted_payload(), request=request)

    monkeypatch.setattr(transport.time, "sleep", lambda _delay: None)
    payload, raw, params = transport._request_json(
        FakeClient(),
        contract=contract,
        endpoint="https://example.invalid/savings",
        key="secret",
        bas_ym="202512",
        page_no=7,
    )

    assert payload == _accepted_payload()
    assert json.loads(raw) == _accepted_payload()
    assert params["pageNo"] == "7"
    assert attempts == [transport.ASSET_REQUEST_TIMEOUT_SECONDS] * len(
        transport.ASSET_RETRY_DELAYS
    )
    assert transport.ASSET_REQUEST_TIMEOUT_SECONDS > 30.0


def test_asset_request_retry_exhaustion_reports_exact_source_month_and_page(
    monkeypatch,
) -> None:
    contract = _contract("data_go_savings_bank_funding")
    attempts = 0

    class FakeClient:
        def get(self, endpoint, *, params, timeout):
            del endpoint, params, timeout
            nonlocal attempts
            attempts += 1
            raise httpx.ReadTimeout("timed out")

    monkeypatch.setattr(transport.time, "sleep", lambda _delay: None)
    with pytest.raises(
        FundingTransportError,
        match=r"source=data_go_savings_bank_funding month=202512 page=7",
    ):
        transport._request_json(
            FakeClient(),
            contract=contract,
            endpoint="https://example.invalid/savings",
            key="secret",
            bas_ym="202512",
            page_no=7,
        )
    assert attempts == len(transport.ASSET_RETRY_DELAYS)


def test_complete_asset_table_is_paged_before_exact_total_account_filter(monkeypatch) -> None:
    contract = _contract("data_go_savings_bank_funding")
    title = transport.TARGET_TABLE_TITLES[contract.source_id]
    table_rows = [
        {
            "fncoCd": "0010",
            "fncoNm": "A저축은행",
            "basYm": "202512",
            "astSmryStfnpsAcitCd": "A",
            "astSmryStfnpsAcitCdNm": "자산총계",
            "astSmryStfnpsAcitCdAmt": "1000000",
        },
        {
            "fncoCd": "0010",
            "fncoNm": "A저축은행",
            "basYm": "202512",
            "astSmryStfnpsAcitCd": "A1",
            "astSmryStfnpsAcitCdNm": "현금및예치금",
            "astSmryStfnpsAcitCdAmt": "100000",
        },
    ]

    def fake_request(client, *, contract, endpoint, key, bas_ym, page_no):
        del client, endpoint, key, page_no
        payload = _payload(title, 2, table_rows)
        raw = json.dumps(payload, ensure_ascii=False).encode()
        params = transport.request_params(
            contract,
            key="secret",
            bas_ym=bas_ym,
            page_no=1,
        )
        return payload, raw, params

    monkeypatch.setattr(transport, "_request_json", fake_request)
    with httpx.Client() as client:
        rows, artifacts = transport.fetch_month(
            client,
            contract=contract,
            endpoint="https://example.invalid/savings",
            key="secret",
            bas_ym="202512",
        )

    assert len(rows) == 1
    assert rows[0]["astSmryStfnpsAcitCd"] == "A"
    assert artifacts[0].request_meta["title"] == title
    assert artifacts[0].request_meta["local_account_filter"] == {
        "astSmryStfnpsAcitCd": "A"
    }


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
    assert all(artifact.request_meta["title"] == title for artifact in artifacts)


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
