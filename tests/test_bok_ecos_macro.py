"""한국은행 ECOS 수신시장 거시지표 수집·저장 계약."""

from __future__ import annotations

import asyncio
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import text as sql_text

from rate_monitor.collectors.base import CollectorError, ParseError, SchemaChangedError
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

# 2026-08-18 E0와 2026-08-27 D0 exact probe의 실제 최근값. balance는 ECOS
# source unit인 십억원 그대로 적고 parser가 trillion_krw로 변환한다.
ACTUAL_VALUES = {
    "bok_bank_savings_deposit_rate": [
        ("202604", "2.92"), ("202605", "2.93"), ("202606", "3.08")
    ],
    "bok_bank_pure_savings_deposit_rate": [
        ("202604", "2.87"), ("202605", "2.88"), ("202606", "3.02")
    ],
    "bok_bank_term_deposit_1y_rate": [
        ("202605", "3.06"), ("202606", "3.26"), ("202607", "3.48")
    ],
    "bok_savings_bank_term_deposit_1y_rate": [
        ("202605", "3.39"), ("202606", "3.74"), ("202607", "4.21")
    ],
    "bok_credit_union_term_deposit_1y_rate": [
        ("202605", "3.25"), ("202606", "3.43"), ("202607", "3.56")
    ],
    "bok_kfcc_term_deposit_1y_rate": [
        ("202605", "3.21"), ("202606", "3.53"), ("202607", "3.48")
    ],
    "bok_savings_bank_deposit_balance": [
        ("202604", "100660.7"), ("202605", "100448.7"), ("202606", "100355.8")
    ],
    "bok_credit_union_deposit_balance": [
        ("202604", "142384.1"), ("202605", "141265.4"), ("202606", "140366.4")
    ],
    "bok_broad_mutual_finance_deposit_balance": [
        ("202604", "526124"), ("202605", "522108.2"), ("202606", "519427.3")
    ],
    "bok_kfcc_deposit_balance": [
        ("202604", "247123.1"), ("202605", "243791"), ("202606", "243247.8")
    ],
    "bok_bank_total_deposit_balance": [
        ("202604", "2216678.6"), ("202605", "2255298.3"), ("202606", "2281489.1")
    ],
    "bok_bank_savings_deposit_balance": [
        ("202604", "1852875.6"), ("202605", "1884028.9"), ("202606", "1896127")
    ],
    "bok_bank_term_deposit_balance": [
        ("202604", "1105418.1"), ("202605", "1120054.3"), ("202606", "1132502.6")
    ],
    "bok_bank_installment_savings_balance": [
        ("202604", "62541.1"), ("202605", "62487.4"), ("202606", "62658.9")
    ],
    "bok_bank_term_deposit_lt_6m_balance": [
        ("202604", "204345.7"), ("202605", "217434"), ("202606", "238366.2")
    ],
    "bok_bank_term_deposit_6m_lt_1y_balance": [
        ("202604", "193326.2"), ("202605", "189738.8"), ("202606", "176076.3")
    ],
    "bok_bank_term_deposit_1y_lt_2y_balance": [
        ("202604", "655240.3"), ("202605", "657590.7"), ("202606", "661978.5")
    ],
    "bok_bank_term_deposit_2y_lt_3y_balance": [
        ("202604", "25076.3"), ("202605", "28159.5"), ("202606", "29438.3")
    ],
    "bok_bank_term_deposit_3y_plus_balance": [
        ("202604", "27429.5"), ("202605", "27131.2"), ("202606", "26643.3")
    ],
}


