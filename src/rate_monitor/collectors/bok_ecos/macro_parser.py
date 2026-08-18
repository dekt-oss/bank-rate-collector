"""한국은행 ECOS 수신시장 거시지표 파서 (Stage E0-3).

이 파일의 통계코드는 추정값이 아니다. 2026-08-18 trusted-main 정찰/실조회로
확인했다.

- discovery run 32135388199 / artifact 9323770229
- exact-series run 32136553896 / artifact 9324218955
- docs/source-recon/strategy-external-indicators-e0-discovery.md

기존 ``bok_ecos`` 기준금리 파서는 건드리지 않는다. 거시지표 하나의 계약이
바뀌어도 기준금리 수집이 같이 깨지지 않도록 별도 operational source가 쓴다.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from rate_monitor.collectors.base import ParseError, SchemaChangedError
from rate_monitor.collectors.bok_ecos.parser import IndicatorPoint

SOURCE_ID = "bok_ecos_macro"
CYCLE = "M"
RATE_UNIT = "percent"
BALANCE_UNIT = "trillion_krw"
BALANCE_SOURCE_UNIT = "십억원"
BILLION_PER_TRILLION = Decimal("1000")
MAX_RATE = Decimal("25")
MAX_STORED_VALUE = Decimal("999.9999")

REQUIRED_FIELDS = frozenset(
    {"STAT_CODE", "ITEM_CODE1", "ITEM_NAME1", "TIME", "DATA_VALUE", "UNIT_NAME"}
)


@dataclass(frozen=True)
class SeriesContract:
    key: str
    stat_code: str
    item_code: str
    item_name: str
    source_unit: str
    indicator_code: str
    indicator_name: str
    unit: str
    value_kind: str


CONTRACTS = (
    SeriesContract(
        key="bank_savings_deposit_rate",
        stat_code="121Y002",
        item_code="BEABAA2",
        item_name="저축성수신",
        source_unit="연%",
        indicator_code="bok_bank_savings_deposit_rate",
        indicator_name="예금은행 저축성수신금리(신규취급액)",
        unit=RATE_UNIT,
        value_kind="rate",
    ),
    SeriesContract(
        key="bank_pure_savings_deposit_rate",
        stat_code="121Y002",
        item_code="BEABAA21",
        item_name="순수저축성예금 1)",
        source_unit="연리%",
        indicator_code="bok_bank_pure_savings_deposit_rate",
        indicator_name="예금은행 순수저축성예금금리(신규취급액)",
        unit=RATE_UNIT,
        value_kind="rate",
    ),
    SeriesContract(
        key="bank_term_deposit_1y_rate",
        stat_code="121Y002",
        item_code="BEABAA2118",
        item_name="정기예금(1년)",
        source_unit="연리%",
        indicator_code="bok_bank_term_deposit_1y_rate",
        indicator_name="예금은행 1년 정기예금금리(신규취급액)",
        unit=RATE_UNIT,
        value_kind="rate",
    ),
    SeriesContract(
        key="savings_bank_deposit_balance",
        stat_code="111Y007",
        item_code="1120600",
        item_name="상호저축은행",
        source_unit=BALANCE_SOURCE_UNIT,
        indicator_code="bok_savings_bank_deposit_balance",
        indicator_name="상호저축은행 수신잔액(말잔)",
        unit=BALANCE_UNIT,
        value_kind="balance_billion_krw",
    ),
    SeriesContract(
        key="credit_union_deposit_balance",
        stat_code="111Y007",
        item_code="1120700",
        item_name="신용협동조합",
        source_unit=BALANCE_SOURCE_UNIT,
        indicator_code="bok_credit_union_deposit_balance",
        indicator_name="신용협동조합 수신잔액(말잔)",
        unit=BALANCE_UNIT,
        value_kind="balance_billion_krw",
    ),
    SeriesContract(
        key="broad_mutual_finance_deposit_balance",
        stat_code="111Y007",
        item_code="1120800",
        item_name="상호금융",
        source_unit=BALANCE_SOURCE_UNIT,
        indicator_code="bok_broad_mutual_finance_deposit_balance",
        indicator_name="광의 상호금융 수신잔액(말잔)",
        unit=BALANCE_UNIT,
        value_kind="balance_billion_krw",
    ),
    SeriesContract(
        key="kfcc_deposit_balance",
        stat_code="111Y007",
        item_code="1121000",
        item_name="새마을금고",
        source_unit=BALANCE_SOURCE_UNIT,
        indicator_code="bok_kfcc_deposit_balance",
        indicator_name="새마을금고 수신잔액(말잔)",
        unit=BALANCE_UNIT,
        value_kind="balance_billion_krw",
    ),
)

CONTRACT_BY_INDICATOR = {contract.indicator_code: contract for contract in CONTRACTS}
CONTRACT_BY_ITEM = {contract.item_code: contract for contract in CONTRACTS}


def month_end(value: object) -> date | None:
    """ECOS 월 ``TIME``을 관측기간의 마지막 날로 표현한다.

    ECOS가 주는 원본은 YYYYMM뿐이다. 월별 평균 금리와 월말 잔액을 모델에서
    같은 월 단위로 정렬하기 위해 period-end date를 쓴다. 원래 YYYYMM은
    ``source_locator``에 그대로 남긴다.
    """
    text = str(value or "").strip()
    if len(text) != 6 or not text.isdigit():
        return None
    year, month = int(text[:4]), int(text[4:])
    if not 1 <= month <= 12:
        return None
    try:
        day = calendar.monthrange(year, month)[1]
        return date(year, month, day)
    except (ValueError, calendar.IllegalMonthError):
        return None


def _value(raw: object, contract: SeriesContract) -> Decimal | None:
    try:
        parsed = Decimal(str(raw).strip())
    except (InvalidOperation, AttributeError):
        return None
    if contract.value_kind == "rate":
        return parsed if Decimal("0") <= parsed <= MAX_RATE else None
    if contract.value_kind == "balance_billion_krw":
        converted = parsed / BILLION_PER_TRILLION
        return converted if Decimal("0") <= converted <= MAX_STORED_VALUE else None
    return None


def parse(
    payload: dict[str, Any], contract: SeriesContract
) -> tuple[list[IndicatorPoint], list[str]]:
    """검증된 ECOS 월 시계열 하나를 ``IndicatorPoint`` 목록으로 바꾼다."""
    if "RESULT" in payload:
        result = payload["RESULT"]
        raise ParseError(f"ECOS 오류 {result.get('CODE')}: {result.get('MESSAGE')}")

    result = payload.get("StatisticSearch")
    if not isinstance(result, dict):
        raise SchemaChangedError("응답에 StatisticSearch 객체가 없다")
    rows = result.get("row") or []
    if not rows:
        return [], [f"{contract.indicator_code}: 시계열에 행이 없다"]

    missing = REQUIRED_FIELDS - set(rows[0])
    if missing:
        raise SchemaChangedError(f"ECOS 응답 필수 필드 소실: {sorted(missing)}")

    warnings: list[str] = []
    points: list[IndicatorPoint] = []
    for row in rows:
        if str(row.get("STAT_CODE") or "") != contract.stat_code:
            warnings.append(f"다른 통계표가 섞였다: {row.get('STAT_CODE')}")
            continue
        if str(row.get("ITEM_CODE1") or "") != contract.item_code:
            warnings.append(f"다른 항목이 섞였다: {row.get('ITEM_CODE1')}")
            continue
        if str(row.get("ITEM_NAME1") or "") != contract.item_name:
            warnings.append(f"항목명이 바뀌었다: {row.get('ITEM_NAME1')!r}")
            continue
        if str(row.get("UNIT_NAME") or "").strip() != contract.source_unit:
            warnings.append(f"단위가 바뀌었다: {row.get('UNIT_NAME')!r}")
            continue

        when = month_end(row.get("TIME"))
        if when is None:
            warnings.append(f"월 시점을 읽지 못했다: {row.get('TIME')!r}")
            continue

        value = _value(row.get("DATA_VALUE"), contract)
        if value is None:
            warnings.append(f"값 범위/형식을 읽지 못했다: {row.get('DATA_VALUE')!r}")
            continue

        points.append(
            IndicatorPoint(
                indicator_code=contract.indicator_code,
                indicator_name=contract.indicator_name,
                value=value,
                unit=contract.unit,
                source_effective_at=when,
                source_locator=(
                    f"{contract.stat_code}/{contract.item_code}/{row.get('TIME')}"
                ),
            )
        )

    return points, warnings
