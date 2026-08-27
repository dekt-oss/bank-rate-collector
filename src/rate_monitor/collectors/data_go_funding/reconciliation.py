"""기관별 Data.go 예수부채 ↔ ECOS 업권 수신잔액 reconciliation.

두 통계는 회계/통계 분류가 완전히 동일하다고 가정하지 않는다.
- 저축은행·신협: 동일 기준월에 합계 차이를 QC band로 측정한다.
- 농·축협: Data.go 단위 농·축협은 ECOS 광의 상호금융의 부분모집단이므로
  equality가 아니라 coverage ratio만 계산한다.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select

from rate_monitor.db import models as m
from rate_monitor.db.institution_funding_models import InstitutionFundingObservation
from rate_monitor.db.session import create_db_engine, make_session_factory, session_scope

TRILLION_TO_MILLION = Decimal("1000000")
ALIGN_MAX_PCT = Decimal("2")
REVIEW_MAX_PCT = Decimal("5")

ECOS_CODE = {
    "savings_bank": "bok_savings_bank_deposit_balance",
    "cu": "bok_credit_union_deposit_balance",
    "nh_local": "bok_broad_mutual_finance_deposit_balance",
}


def _band(pct: Decimal) -> str:
    if pct <= ALIGN_MAX_PCT:
        return "aligned"
    if pct <= REVIEW_MAX_PCT:
        return "review"
    return "contract_mismatch_review"


def _month(date_value: Any) -> str | None:
    if date_value is None:
        return None
    return f"{date_value.year:04d}-{date_value.month:02d}"


def build_report(db_path: Path) -> dict[str, Any]:
    engine = create_db_engine(db_path)
    factory = make_session_factory(engine)
    with session_scope(factory) as session:
        rows = list(
            session.scalars(
                select(InstitutionFundingObservation).where(
                    InstitutionFundingObservation.valid_to.is_(None)
                )
            )
        )
        ecos_rows = list(
            session.scalars(
                select(m.MarketIndicator).where(
                    m.MarketIndicator.indicator_code.in_(tuple(ECOS_CODE.values()))
                )
            )
        )

    coverage: dict[tuple[str, str], dict[str, Any]] = {}
    grouped: dict[tuple[str, str], list[InstitutionFundingObservation]] = defaultdict(list)
    for row in rows:
        if row.population_scope == "agri_coop_central_excluded_from_local_sum":
            continue
        grouped[(row.sector, row.source_effective_month)].append(row)

    for (sector, month), items in sorted(grouped.items()):
        coverage[(sector, month)] = {
            "sector": sector,
            "month": month,
            "institution_count": len({row.source_institution_key for row in items}),
            "mapped_count": len(
                {
                    row.source_institution_key
                    for row in items
                    if row.institution_id is not None
                }
            ),
            "unmapped_count": len(
                {
                    row.source_institution_key
                    for row in items
                    if row.institution_id is None
                }
            ),
            "institution_sum_million_krw": str(sum((row.value for row in items), Decimal("0"))),
        }

    ecos_by_key: dict[tuple[str, str], Decimal] = {}
    reverse = {indicator: sector for sector, indicator in ECOS_CODE.items()}
    for row in ecos_rows:
        sector = reverse.get(row.indicator_code)
        month = _month(row.source_effective_at)
        if sector and month and row.unit == "trillion_krw":
            ecos_by_key[(sector, month)] = row.value * TRILLION_TO_MILLION

    reconciliations: list[dict[str, Any]] = []
    for key, item in coverage.items():
        sector, month = key
        sector_total = ecos_by_key.get(key)
        institution_sum = Decimal(item["institution_sum_million_krw"])
        base = {
            "sector": sector,
            "month": month,
            "institution_count": item["institution_count"],
            "institution_sum_million_krw": str(institution_sum),
            "ecos_indicator_code": ECOS_CODE[sector],
        }
        if sector_total is None:
            reconciliations.append(
                {
                    **base,
                    "status": "no_matching_ecos_period",
                    "sector_total_million_krw": None,
                    "difference_million_krw": None,
                    "difference_pct": None,
                    "coverage_ratio": None,
                }
            )
            continue

        difference = institution_sum - sector_total
        if sector == "nh_local":
            ratio = institution_sum / sector_total if sector_total != 0 else Decimal("0")
            reconciliations.append(
                {
                    **base,
                    "status": "coverage_only_not_equality",
                    "sector_total_million_krw": str(sector_total),
                    "difference_million_krw": str(difference),
                    "difference_pct": None,
                    "coverage_ratio": str(ratio),
                    "basis_note": (
                        "Data.go 단위 농·축협 합계는 농협중앙회를 제외한다. "
                        "ECOS 광의 상호금융은 농·수·산림계 상호금융을 포함하는 더 넓은 모집단이라 "
                        "동일성 tolerance를 적용하지 않는다."
                    ),
                }
            )
            continue

        pct = (
            abs(difference) / sector_total * Decimal("100")
            if sector_total != 0
            else Decimal("0")
        )
        reconciliations.append(
            {
                **base,
                "status": _band(pct),
                "sector_total_million_krw": str(sector_total),
                "difference_million_krw": str(difference),
                "difference_pct": str(pct),
                "coverage_ratio": str(institution_sum / sector_total) if sector_total != 0 else None,
                "basis_note": (
                    "Data.go 예수부채는 금융회사 재무상태표 계정, ECOS 수신잔액은 "
                    "금융통계 업권 합계다. 2% 이하는 정합, 2~5%는 review, 5% 초과는 "
                    "contract/population mismatch review로 분류하되 수집값 자체를 폐기하지 않는다."
                ),
            }
        )

    central = [
        row
        for row in rows
        if row.population_scope == "agri_coop_central_excluded_from_local_sum"
    ]
    return {
        "contract": {
            "normalized_unit": "million_krw",
            "source_unit": "krw",
            "data_go_basis": "reported_period_end",
            "reconciliation_policy": {
                "savings_bank_credit_union_aligned_max_pct": "2",
                "review_max_pct": "5",
                "over_5_pct": "contract_mismatch_review",
                "agri_coop": "coverage_only_no_equality_tolerance",
            },
            "identity_policy": {
                "primary_key": "FSS fncoCd",
                "secondary_evidence": "crno",
                "automatic_cross_source_merge": "exact same sector+fncoCd+normalized name only",
                "name_only_merge": False,
                "legal_effective_dates": (
                    "source_entity_links.valid_from/valid_to는 공식 합병·폐업·조직전환 "
                    "효력일 증거가 있을 때만 채운다. basYm first-seen을 법적 효력일로 대체하지 않는다."
                ),
            },
        },
        "coverage": list(coverage.values()),
        "reconciliation": reconciliations,
        "agri_central_rows_excluded": len(central),
    }
