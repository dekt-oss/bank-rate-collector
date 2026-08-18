"""Stage E0-3 한국은행 ECOS 수신시장 거시지표."""

from __future__ import annotations

import asyncio
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from rate_monitor.collectors.base import CollectorError
from rate_monitor.collectors.bok_ecos import macro_parser
from rate_monitor.collectors.bok_ecos.adapter import BokEcosAdapter
from rate_monitor.collectors.bok_ecos.macro_adapter import (
    BokEcosMacroAdapter,
    _month_key_months_ago,
)
from rate_monitor.db import models as m
from rate_monitor.db.session import create_db_engine, make_session_factory
from rate_monitor.domain.schemas import CollectionRequest, RawArtifactData
from rate_monitor.services.indicator_service import collect_indicator

# trusted-main E0-2 run 32136553896 / artifact 9324218955의 실제 3개월 값.
ACTUAL_VALUES = {
    "bok_bank_savings_deposit_rate": [
        ("202604", "2.92"), ("202605", "2.93"), ("202606", "3.08")
    ],
    "bok_bank_pure_savings_deposit_rate": [
        ("202604", "2.87"), ("202605", "2.88"), ("202606", "3.02")
    ],
    "bok_bank_term_deposit_1y_rate": [
        ("202604", "3.04"), ("202605", "3.06"), ("202606", "3.26")
    ],
    "bok_savings_bank_deposit_balance": [
        ("202604", "100660.7"), ("202605", "100448.7"), ("202606", "100355.8")
    ],
    "bok_credit_union_deposit_balance": [
        ("202604", "142384.1"), ("202605", "141265.4"), ("202606", "140366.4")
    ],
    "bok_broad_mutual_finance_deposit_balance": [
        ("202604", "526124.0"), ("202605", "522108.2"), ("202606", "519427.3")
    ],
    "bok_kfcc_deposit_balance": [
        ("202604", "247123.1"), ("202605", "243791"), ("202606", "243247.8")
    ],
}


def _payload(contract: macro_parser.SeriesContract) -> dict:
    rows = [
        {
            "STAT_CODE": contract.stat_code,
            "STAT_NAME": "verified E0 source",
            "ITEM_CODE1": contract.item_code,
            "ITEM_NAME1": contract.item_name,
            "UNIT_NAME": contract.source_unit,
            "TIME": month,
            "DATA_VALUE": value,
        }
        for month, value in ACTUAL_VALUES[contract.indicator_code]
    ]
    return {"StatisticSearch": {"list_total_count": len(rows), "row": rows}}


class FixtureMacroAdapter(BokEcosMacroAdapter):
    def __init__(self) -> None:
        super().__init__(api_key="test-key")

    async def fetch(self, request):  # noqa: ANN001, ANN201
        del request
        return [
            RawArtifactData(
                artifact_type="json",
                content=json.dumps(_payload(contract), ensure_ascii=False).encode(),
                filename=f"{contract.indicator_code}.json",
                request_meta={
                    "url": "https://ecos.bok.or.kr/…/[REDACTED]/…",
                    "indicator_code": contract.indicator_code,
                    "stat_code": contract.stat_code,
                    "item_code": contract.item_code,
                    "cycle": "M",
                },
                schema_fingerprint=f"{contract.stat_code}/{contract.item_code}",
                source_role=self.source_role,
                trust_level=self.trust_level,
            )
            for contract in macro_parser.CONTRACTS
        ]


@pytest.fixture()
def factory(tmp_path: Path):
    engine = create_db_engine(tmp_path / "bok-macro.sqlite3")
    m.Base.metadata.create_all(engine)
    return make_session_factory(engine)


def test_contracts_are_exactly_the_verified_e0_series() -> None:
    by_code = {contract.indicator_code: contract for contract in macro_parser.CONTRACTS}

    assert by_code["bok_bank_savings_deposit_rate"].item_code == "BEABAA2"
    assert by_code["bok_bank_pure_savings_deposit_rate"].item_code == "BEABAA21"
    assert by_code["bok_bank_term_deposit_1y_rate"].item_code == "BEABAA2118"
    assert by_code["bok_savings_bank_deposit_balance"].item_code == "1120600"
    assert by_code["bok_credit_union_deposit_balance"].item_code == "1120700"
    assert by_code["bok_broad_mutual_finance_deposit_balance"].item_code == "1120800"
    assert by_code["bok_kfcc_deposit_balance"].item_code == "1121000"
    assert {contract.stat_code for contract in macro_parser.CONTRACTS} == {
        "121Y002", "111Y007"
    }


def test_macro_source_is_isolated_from_the_existing_base_rate_source() -> None:
    assert BokEcosAdapter.source_id == "bok_ecos"
    assert BokEcosMacroAdapter.source_id == "bok_ecos_macro"