def _payload(contract: macro_parser.SeriesContract) -> dict:
    rows = [
        {
            "STAT_CODE": contract.stat_code,
            "STAT_NAME": "verified ECOS source",
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


def test_contracts_are_exactly_the_verified_operational_plus_d0_series() -> None:
    by_code = {contract.indicator_code: contract for contract in macro_parser.CONTRACTS}

    assert len(by_code) == 19
    assert by_code["bok_bank_term_deposit_1y_rate"].item_code == "BEABAA2118"
    assert by_code["bok_savings_bank_term_deposit_1y_rate"].item_code == "BEBBBE01"
    assert by_code["bok_credit_union_term_deposit_1y_rate"].item_code == "BEBBBG01"
    assert by_code["bok_kfcc_term_deposit_1y_rate"].item_code == "BEBBA000"
    assert by_code["bok_bank_total_deposit_balance"].item_code == "BDAA1"
    assert by_code["bok_bank_installment_savings_balance"].item_code == "BDAA33"
    assert by_code["bok_bank_term_deposit_3y_plus_balance"].item_code == "1070000"
    assert {contract.stat_code for contract in macro_parser.CONTRACTS} == {
        "121Y002", "121Y004", "111Y007", "104Y015", "104Y010"
    }
    assert all(contract.value_semantics for contract in macro_parser.CONTRACTS)
    assert all(contract.population for contract in macro_parser.CONTRACTS)


def test_macro_source_is_isolated_from_the_existing_base_rate_source() -> None:
    assert BokEcosAdapter.source_id == "bok_ecos"
    assert BokEcosMacroAdapter.source_id == "bok_ecos_macro"


def test_verified_nonbank_rate_parses_to_month_end_percent() -> None:
    contract = macro_parser.CONTRACT_BY_INDICATOR[
        "bok_savings_bank_term_deposit_1y_rate"
    ]
    points, warnings = macro_parser.parse(_payload(contract), contract)

    assert warnings == []
    assert points[-1].value == Decimal("4.210000")
    assert points[-1].unit == "percent"
    assert points[-1].source_effective_at == date(2026, 7, 31)
    assert points[-1].source_locator == "121Y004/BEBBBE01/202607"


def test_verified_balance_converts_billion_to_trillion_without_precision_loss() -> None:
    contract = macro_parser.CONTRACT_BY_INDICATOR[
        "bok_savings_bank_deposit_balance"
    ]
    points, warnings = macro_parser.parse(_payload(contract), contract)

    assert warnings == []
    assert points[-1].value == Decimal("100.355800")
    assert points[-1].unit == "trillion_krw"
    assert points[-1].source_effective_at == date(2026, 6, 30)


def test_bank_total_over_2000_trillion_is_accepted_losslessly() -> None:
    contract = macro_parser.CONTRACT_BY_INDICATOR["bok_bank_total_deposit_balance"]
    points, warnings = macro_parser.parse(_payload(contract), contract)

    assert warnings == []
    assert points[-1].value == Decimal("2281.489100")


def test_broad_mutual_finance_is_never_named_nh_local() -> None:
    contract = macro_parser.CONTRACT_BY_INDICATOR[
        "bok_broad_mutual_finance_deposit_balance"
    ]

    assert contract.item_name == "상호금융"
    assert "광의 상호금융" in contract.indicator_name
    assert "농·축협" not in contract.indicator_name
    assert "broad" in contract.population


def test_changed_unit_fails_the_whole_contract_artifact() -> None:
    contract = macro_parser.CONTRACT_BY_INDICATOR["bok_savings_bank_deposit_balance"]
    payload = _payload(contract)
    payload["StatisticSearch"]["row"][0]["UNIT_NAME"] = "억원"

    with pytest.raises(SchemaChangedError, match="단위가 바뀌었다"):
        macro_parser.parse(payload, contract)


def test_pagination_count_mismatch_fails_closed() -> None:
    contract = macro_parser.CONTRACT_BY_INDICATOR["bok_bank_total_deposit_balance"]
    payload = _payload(contract)
    payload["StatisticSearch"]["list_total_count"] = 999

    with pytest.raises(SchemaChangedError, match="pagination/count"):
        macro_parser.parse(payload, contract)


def test_quantity_precision_over_six_decimals_fails_closed() -> None:
    contract = macro_parser.CONTRACT_BY_INDICATOR["bok_bank_total_deposit_balance"]
    payload = _payload(contract)
    # 십억원 / 1000 뒤 7자리 소수가 남도록 만든다.
    payload["StatisticSearch"]["row"][0]["DATA_VALUE"] = "1.2345678"

    with pytest.raises(ParseError, match="정밀도"):
        macro_parser.parse(payload, contract)


def test_ecos_info_200_is_no_data_not_schema_or_network_failure() -> None:
    contract = macro_parser.CONTRACT_BY_INDICATOR["bok_bank_total_deposit_balance"]
    points, notes = macro_parser.parse(
        {"RESULT": {"CODE": "INFO-200", "MESSAGE": "해당하는 데이터가 없습니다."}},
        contract,
    )

    assert points == []
    assert len(notes) == 1
    assert "no_data" in notes[0]


def test_month_window_has_48_calendar_months_including_current() -> None:
    today = date(2026, 8, 18)

    assert _month_key_months_ago(today, 0) == "202608"
    assert _month_key_months_ago(today, 47) == "202209"


def test_all_verified_series_store_through_existing_indicator_service(
    factory, tmp_path: Path
) -> None:
    request = CollectionRequest(source_id="bok_ecos_macro")
    first = asyncio.run(
        collect_indicator(
            FixtureMacroAdapter(), request, factory, raw_root=tmp_path / "raw"
        )
    )

    expected_points = len(macro_parser.CONTRACTS) * 3
    assert first.status == "success"
    assert first.fetched == 19
    assert first.parsed == expected_points
    assert first.stored == expected_points
    assert first.warnings == 0

    with factory() as session:
        rows = session.query(m.MarketIndicator).all()
        codes = {row.indicator_code for row in rows}
        june_bank_total = (
            session.query(m.MarketIndicator)
            .filter_by(
                indicator_code="bok_bank_total_deposit_balance",
                source_effective_at=date(2026, 6, 30),
            )
            .one()
        )
        raw = session.execute(
            sql_text(
                "SELECT value, typeof(value) FROM market_indicators "
                "WHERE id = :id"
            ),
            {"id": june_bank_total.id},
        ).one()

    assert len(rows) == expected_points
    assert codes == {contract.indicator_code for contract in macro_parser.CONTRACTS}
    assert june_bank_total.value == Decimal("2281.489100")
    assert june_bank_total.unit == "trillion_krw"
    assert raw == ("000000002281.489100", "text")

    second = asyncio.run(
        collect_indicator(
            FixtureMacroAdapter(), request, factory, raw_root=tmp_path / "raw"
        )
    )
    assert second.status == "no_change"
    assert (second.stored, second.unchanged) == (0, expected_points)

    with factory() as session:
        assert session.query(m.ReviewItem).filter_by(
            issue_type="market_indicator_revision"
        ).count() == 0


def test_source_revision_is_audited_before_canonical_update(
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
    contract = macro_parser.CONTRACT_BY_INDICATOR[
        "bok_savings_bank_term_deposit_1y_rate"
    ]
    payload = _payload(contract)
    payload["StatisticSearch"]["row"][-1]["DATA_VALUE"] = "4.22"

    class RevisionAdapter(BokEcosMacroAdapter):
        def __init__(self) -> None:
            super().__init__(api_key="test-key")

        async def fetch(self, request):  # noqa: ANN001, ANN201
            del request
            return [
                RawArtifactData(
                    artifact_type="json",
                    content=json.dumps(payload, ensure_ascii=False).encode(),
                    filename="revision.json",
                    request_meta={"indicator_code": contract.indicator_code},
                    schema_fingerprint="revision",
                    source_role=self.source_role,
                    trust_level=self.trust_level,
                )
            ]

    result = asyncio.run(
        collect_indicator(
            RevisionAdapter(),
            CollectionRequest(source_id="bok_ecos_macro"),
            factory,
            raw_root=tmp_path / "raw-revision",
        )
    )
    assert result.status == "success"
    assert result.stored == 1
    assert result.unchanged == 2

    with factory() as session:
        latest = (
            session.query(m.MarketIndicator)
            .filter_by(
                indicator_code=contract.indicator_code,
                source_effective_at=date(2026, 7, 31),
            )
            .one()
        )
        audit = session.query(m.ReviewItem).filter_by(
            issue_type="market_indicator_revision"
        ).one()

    assert latest.value == Decimal("4.220000")
    assert audit.entity_id == latest.id
    assert audit.payload_json["old_value"] == "4.210000"
    assert audit.payload_json["new_value"] == "4.220000"
    assert audit.payload_json["old_raw_artifact_id"] != audit.payload_json["new_raw_artifact_id"]


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
