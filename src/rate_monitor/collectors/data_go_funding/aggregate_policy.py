"""Pure validation policy for Data.go funding aggregate pseudo rows.

The Data.go agricultural-cooperative finance table mixes local-institution rows
with source-reported regional/sector totals. This module validates the observed
hierarchy before callers exclude aggregate rows from institution persistence or
retire legacy active rows. It intentionally has no DB or collector dependency.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol

AGRI_COOP_INSTITUTION_KEY_PREFIX = "0010027"
AGRI_COOP_LEGACY_TOTALS = {"032120S": "농업협동조합"}
AGRI_COOP_SECTOR_TOTALS = {"030801S": "농협단위조합"}
AGRI_COOP_REGION_TOTALS = {
    "0321301S": "농협(서울)",
    "0321302S": "농협(부산)",
    "0321303S": "농협(대구)",
    "0321304S": "농협(인천)",
    "0321305S": "농협(광주)",
    "0321306S": "농협(대전)",
    "0321307S": "농협(울산)",
    "0321308S": "농협(경기)",
    "0321309S": "농협(강원)",
    "0321310S": "농협(충북)",
    "0321311S": "농협(충남)",
    "0321312S": "농협(전북)",
    "0321313S": "농협(전남)",
    "0321314S": "농협(경북)",
    "0321315S": "농협(경남)",
    "0321316S": "농협(제주)",
}
AGRI_COOP_AGGREGATE_KEYS = frozenset(
    AGRI_COOP_LEGACY_TOTALS | AGRI_COOP_SECTOR_TOTALS | AGRI_COOP_REGION_TOTALS
)
AGRI_COOP_CENTRAL_POPULATION_SCOPE = "agri_coop_central_excluded_from_local_sum"


class AggregateValidationError(ValueError):
    """Observed aggregate hierarchy no longer matches the verified contract."""


class FundingAggregateRow(Protocol):
    source_institution_key: str
    source_institution_name: str
    source_crno: str | None
    source_effective_month: str
    value: Decimal
    population_scope: str


def is_agri_coop_institution_key(key: str) -> bool:
    """Return whether a source key matches the verified local-coop key shape."""
    return (
        len(key) == 13
        and key.startswith(AGRI_COOP_INSTITUTION_KEY_PREFIX)
        and key[len(AGRI_COOP_INSTITUTION_KEY_PREFIX) :].isdigit()
    )


def _validate_identity(row: FundingAggregateRow, expected_name: str) -> None:
    crno = str(row.source_crno or "").strip()
    if row.source_institution_name != expected_name or crno:
        raise AggregateValidationError(
            "농·축협 aggregate identity 계약 불일치: "
            f"month={row.source_effective_month} "
            f"fncoCd={row.source_institution_key!r} "
            f"fncoNm={row.source_institution_name!r} crno={row.source_crno!r}"
        )


def partition_validated_agri_coop_rows[RowT: FundingAggregateRow](
    rows: list[RowT],
) -> tuple[list[RowT], list[RowT]]:
    """Return (institution_rows, aggregate_rows) after exact hierarchy checks.

    Verified runtime shapes:

    * 2020 legacy: one ``032120S`` total equals the sum of real local coops.
    * 2021+ current: 16 regional totals sum to the real local-coop total, and
      ``030801S`` equals real total + regional total (therefore exactly 2x the
      real total).

    If an aggregate-looking row appears but the full observed contract is not
    satisfied, fail closed instead of guessing or silently dropping it.
    """
    if not rows:
        return [], []

    months = {row.source_effective_month for row in rows}
    if len(months) != 1:
        raise AggregateValidationError(
            f"농·축협 aggregate 검증은 한 기준월씩 수행해야 한다: months={sorted(months)}"
        )
    month = next(iter(months))

    unknown_aggregate_like = [
        row
        for row in rows
        if row.source_institution_key.endswith("S")
        and row.source_institution_key not in AGRI_COOP_AGGREGATE_KEYS
    ]
    if unknown_aggregate_like:
        keys = sorted({row.source_institution_key for row in unknown_aggregate_like})
        raise AggregateValidationError(
            f"농·축협 미확정 aggregate key 발견: month={month} keys={keys}"
        )

    aggregates = [
        row for row in rows if row.source_institution_key in AGRI_COOP_AGGREGATE_KEYS
    ]
    if not aggregates:
        return rows, []

    institutions = [
        row for row in rows if is_agri_coop_institution_key(row.source_institution_key)
    ]
    central = [
        row
        for row in rows
        if row.population_scope == AGRI_COOP_CENTRAL_POPULATION_SCOPE
    ]
    recognized_ids = {id(row) for row in institutions + central + aggregates}
    unknown = [row for row in rows if id(row) not in recognized_ids]
    if unknown:
        keys = sorted({row.source_institution_key for row in unknown})
        raise AggregateValidationError(
            f"농·축협 aggregate 동반 시 미확정 institution key 발견: month={month} keys={keys}"
        )
    if not institutions:
        raise AggregateValidationError(
            f"농·축협 aggregate 검증 대상 실제 기관 row가 없다: month={month}"
        )

    institution_total = sum(
        (Decimal(row.value) for row in institutions),
        start=Decimal("0"),
    )
    by_key = {row.source_institution_key: row for row in aggregates}
    if len(by_key) != len(aggregates):
        raise AggregateValidationError(
            f"농·축협 aggregate key 중복: month={month}"
        )

    legacy_keys = set(by_key) & set(AGRI_COOP_LEGACY_TOTALS)
    current_keys = set(by_key) & (
        set(AGRI_COOP_SECTOR_TOTALS) | set(AGRI_COOP_REGION_TOTALS)
    )

    if legacy_keys:
        expected = set(AGRI_COOP_LEGACY_TOTALS)
        if set(by_key) != expected or current_keys:
            raise AggregateValidationError(
                "농·축협 legacy aggregate hierarchy 일부/혼합 응답: "
                f"month={month} keys={sorted(by_key)}"
            )
        row = by_key["032120S"]
        _validate_identity(row, AGRI_COOP_LEGACY_TOTALS["032120S"])
        if Decimal(row.value) != institution_total:
            raise AggregateValidationError(
                "농·축협 legacy total 합계 불일치: "
                f"month={month} aggregate={row.value} institutions={institution_total} "
                f"institution_rows={len(institutions)}"
            )
        return institutions + central, aggregates

    expected_current = set(AGRI_COOP_SECTOR_TOTALS) | set(AGRI_COOP_REGION_TOTALS)
    if set(by_key) != expected_current:
        missing = sorted(expected_current - set(by_key))
        extra = sorted(set(by_key) - expected_current)
        raise AggregateValidationError(
            "농·축협 current aggregate hierarchy 불완전: "
            f"month={month} missing={missing} extra={extra}"
        )

    for key, expected_name in AGRI_COOP_REGION_TOTALS.items():
        _validate_identity(by_key[key], expected_name)
    for key, expected_name in AGRI_COOP_SECTOR_TOTALS.items():
        _validate_identity(by_key[key], expected_name)

    regional_total = sum(
        (Decimal(by_key[key].value) for key in AGRI_COOP_REGION_TOTALS),
        start=Decimal("0"),
    )
    sector_row = by_key["030801S"]
    sector_total = Decimal(sector_row.value)

    if regional_total != institution_total:
        raise AggregateValidationError(
            "농·축협 regional total 합계 불일치: "
            f"month={month} regions={regional_total} institutions={institution_total} "
            f"institution_rows={len(institutions)}"
        )
    if sector_total != institution_total + regional_total:
        raise AggregateValidationError(
            "농·축협 sector total hierarchy 불일치: "
            f"month={month} sector={sector_total} institutions={institution_total} "
            f"regions={regional_total}"
        )

    return institutions + central, aggregates