def test_verified_bank_rate_parses_to_month_end_percent() -> None:
    contract = macro_parser.CONTRACT_BY_INDICATOR["bok_bank_pure_savings_deposit_rate"]
    points, warnings = macro_parser.parse(_payload(contract), contract)

    assert warnings == []
    assert points[-1].value == Decimal("3.02")
    assert points[-1].unit == "percent"
    assert points[-1].source_effective_at == date(2026, 6, 30)
    assert points[-1].source_locator == "121Y002/BEABAA21/202606"


def test_verified_balance_converts_billion_to_trillion_without_precision_loss() -> None:
    contract = macro_parser.CONTRACT_BY_INDICATOR[
        "bok_savings_bank_deposit_balance"
    ]
    points, warnings = macro_parser.parse(_payload(contract), contract)

    assert warnings == []
    assert points[-1].value == Decimal("100.3558")
    assert points[-1].unit == "trillion_krw"
    assert points[-1].source_effective_at == date(2026, 6, 30)


def test_broad_mutual_finance_is_never_named_nh_local() -> None:
    contract = macro_parser.CONTRACT_BY_INDICATOR[
        "bok_broad_mutual_finance_deposit_balance"
    ]

    assert contract.item_name == "상호금융"
    assert "광의 상호금융" in contract.indicator_name
    assert "농·축협" not in contract.indicator_name


def test_changed_unit_is_refused_instead_of_silently_rescaled() -> None:
    contract = macro_parser.CONTRACT_BY_INDICATOR["bok_savings_bank_deposit_balance"]
    payload = _payload(contract)
    payload["StatisticSearch"]["row"][0]["UNIT_NAME"] = "억원"

    points, warnings = macro_parser.parse(payload, contract)

    assert len(points) == 2
    assert any("단위가 바뀌었다" in warning for warning in warnings)


def test_balance_over_current_storage_capacity_fails_closed() -> None:
    contract = macro_parser.CONTRACT_BY_INDICATOR["bok_savings_bank_deposit_balance"]
    payload = _payload(contract)
    payload["StatisticSearch"]["row"][0]["DATA_VALUE"] = "1000000.0"

    points, warnings = macro_parser.parse(payload, contract)

    assert len(points) == 2
    assert any("값 범위/형식" in warning for warning in warnings)


def test_month_window_has_48_calendar_months_including_current() -> None:
    today = date(2026, 8, 18)

    assert _month_key_months_ago(today, 0) == "202608"
    assert _month_key_months_ago(today, 47) == "202209"


def test_all_seven_series_store_through_existing_indicator_service(
    factory, tmp_path: Path
) -> None:
    request = CollectionRequest(source_id="bok_ecos_macro")
    first = asyncio.run(
        collect_indicator(
            FixtureMacroAdapter(), request, factory, raw_root=tmp_path / "raw"
        )
    )

    assert first.status == "success"
    assert first.fetched == 7
    assert first.parsed == 21
    assert first.stored == 21
    assert first.warnings == 0

    with factory() as session:
        rows = session.query(m.MarketIndicator).all()
        codes = {row.indicator_code for row in rows}
        june_balance = (
            session.query(m.MarketIndicator)
            .filter_by(
                indicator_code="bok_savings_bank_deposit_balance",
                source_effective_at=date(2026, 6, 30),
            )
            .one()
        )

    assert len(rows) == 21
    assert codes == {contract.indicator_code for contract in macro_parser.CONTRACTS}
    assert june_balance.value == Decimal("100.3558")
    assert june_balance.unit == "trillion_krw"

    second = asyncio.run(
        collect_indicator(
            FixtureMacroAdapter(), request, factory, raw_root=tmp_path / "raw"
        )
    )
    assert second.status == "no_change"
    assert (second.stored, second.unchanged) == (0, 21)


def test_macro_artifact_metadata_never_contains_the_api_key(
    factory, tmp_path: Path
) -> None:
    asyncio.run(
        collect_indicator(
            FixtureMacroAdapter(),
            CollectionRequest(source_id="bok_ecos_macro"),
            factory,
            raw_root=tmp_path / "raw",
        )
    )
    with factory() as session:
        blob = json.dumps(
            [artifact.request_meta_json for artifact in session.query(m.RawArtifact).all()],
            ensure_ascii=False,
        )

    assert "test-key" not in blob
    assert "[REDACTED]" in blob


def test_unknown_indicator_metadata_fails_closed() -> None:
    adapter = BokEcosMacroAdapter(api_key="test-key")
    artifact = RawArtifactData(
        artifact_type="json",
        content=b"{}",
        filename="unknown.json",
        request_meta={"indicator_code": "unknown"},
        schema_fingerprint="unknown",
        source_role=adapter.source_role,
        trust_level=adapter.trust_level,
    )

    with pytest.raises(CollectorError, match="알 수 없는 ECOS macro indicator"):
        adapter.parse_points(artifact)
