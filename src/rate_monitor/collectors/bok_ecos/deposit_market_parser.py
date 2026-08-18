"""Stage E0 예금시장 외부지표 ECOS 월별 시계열 파서.

통계코드와 항목코드는 2026-08-18 read-only ECOS 정찰에서 이름으로 찾고,
실제 ``StatisticSearch`` 월별 응답까지 검증한 6개 계열만 허용한다.

- 예금은행 1년 정기예금 신규취급액 금리
- 상호저축은행 1년 정기예금 신규취급액 금리
- 상호저축은행 / 신용협동조합 / 상호금융 / 새마을금고 수신 말잔

수신잔액 원천 단위는 ``십억원``이지만 ``market_indicators.value``는 기존
DECIMAL(7,4) 상당 ``Rate`` 타입을 사용해 999.9999가 최대다. 따라서 DB
migration 없이 정확도를 유지하도록 ``십억원 / 1000 = 조원``으로 정규화한다.
원천값은 raw artifact에 그대로 보존된다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, NamedTuple

from rate_monitor.collectors.base import ParseError, SchemaChangedError

SOURCE_ID = "bok_ecos_deposit_market"
CYCLE = "M"
RESULT_KEY = "StatisticSearch"
REQUIRED_FIELDS = frozenset(
    {"STAT_CODE", "ITEM_CODE1", "ITEM_NAME1", "TIME", "DATA_VALUE", "UNIT_NAME"}
)


@dataclass(frozen=True)
class SeriesSpec:
    indicator_code: str
    indicator_name: str
    stat_code: str
    item_code: str
    expected_item_name: str
    source_unit: str
    unit: str
    multiplier: Decimal
    minimum: Decimal
    maximum: Decimal


SERIES: tuple[SeriesSpec, ...] = (
    SeriesSpec(
        indicator_code="commercial_bank_1y_new_business_rate",
        indicator_name="예금은행 1년 정기예금 신규취급액 금리",
        stat_code="121Y002",
        item_code="BEABAA2118",
        expected_item_name="정기예금(1년)",
        source_unit="연리%",
        unit="percent",
        multiplier=Decimal("1"),
        minimum=Decimal("0"),
        maximum=Decimal("25"),
    ),
    SeriesSpec(
        indicator_code="savings_bank_1y_new_business_rate",
        indicator_name="상호저축은행 1년 정기예금 신규취급액 금리",
        stat_code="121Y004",
        item_code="BEBBBE01",
        expected_item_name="상호저축은행-정기예금(1년)",
        source_unit="연리%",
        unit="percent",
        multiplier=Decimal("1"),
        minimum=Decimal("0"),
        maximum=Decimal("25"),
    ),
    SeriesSpec(
        indicator_code="savings_bank_deposit_balance",
        indicator_name="상호저축은행 수신 말잔",
        stat_code="111Y007",
        item_code="1120600",
        expected_item_name="상호저축은행",
        source_unit="십억원",
        unit="krw_trillion",
        multiplier=Decimal("0.001"),
        minimum=Decimal("0"),
        maximum=Decimal("999.9999"),
    ),
    SeriesSpec(
        indicator_code="credit_union_deposit_balance",
        indicator_name="신용협동조합 수신 말잔",
        stat_code="111Y007",
        item_code="1120700",
        expected_item_name="신용협동조합",
        source_unit="십억원",
        unit="krw_trillion",
        multiplier=Decimal("0.001"),
        minimum=Decimal("0"),
        maximum=Decimal("999.9999"),
    ),
    SeriesSpec(
        indicator_code="mutual_finance_deposit_balance",
        indicator_name="상호금융 수신 말잔",
        stat_code="111Y007",
        item_code="1120800",
        expected_item_name="상호금융",
        source_unit="십억원",
        unit="krw_trillion",
        multiplier=Decimal("0.001"),
        minimum=Decimal("0"),
        maximum=Decimal("999.9999"),
    ),
    SeriesSpec(
        indicator_code="kfcc_deposit_balance",
        indicator_name="새마을금고 수신 말잔",
        stat_code="111Y007",
        item_code="1121000",
        expected_item_name="새마을금고",
        source_unit="십억원",
        unit="krw_trillion",
        multiplier=Decimal("0.001"),
        minimum=Decimal("0"),
        maximum=Decimal("999.9999"),
    ),
)

SERIES_BY_CODE = {spec.indicator_code: spec for spec in SERIES}


class IndicatorPoint(NamedTuple):
    indicator_code: str
    indicator_name: str
    value: Decimal
    unit: str
    source_effective_at: date
    source_locator: str


def spec_for(indicator_code: str) -> SeriesSpec:
    try:
        return SERIES_BY_CODE[indicator_code]
    except KeyError as error:
        raise ParseError(f"지원하지 않는 ECOS 예금시장 지표: {indicator_code}") from error


def _parse_month(value: object) -> date | None:
    text = str(value or "").strip()
    if len(text) != 6 or not text.isdigit():
        return None
    try:
        return datetime.strptime(text, "%Y%m").date()
    except ValueError:
        return None


def _schema_warnings(result: dict[str, Any]) -> list[str]:
    rows = result.get("row") or []
    if not rows:
        return ["시계열에 행이 없다"]
    missing = REQUIRED_FIELDS - set(rows[0])
    if missing:
        raise SchemaChangedError(f"ECOS 예금시장 응답 필수 필드 소실: {sorted(missing)}")
    return []


def parse(
    payload: dict[str, Any],
    *,
    indicator_code: str,
) -> tuple[list[IndicatorPoint], list[str]]:
    """검증된 ECOS 월별 계열 하나를 내부 지표 시점으로 변환한다."""
    spec = spec_for(indicator_code)

    if "RESULT" in payload:
        result = payload["RESULT"]
        raise ParseError(
            f"ECOS 오류 {result.get('CODE')}: {result.get('MESSAGE')}"
        )

    result = payload.get(RESULT_KEY)
    if not isinstance(result, dict):
        raise SchemaChangedError(f"응답에 {RESULT_KEY} 객체가 없다")

    warnings = _schema_warnings(result)
    points: list[IndicatorPoint] = []
    for row in result.get("row") or []:
        if str(row.get("STAT_CODE") or "") != spec.stat_code:
            warnings.append(f"다른 통계표가 섞였다: {row.get('STAT_CODE')}")
            continue
        if str(row.get("ITEM_CODE1") or "") != spec.item_code:
            warnings.append(f"다른 항목이 섞였다: {row.get('ITEM_CODE1')}")
            continue
        if str(row.get("ITEM_NAME1") or "").strip() != spec.expected_item_name:
            warnings.append(f"항목명이 바뀌었다: {row.get('ITEM_NAME1')!r}")
            continue
        if str(row.get("UNIT_NAME") or "").strip() != spec.source_unit:
            warnings.append(f"단위가 바뀌었다: {row.get('UNIT_NAME')!r}")
            continue

        when = _parse_month(row.get("TIME"))
        if when is None:
            warnings.append(f"월 시점을 읽지 못했다: {row.get('TIME')!r}")
            continue

        try:
            raw_value = Decimal(str(row.get("DATA_VALUE")).strip())
        except (InvalidOperation, AttributeError):
            warnings.append(f"값을 읽지 못했다: {row.get('DATA_VALUE')!r}")
            continue
        if not raw_value.is_finite():
            warnings.append(f"유한하지 않은 값이다: {row.get('DATA_VALUE')!r}")
            continue

        normalized = raw_value * spec.multiplier
        if not (spec.minimum <= normalized <= spec.maximum):
            warnings.append(
                f"{spec.indicator_code} 저장 범위를 벗어났다: "
                f"raw={raw_value} {spec.source_unit}, normalized={normalized} {spec.unit}"
            )
            continue

        points.append(
            IndicatorPoint(
                indicator_code=spec.indicator_code,
                indicator_name=spec.indicator_name,
                value=normalized,
                unit=spec.unit,
                source_effective_at=when,
                source_locator=f"{spec.stat_code}/{spec.item_code}/{row.get('TIME')}",
            )
        )

    return points, warnings
