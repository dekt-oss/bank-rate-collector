"""Stage E0 한국은행 ECOS 예금시장 월별지표 계약.

코드/항목/단위는 2026-08-18 metadata + live StatisticSearch Evidence Gate에서
확인했다. 테스트의 숫자값은 파서 경계 검사용 synthetic 값이고 원천 최신값을
복제하려는 fixture가 아니다.
"""

import asyncio
import json
import sqlite3
from decimal import Decimal
from pathlib import Path

import pytest

from rate_monitor.collectors.base import ParseError, SchemaChangedError
from rate_monitor.collectors.bok_ecos import deposit_market_parser as parser
from rate_monitor.collectors.bok_ecos.deposit_market_adapter import (
    BokEcosDepositMarketAdapter,
)
from rate_monitor.db import models as m
from rate_monitor.db.session import create_db_engine, make_session_factory
from rate_monitor.domain.schemas import CollectionRequest, RawArtifactData
from rate_monitor.services.indicator_service import collect_indicator

EXPECTED_CODES = {
    "commercial_bank_1y_new_business_rate": ("121Y002", "BEABAA2118", "percent"),
    "savings_bank_1y_new_business_rate": ("121Y004", "BEBBBE01", "percent"),
    "savings_bank_deposit_balance": ("111Y007", "1120600", "krw_trillion"),
    "credit_union_deposit_balance": ("111Y007", "1120700", "krw_trillion"),
    "mutual_finance_deposit_balance": ("111Y007", "1120800", "krw_trillion"),
    "kfcc_deposit_balance": ("111Y007", "1121000", "krw_trillion"),
}

SYNTHETIC_RAW_VALUES = {
    "commercial_bank_1y_new_business_rate": ("3.10", "3.26"),
    "savings_bank_1y_new_business_rate": ("3.40", "3.74"),
    "savings_bank_deposit_balance": ("100448.7", "100355.8"),
    "credit_union_deposit_balance": ("140100.0", "140366.4"),
    "mutual_finance_deposit_balance": ("510100.0", "510500.5"),
    "kfcc_deposit_balance": ("300100.0", "300400.4"),
}


def _payload(spec: parser.SeriesSpec) -> dict:
    first, second = SYNTHETIC_RAW_VALUES[spec.indicator_code]
    return {
        "StatisticSearch": {
            "list_total_count": 2,
            "row": [
                {
                    "STAT_CODE": spec.stat_code,
                    "STAT_NAME": "검증된 ECOS 통계표",
                    "ITEM_CODE1": spec.item_code,
                    "ITEM_NAME1": spec.expected_item_name,
                    "UNIT_NAME": spec.source_unit,
                    "TIME": "202605",
                    "DATA_VALUE": first,
                },
                {
                    "STAT_CODE": spec.stat_code,
                    "STAT_NAME": "검증된 ECOS 통계표",
                    "ITEM_CODE1": spec.item_code,
                    "ITEM_NAME1": spec.expected_item_name,
                    "UNIT_NAME": spec.source_unit,
                    "TIME": "202606",
                    "DATA_VALUE": second,
                },
            ],
        }
    }


class FixtureAdapter(BokEcosDepositMarketAdapter):
    def __init__(self) -> None:
        super().__init__(api_key="test-key")

    async def fetch(self, request):  # noqa: ANN001, ANN201
        del request
        return [
            RawArtifactData(
                artifact_type="json",
                content=json.dumps(_payload(spec), ensure_ascii=False).encode(),
                filename=f"{spec.indicator_code}.json",
                request_meta={
                    "url": "https://ecos.bok.or.kr/…/[REDACTED]/…",
                    "indicator_code": spec.indicator_code,
                    "stat_code": spec.stat_code,
                    "item_code": spec.item_code,
                    "cycle": "M",
                    "source_unit": spec.source_unit,
                    "storage_unit": spec.unit,
                },
                schema_fingerprint=f"{spec.stat_code}/{spec.item_code}/M",
                source_role=self.source_role,
                trust_level=self.trust_level,
            )
            for spec in parser.SERIES
        ]


@pytest.fixture()
def factory(tmp_path: Path):
    engine = create_db_engine(tmp_path / "deposit-market.sqlite3")
    m.Base.metadata.create_all(engine)
    yield make_session_factory(engine)
    engine.dispose()


def test_series_codes_are_pinned_to_live_recon_evidence() -> None:
    actual = {
        spec.indicator_code: (spec.stat_code, spec.item_code, spec.unit)
        for spec in parser.SERIES
    }
    assert actual == EXPECTED_CODES
    assert parser.SOURCE_ID == "bok_ecos_deposit_market"
    assert parser.CYCLE == "M"


