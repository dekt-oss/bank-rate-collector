"""Pure total-assets parser for size-peer evidence diagnostics.

This module deliberately has no database/session dependency. It parses the
verified total-assets rows from the same Data.go finance payloads already used
for institution funding, validates source-reported aggregate hierarchy, and
returns institution/aggregate partitions for read-only evidence generation.

Persistence is intentionally out of scope until the size-peer Evidence Gate has
validated real production-source distributions and temporal alignment.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from rate_monitor.collectors.data_go_funding.aggregate_policy import (
    AGRI_COOP_CENTRAL_POPULATION_SCOPE,
    AggregateValidationError,
    partition_validated_agri_coop_rows,
)
from rate_monitor.db.types import quantize_quantity
from rate_monitor.domain.normalization import normalize_institution_name

MILLION = Decimal("1000000")
TOTAL_ASSETS_METRIC_CODE = "total_assets"
TOTAL_ASSETS_METRIC_NAME = "자산총계"
NORMALIZED_UNIT = "million_krw"
SOURCE_UNIT = "krw"

SAVINGS_BANK_SOURCE_ID = "data_go_savings_bank_funding"
SAVINGS_BANK_DATASET_ID = "15061316"
SAVINGS_BANK_SECTOR_TOTAL_KEY = "030350S"
SAVINGS_BANK_SECTOR_TOTAL_NAME = "저축은행"

AGRI_COOP_SOURCE_ID = "data_go_agri_coop_funding"
AGRI_COOP_DATASET_ID = "15061344"
AGRI_COOP_CENTRAL_KEY = "0212450"
AGRI_COOP_CENTRAL_NAME = "농협중앙회"


class TotalAssetsEvidenceError(ValueError):
    """Source payload does not satisfy the locked total-assets evidence contract."""


@dataclass(frozen=True)
class TotalAssetsSchema:
    source_id: str
    sector: str
    dataset_id: str
    code_field: str
    name_field: str
    amount_field: str
    total_code: str
    population_scope: str


SAVINGS_BANK_SCHEMA = TotalAssetsSchema(
    source_id=SAVINGS_BANK_SOURCE_ID,
    sector="savings_bank",
    dataset_id=SAVINGS_BANK_DATASET_ID,
    code_field="astSmryStfnpsAcitCd",
    name_field="astSmryStfnpsAcitCdNm",
    amount_field="astSmryStfnpsAcitCdAmt",
    total_code="A",
    population_scope="savings_banks_all_source_reported",
)

AGRI_COOP_SCHEMA = TotalAssetsSchema(
    source_id=AGRI_COOP_SOURCE_ID,
    sector="nh_local",
    dataset_id=AGRI_COOP_DATASET_ID,
    code_field="astSmryBlnshDcd",
    name_field="astSmryBlnshDcdNm",
    amount_field="astSmryBlnshClsfAmt",
    total_code="A",
    population_scope="agri_coops_local_units_source_reported",
)

SCHEMAS_BY_SOURCE_ID = {
    SAVINGS_BANK_SCHEMA.source_id: SAVINGS_BANK_SCHEMA,
    AGRI_COOP_SCHEMA.source_id: AGRI_COOP_SCHEMA,
}


@dataclass(frozen=True)
class TotalAssetsEvidencePoint:
    source_id: str
    sector: str
    dataset_id: str
    source_institution_key: str
    source_institution_name: str
    source_crno: str | None
    source_effective_month: str
    period_start: date
    period_end: date
    source_value_text: str
    value: Decimal
    population_scope: str
    source_locator: str


@dataclass(frozen=True)
class TotalAssetsEvidencePartition:
    source_id: str
    sector: str
    source_effective_month: str
    institution_rows: tuple[TotalAssetsEvidencePoint, ...]
    aggregate_rows: tuple[TotalAssetsEvidencePoint, ...]
    institution_total: Decimal
    aggregate_total: Decimal | None


def _parse_month(raw: object) -> tuple[str, date, date]:
    text = str(raw or "").strip()
    if len(text) != 6 or not text.isdigit():
        raise TotalAssetsEvidenceError(f"basYm 형식 오류: {raw!r}")
    year, month = int(text[:4]), int(text[4:])
    if not 1 <= month <= 12:
        raise TotalAssetsEvidenceError(f"basYm 월 오류: {raw!r}")
    last = calendar.monthrange(year, month)[1]
    return f"{year:04d}-{month:02d}", date(year, month, 1), date(year, month, last)


def _parse_krw(raw: object) -> tuple[str, Decimal]:
    text = str(raw if raw is not None else "").strip().replace(",", "")
    if not text or text.lower() in {"null", "none", "-"}:
        raise TotalAssetsEvidenceError(f"총자산 금액이 비어 있다: {raw!r}")
    try:
        krw = Decimal(text)
    except InvalidOperation as exc:
        raise TotalAssetsEvidenceError(f"총자산 금액 변환 실패: {raw!r}") from exc
    if not krw.is_finite() or krw < 0:
        raise TotalAssetsEvidenceError(f"총자산 금액은 비음수여야 한다: {raw!r}")
    if krw != krw.to_integral_value():
        raise TotalAssetsEvidenceError(
            f"Data.go source_unit=KRW 계약에서 소수 총자산을 받았다: {raw!r}"
        )
    return format(krw, "f"), quantize_quantity(krw / MILLION)


def parse_total_assets_rows(
    *,
    source_id: str,
    rows: list[dict[str, Any]],
    endpoint: str,
) -> list[TotalAssetsEvidencePoint]:
    """Parse exact `A / 자산총계` rows without dropping aggregate pseudo rows."""

    try:
        schema = SCHEMAS_BY_SOURCE_ID[source_id]
    except KeyError as exc:
        raise TotalAssetsEvidenceError(f"unsupported total-assets source: {source_id}") from exc

    by_key: dict[tuple[str, str], TotalAssetsEvidencePoint] = {}
    saw_asset_row = False
    for row in rows:
        if str(row.get(schema.code_field) or "").strip() != schema.total_code:
            continue

        account_name = str(row.get(schema.name_field) or "").replace(" ", "").strip()
        if account_name != TOTAL_ASSETS_METRIC_NAME:
            raise TotalAssetsEvidenceError(
                f"{schema.total_code} 코드명이 자산총계가 아니다: {account_name!r}"
            )
        saw_asset_row = True

        fnco_cd = str(row.get("fncoCd") or "").strip()
        fnco_nm = str(row.get("fncoNm") or "").strip()
        if not fnco_cd or not fnco_nm:
            raise TotalAssetsEvidenceError(
                f"총자산 row에 fncoCd/fncoNm이 없다: fncoCd={fnco_cd!r} fncoNm={fnco_nm!r}"
            )

        month, period_start, period_end = _parse_month(row.get("basYm"))
        source_text, value = _parse_krw(row.get(schema.amount_field))
        crno = str(row.get("crno") or "").strip() or None

        population_scope = schema.population_scope
        if schema.sector == "nh_local" and (
            fnco_cd == AGRI_COOP_CENTRAL_KEY
            or normalize_institution_name(fnco_nm) == AGRI_COOP_CENTRAL_NAME
        ):
            population_scope = AGRI_COOP_CENTRAL_POPULATION_SCOPE

        point = TotalAssetsEvidencePoint(
            source_id=schema.source_id,
            sector=schema.sector,
            dataset_id=schema.dataset_id,
            source_institution_key=fnco_cd,
            source_institution_name=fnco_nm,
            source_crno=crno,
            source_effective_month=month,
            period_start=period_start,
            period_end=period_end,
            source_value_text=source_text,
            value=value,
            population_scope=population_scope,
            source_locator=endpoint,
        )
        natural_key = (fnco_cd, month)
        prior = by_key.get(natural_key)
        if prior is not None and (
            prior.source_value_text != point.source_value_text
            or prior.source_crno != point.source_crno
        ):
            raise TotalAssetsEvidenceError(
                "같은 기관/기준월 총자산이 서로 다르다: "
                f"{fnco_cd} {month} {prior.source_value_text} != {point.source_value_text}"
            )
        by_key[natural_key] = point

    if rows and not saw_asset_row:
        raise TotalAssetsEvidenceError(
            f"{source_id}: 응답 row는 있으나 A/자산총계 contract row를 찾지 못했다"
        )

    return sorted(
        by_key.values(),
        key=lambda point: (point.source_effective_month, point.source_institution_key),
    )


def _partition_savings_bank_month(
    points: list[TotalAssetsEvidencePoint],
) -> tuple[list[TotalAssetsEvidencePoint], list[TotalAssetsEvidencePoint]]:
    aggregates = [
        point
        for point in points
        if point.source_institution_key == SAVINGS_BANK_SECTOR_TOTAL_KEY
    ]
    if not aggregates:
        return points, []
    if len(aggregates) != 1:
        raise TotalAssetsEvidenceError(
            "저축은행 총자산 sector-total row가 기준월에 하나가 아니다: "
            f"count={len(aggregates)}"
        )

    aggregate = aggregates[0]
    normalized_name = normalize_institution_name(aggregate.source_institution_name)
    if normalized_name != SAVINGS_BANK_SECTOR_TOTAL_NAME or aggregate.source_crno:
        raise TotalAssetsEvidenceError(
            "저축은행 총자산 sector-total identity 계약 불일치: "
            f"fncoCd={aggregate.source_institution_key!r} "
            f"fncoNm={aggregate.source_institution_name!r} crno={aggregate.source_crno!r}"
        )

    institutions = [
        point
        for point in points
        if point.source_institution_key != SAVINGS_BANK_SECTOR_TOTAL_KEY
    ]
    if not institutions:
        raise TotalAssetsEvidenceError("저축은행 총자산 sector-total 검증 대상 기관 row가 없다")

    institution_total = sum(
        (point.value for point in institutions),
        start=Decimal("0"),
    )
    if aggregate.value != institution_total:
        raise TotalAssetsEvidenceError(
            "저축은행 총자산 sector-total 합계 불일치: "
            f"aggregate={aggregate.value} institutions={institution_total} "
            f"institution_rows={len(institutions)}"
        )
    return institutions, aggregates


def partition_validated_total_assets(
    points: list[TotalAssetsEvidencePoint],
) -> list[TotalAssetsEvidencePartition]:
    """Validate aggregate hierarchy independently for each source/month."""

    grouped: dict[tuple[str, str], list[TotalAssetsEvidencePoint]] = {}
    for point in points:
        grouped.setdefault((point.source_id, point.source_effective_month), []).append(point)

    partitions: list[TotalAssetsEvidencePartition] = []
    for (source_id, month), month_points in sorted(grouped.items()):
        source_ids = {point.source_id for point in month_points}
        sectors = {point.sector for point in month_points}
        if source_ids != {source_id} or len(sectors) != 1:
            raise TotalAssetsEvidenceError(
                f"총자산 source/month partition 불일치: source={source_id} month={month}"
            )
        sector = next(iter(sectors))

        if source_id == SAVINGS_BANK_SOURCE_ID:
            institutions, aggregates = _partition_savings_bank_month(month_points)
        elif source_id == AGRI_COOP_SOURCE_ID:
            try:
                institutions, aggregates = partition_validated_agri_coop_rows(month_points)
            except AggregateValidationError as exc:
                raise TotalAssetsEvidenceError(str(exc)) from exc
        else:
            raise TotalAssetsEvidenceError(f"unsupported total-assets source: {source_id}")

        institution_total = sum(
            (point.value for point in institutions),
            start=Decimal("0"),
        )
        aggregate_total = (
            sum((point.value for point in aggregates), start=Decimal("0"))
            if aggregates
            else None
        )
        partitions.append(
            TotalAssetsEvidencePartition(
                source_id=source_id,
                sector=sector,
                source_effective_month=month,
                institution_rows=tuple(
                    sorted(institutions, key=lambda point: point.source_institution_key)
                ),
                aggregate_rows=tuple(
                    sorted(aggregates, key=lambda point: point.source_institution_key)
                ),
                institution_total=institution_total,
                aggregate_total=aggregate_total,
            )
        )

    return partitions
