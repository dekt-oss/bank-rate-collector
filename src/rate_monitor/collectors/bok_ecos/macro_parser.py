"""한국은행 ECOS 수신시장 거시지표 파서.

기존 7개 operational contract에 2026-08-27 D0 exact probe에서 실제 응답으로
검증한 수신시장 series를 추가한다. guessed stat/item은 persistence contract로
승격하지 않는다.

D0 evidence:
- discovery run 33053767652
- exact-series run 33054355763 / artifact 9638970120
- docs/source-recon/market-funding-d0-evidence-20260827.md

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
from rate_monitor.db.types import (
    QuantityOutOfRangeError,
    QuantityPrecisionError,
    quantize_quantity,
)

SOURCE_ID = "bok_ecos_macro"
CYCLE = "M"
RATE_UNIT = "percent"
BALANCE_UNIT = "trillion_krw"
BALANCE_SOURCE_UNIT = "십억원"
BILLION_PER_TRILLION = Decimal("1000")
MAX_RATE = Decimal("25")
NO_DATA_RESULT_CODES = frozenset({"INFO-200"})

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
    value_semantics: str
    balance_basis: str | None
    population: str


# 기존 Strategy consumer가 쓰는 두 은행 실현금리 series는 보존한다. 그 외에는
# D0 exact probe에서 stat/item/name/unit/data를 모두 확인한 contract만 추가한다.
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
        value_semantics="flow_weighted_avg_of_month",
        balance_basis=None,
        population="deposit_banks_all",
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
        value_semantics="flow_weighted_avg_of_month",
        balance_basis=None,
        population="deposit_banks_all",
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
        value_semantics="flow_weighted_avg_of_month",
        balance_basis=None,
        population="deposit_banks_all",
    ),
    SeriesContract(
        key="savings_bank_term_deposit_1y_rate",
        stat_code="121Y004",
        item_code="BEBBBE01",
        item_name="상호저축은행-정기예금(1년)",
        source_unit="연리%",
        indicator_code="bok_savings_bank_term_deposit_1y_rate",
        indicator_name="상호저축은행 1년 정기예금금리(신규취급액)",
        unit=RATE_UNIT,
        value_kind="rate",
        value_semantics="flow_weighted_avg_of_month",
        balance_basis=None,
        population="savings_banks_all",
    ),
    SeriesContract(
        key="credit_union_term_deposit_1y_rate",
        stat_code="121Y004",
        item_code="BEBBBG01",
        item_name="신협-정기예탁금(1년)",
        source_unit="연리%",
        indicator_code="bok_credit_union_term_deposit_1y_rate",
        indicator_name="신협 1년 정기예탁금금리(신규취급액)",
        unit=RATE_UNIT,
        value_kind="rate",
        value_semantics="flow_weighted_avg_of_month",
        balance_basis=None,
        population="credit_unions_all",
    ),
    SeriesContract(
        key="kfcc_term_deposit_1y_rate",
        stat_code="121Y004",
        item_code="BEBBA000",
        item_name="새마을금고-정기예탁금(1년)",
        source_unit="연리%",
        indicator_code="bok_kfcc_term_deposit_1y_rate",
        indicator_name="새마을금고 1년 정기예탁금금리(신규취급액)",
        unit=RATE_UNIT,
        value_kind="rate",
        value_semantics="flow_weighted_avg_of_month",
        balance_basis=None,
        population="kfcc_all",
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
        value_semantics="stock",
        balance_basis="eom",
        population="savings_banks_all",
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
        value_semantics="stock",
        balance_basis="eom",
        population="credit_unions_all",
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
        value_semantics="stock",
        balance_basis="eom",
        population="mutual_finance_broad_including_agri_fishery_forestry",
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
        value_semantics="stock",
        balance_basis="eom",
        population="kfcc_all",
    ),
    SeriesContract(
        key="bank_total_deposit_balance_eom",
        stat_code="104Y015",
        item_code="BDAA1",
        item_name="총예금",
        source_unit=BALANCE_SOURCE_UNIT,
        indicator_code="bok_bank_total_deposit_balance",
        indicator_name="예금은행 총예금(말잔)",
        unit=BALANCE_UNIT,
        value_kind="balance_billion_krw",
        value_semantics="stock",
        balance_basis="eom",
        population="deposit_banks_all",
    ),
    SeriesContract(
        key="bank_savings_deposit_balance_eom",
        stat_code="104Y015",
        item_code="BDAA3",
        item_name="저축성예금",
        source_unit=BALANCE_SOURCE_UNIT,
        indicator_code="bok_bank_savings_deposit_balance",
        indicator_name="예금은행 저축성예금(말잔)",
        unit=BALANCE_UNIT,
        value_kind="balance_billion_krw",
        value_semantics="stock",
        balance_basis="eom",
        population="deposit_banks_all",
    ),
    SeriesContract(
        key="bank_term_deposit_balance_eom",
        stat_code="104Y015",
        item_code="BDAA31",
        item_name="정기예금",
        source_unit=BALANCE_SOURCE_UNIT,
        indicator_code="bok_bank_term_deposit_balance",
        indicator_name="예금은행 정기예금(말잔)",
        unit=BALANCE_UNIT,
        value_kind="balance_billion_krw",
        value_semantics="stock",
        balance_basis="eom",
        population="deposit_banks_all",
    ),
    SeriesContract(
        key="bank_installment_savings_balance_eom",
        stat_code="104Y015",
        item_code="BDAA33",
        item_name="정기적금",
        source_unit=BALANCE_SOURCE_UNIT,
        indicator_code="bok_bank_installment_savings_balance",
        indicator_name="예금은행 정기적금(말잔)",
        unit=BALANCE_UNIT,
        value_kind="balance_billion_krw",
        value_semantics="stock",
        balance_basis="eom",
        population="deposit_banks_all",
    ),
    SeriesContract(
        key="bank_term_deposit_lt_6m_eom",
        stat_code="104Y010",
        item_code="1021000",
        item_name="6개월미만",
        source_unit=BALANCE_SOURCE_UNIT,
        indicator_code="bok_bank_term_deposit_lt_6m_balance",
        indicator_name="예금은행 정기예금 6개월 미만(말잔)",
        unit=BALANCE_UNIT,
        value_kind="balance_billion_krw",
        value_semantics="stock",
        balance_basis="eom",
        population="deposit_banks_all",
    ),
    SeriesContract(
        key="bank_term_deposit_6m_lt_1y_eom",
        stat_code="104Y010",
        item_code="1030000",
        item_name="6개월이상 1년미만",
        source_unit=BALANCE_SOURCE_UNIT,
        indicator_code="bok_bank_term_deposit_6m_lt_1y_balance",
        indicator_name="예금은행 정기예금 6개월 이상 1년 미만(말잔)",
        unit=BALANCE_UNIT,
        value_kind="balance_billion_krw",
        value_semantics="stock",
        balance_basis="eom",
        population="deposit_banks_all",
    ),
    SeriesContract(
        key="bank_term_deposit_1y_lt_2y_eom",
        stat_code="104Y010",
        item_code="1040000",
        item_name="1년이상 2년미만",
        source_unit=BALANCE_SOURCE_UNIT,
        indicator_code="bok_bank_term_deposit_1y_lt_2y_balance",
        indicator_name="예금은행 정기예금 1년 이상 2년 미만(말잔)",
        unit=BALANCE_UNIT,
        value_kind="balance_billion_krw",
        value_semantics="stock",
        balance_basis="eom",
        population="deposit_banks_all",
    ),
    SeriesContract(
        key="bank_term_deposit_2y_lt_3y_eom",
        stat_code="104Y010",
        item_code="1060000",
        item_name="2년이상 3년미만",
        source_unit=BALANCE_SOURCE_UNIT,
        indicator_code="bok_bank_term_deposit_2y_lt_3y_balance",
        indicator_name="예금은행 정기예금 2년 이상 3년 미만(말잔)",
        unit=BALANCE_UNIT,
        value_kind="balance_billion_krw",
        value_semantics="stock",
        balance_basis="eom",
        population="deposit_banks_all",
    ),
    SeriesContract(
        key="bank_term_deposit_3y_plus_eom",
        stat_code="104Y010",
        item_code="1070000",
        item_name="3년이상",
        source_unit=BALANCE_SOURCE_UNIT,
        indicator_code="bok_bank_term_deposit_3y_plus_balance",
        indicator_name="예금은행 정기예금 3년 이상(말잔)",
        unit=BALANCE_UNIT,
        value_kind="balance_billion_krw",
        value_semantics="stock",
        balance_basis="eom",
        population="deposit_banks_all",
    ),
)

CONTRACT_BY_INDICATOR = {contract.indicator_code: contract for contract in CONTRACTS}
CONTRACT_BY_STAT_ITEM = {
    (contract.stat_code, contract.item_code): contract for contract in CONTRACTS
}


def month_end(value: object) -> date | None:
    """ECOS 월 ``TIME``을 관측기간의 마지막 날로 표현한다."""
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
    except (InvalidOperation, AttributeError, ValueError):
        return None
    if not parsed.is_finite():
        return None
    if contract.value_kind == "rate":
        normalized = parsed if Decimal("0") <= parsed <= MAX_RATE else None
    elif contract.value_kind == "balance_billion_krw":
        normalized = parsed / BILLION_PER_TRILLION if parsed >= 0 else None
    else:
        normalized = None
    if normalized is None:
        return None
    try:
        return quantize_quantity(normalized)
    except (QuantityOutOfRangeError, QuantityPrecisionError):
        return None


def _count(result: dict[str, Any]) -> int:
    raw = result.get("list_total_count")
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise SchemaChangedError(f"ECOS list_total_count를 읽지 못했다: {raw!r}") from exc


def parse(
    payload: dict[str, Any], contract: SeriesContract
) -> tuple[list[IndicatorPoint], list[str]]:
    """검증된 ECOS 월 시계열 하나를 artifact 단위 fail-closed로 파싱한다."""
    if "RESULT" in payload:
        result = payload.get("RESULT") or {}
        code = str(result.get("CODE") or "")
        message = str(result.get("MESSAGE") or "")
        if code in NO_DATA_RESULT_CODES:
            return [], [f"{contract.indicator_code}: ECOS {code} no_data — {message}"]
        raise ParseError(f"ECOS 오류 {code}: {message}")

    result = payload.get("StatisticSearch")
    if not isinstance(result, dict):
        raise SchemaChangedError("응답에 StatisticSearch 객체가 없다")
    rows = result.get("row") or []
    if not isinstance(rows, list):
        raise SchemaChangedError("ECOS StatisticSearch.row가 배열이 아니다")
    total = _count(result)
    if total != len(rows):
        raise SchemaChangedError(
            "ECOS pagination/count 불일치: "
            f"list_total_count={total}, returned={len(rows)}"
        )
    if not rows:
        return [], [f"{contract.indicator_code}: 시계열에 행이 없다"]

    points: list[IndicatorPoint] = []
    seen_times: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise SchemaChangedError("ECOS row가 객체가 아니다")
        missing = REQUIRED_FIELDS - set(row)
        if missing:
            raise SchemaChangedError(f"ECOS 응답 필수 필드 소실: {sorted(missing)}")
        if str(row.get("STAT_CODE") or "") != contract.stat_code:
            raise SchemaChangedError(f"다른 통계표가 섞였다: {row.get('STAT_CODE')!r}")
        if str(row.get("ITEM_CODE1") or "") != contract.item_code:
            raise SchemaChangedError(f"다른 항목이 섞였다: {row.get('ITEM_CODE1')!r}")
        if str(row.get("ITEM_NAME1") or "") != contract.item_name:
            raise SchemaChangedError(f"항목명이 바뀌었다: {row.get('ITEM_NAME1')!r}")
        if str(row.get("UNIT_NAME") or "").strip() != contract.source_unit:
            raise SchemaChangedError(f"단위가 바뀌었다: {row.get('UNIT_NAME')!r}")

        raw_time = str(row.get("TIME") or "")
        if raw_time in seen_times:
            raise SchemaChangedError(f"같은 월이 중복됐다: {raw_time}")
        seen_times.add(raw_time)
        when = month_end(raw_time)
        if when is None:
            raise ParseError(f"월 시점을 읽지 못했다: {row.get('TIME')!r}")

        value = _value(row.get("DATA_VALUE"), contract)
        if value is None:
            raise ParseError(f"값 범위/정밀도를 읽지 못했다: {row.get('DATA_VALUE')!r}")

        points.append(
            IndicatorPoint(
                indicator_code=contract.indicator_code,
                indicator_name=contract.indicator_name,
                value=value,
                unit=contract.unit,
                source_effective_at=when,
                source_locator=f"{contract.stat_code}/{contract.item_code}/{raw_time}",
            )
        )

    return points, []