def test_all_six_verified_series_parse() -> None:
    seen = set()
    for spec in parser.SERIES:
        points, warnings = parser.parse(_payload(spec), indicator_code=spec.indicator_code)
        assert warnings == []
        assert len(points) == 2
        assert {point.indicator_code for point in points} == {spec.indicator_code}
        assert {point.unit for point in points} == {spec.unit}
        assert points[-1].source_effective_at.isoformat() == "2026-06-01"
        seen.add(spec.indicator_code)
    assert seen == set(EXPECTED_CODES)


def test_balance_is_normalized_from_billion_to_trillion_without_rounding_loss() -> None:
    spec = parser.spec_for("savings_bank_deposit_balance")
    points, warnings = parser.parse(_payload(spec), indicator_code=spec.indicator_code)

    assert warnings == []
    assert points[0].value == Decimal("100.4487")
    assert points[1].value == Decimal("100.3558")
    assert points[1].unit == "krw_trillion"


def test_rate_series_stays_percent() -> None:
    spec = parser.spec_for("commercial_bank_1y_new_business_rate")
    points, warnings = parser.parse(_payload(spec), indicator_code=spec.indicator_code)

    assert warnings == []
    assert points[-1].value == Decimal("3.26")
    assert points[-1].unit == "percent"


def test_wrong_stat_item_name_and_unit_are_rejected_as_warnings() -> None:
    spec = parser.spec_for("savings_bank_1y_new_business_rate")
    payload = _payload(spec)
    rows = payload["StatisticSearch"]["row"]
    rows[0]["STAT_CODE"] = "WRONG"
    rows[1]["UNIT_NAME"] = "십억원"

    points, warnings = parser.parse(payload, indicator_code=spec.indicator_code)

    assert points == []
    assert any("다른 통계표" in warning for warning in warnings)
    assert any("단위가 바뀌었다" in warning for warning in warnings)

    payload = _payload(spec)
    payload["StatisticSearch"]["row"][0]["ITEM_NAME1"] = "다른 항목"
    points, warnings = parser.parse(payload, indicator_code=spec.indicator_code)
    assert len(points) == 1
    assert any("항목명이 바뀌었다" in warning for warning in warnings)


def test_missing_required_field_is_schema_failure() -> None:
    spec = parser.spec_for("commercial_bank_1y_new_business_rate")
    payload = _payload(spec)
    del payload["StatisticSearch"]["row"][0]["DATA_VALUE"]

    with pytest.raises(SchemaChangedError, match="필수 필드 소실"):
        parser.parse(payload, indicator_code=spec.indicator_code)


def test_http_200_error_body_is_not_silently_empty() -> None:
    with pytest.raises(ParseError, match="ECOS 오류"):
        parser.parse(
            {"RESULT": {"CODE": "INFO-100", "MESSAGE": "인증키 오류"}},
            indicator_code="commercial_bank_1y_new_business_rate",
        )


def test_unknown_indicator_code_fails_closed() -> None:
    with pytest.raises(ParseError, match="지원하지 않는"):
        parser.parse({}, indicator_code="not_verified")


def test_six_series_roundtrip_and_no_duplicate_points(factory, tmp_path: Path) -> None:
    request = CollectionRequest(source_id=parser.SOURCE_ID)
    first = asyncio.run(
        collect_indicator(
            FixtureAdapter(), request, factory, raw_root=tmp_path / "raw"
        )
    )
    assert first.status == "success"
    assert first.fetched == 6
    assert first.parsed == 12
    assert first.stored == 12

    second = asyncio.run(
        collect_indicator(
            FixtureAdapter(), request, factory, raw_root=tmp_path / "raw"
        )
    )
    assert second.status == "no_change"
    assert second.stored == 0
    assert second.unchanged == 12

    conn = sqlite3.connect(tmp_path / "deposit-market.sqlite3")
    try:
        rows = conn.execute(
            "SELECT indicator_code, value, unit, source_id "
            "FROM market_indicators ORDER BY indicator_code, source_effective_at"
        ).fetchall()
    finally:
        conn.close()
    assert len(rows) == 12
    assert {row[0] for row in rows} == set(EXPECTED_CODES)
    assert {row[3] for row in rows} == {parser.SOURCE_ID}


def test_api_key_never_reaches_stored_request_metadata(factory, tmp_path: Path) -> None:
    asyncio.run(
        collect_indicator(
            FixtureAdapter(),
            CollectionRequest(source_id=parser.SOURCE_ID),
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


def test_adapter_masks_key_and_requires_environment(monkeypatch) -> None:
    adapter = BokEcosDepositMarketAdapter(api_key="SECRET123")
    assert "SECRET123" not in adapter._mask(
        "https://ecos.bok.or.kr/api/StatisticSearch/SECRET123/json"
    )

    monkeypatch.delenv("ECOS_API_KEY", raising=False)
    with pytest.raises(Exception, match="ECOS_API_KEY"):
        BokEcosDepositMarketAdapter()
