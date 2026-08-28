"""Guards for Data.go funding rows that are not institution observations.

The savings-bank summary table includes a source-reported sector total row
(``fncoCd=030350S``, ``fncoNm=저축은행``) alongside individual institutions.
Persisting that row as an institution doubles sector reconciliation totals.
Raw evidence remains untouched; after validating that the aggregate equals the
sum of active institution rows for the same reporting month, this module
retires only the aggregate observation via the existing ``valid_to`` history
contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from rate_monitor.collectors.data_go_funding.collector import (
    TOTAL_METRIC_CODE,
    FundingContractError,
)
from rate_monitor.db.institution_funding_models import InstitutionFundingObservation
from rate_monitor.db.session import create_db_engine, make_session_factory, session_scope
from rate_monitor.domain.normalization import normalize_institution_name

SAVINGS_BANK_SOURCE_ID = "data_go_savings_bank_funding"
SAVINGS_BANK_SECTOR_TOTAL_KEY = "030350S"
SAVINGS_BANK_SECTOR_TOTAL_NAME = "저축은행"


@dataclass(frozen=True)
class AggregateGuardResult:
    checked_months: int
    retired_observations: int


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def retire_validated_savings_bank_sector_totals(
    db_path: Path,
    *,
    now: datetime | None = None,
) -> AggregateGuardResult:
    """Retire active source-total pseudo rows only after exact sum validation.

    The operation is idempotent: retired rows are historical evidence and a
    second call sees no active aggregate rows. A changed aggregate identity or
    any value mismatch fails closed and leaves the transaction unchanged.
    """
    stamp = now or _now()
    engine = create_db_engine(db_path)
    factory = make_session_factory(engine)

    with session_scope(factory) as session:
        aggregates = list(
            session.scalars(
                select(InstitutionFundingObservation)
                .where(
                    InstitutionFundingObservation.source_id
                    == SAVINGS_BANK_SOURCE_ID,
                    InstitutionFundingObservation.source_institution_key
                    == SAVINGS_BANK_SECTOR_TOTAL_KEY,
                    InstitutionFundingObservation.metric_code == TOTAL_METRIC_CODE,
                    InstitutionFundingObservation.valid_to.is_(None),
                )
                .order_by(InstitutionFundingObservation.source_effective_month)
            )
        )

        for aggregate in aggregates:
            normalized_name = normalize_institution_name(
                aggregate.source_institution_name
            )
            crno = str(aggregate.source_crno or "").strip()
            if normalized_name != SAVINGS_BANK_SECTOR_TOTAL_NAME or crno:
                raise FundingContractError(
                    "저축은행 sector-total identity 계약 불일치: "
                    f"fncoCd={aggregate.source_institution_key!r} "
                    f"fncoNm={aggregate.source_institution_name!r} "
                    f"crno={aggregate.source_crno!r}"
                )

            peers = list(
                session.scalars(
                    select(InstitutionFundingObservation).where(
                        InstitutionFundingObservation.source_id
                        == SAVINGS_BANK_SOURCE_ID,
                        InstitutionFundingObservation.metric_code
                        == TOTAL_METRIC_CODE,
                        InstitutionFundingObservation.source_effective_month
                        == aggregate.source_effective_month,
                        InstitutionFundingObservation.source_institution_key
                        != SAVINGS_BANK_SECTOR_TOTAL_KEY,
                        InstitutionFundingObservation.valid_to.is_(None),
                    )
                )
            )
            if not peers:
                raise FundingContractError(
                    "저축은행 sector-total 검증 대상 기관 row가 없다: "
                    f"month={aggregate.source_effective_month}"
                )

            institution_total = sum(
                (Decimal(peer.value) for peer in peers),
                start=Decimal("0"),
            )
            aggregate_value = Decimal(aggregate.value)
            if aggregate_value != institution_total:
                raise FundingContractError(
                    "저축은행 sector-total 합계 불일치: "
                    f"month={aggregate.source_effective_month} "
                    f"aggregate={aggregate_value} institutions={institution_total} "
                    f"institution_rows={len(peers)}"
                )

        for aggregate in aggregates:
            aggregate.valid_to = stamp

    return AggregateGuardResult(
        checked_months=len(aggregates),
        retired_observations=len(aggregates),
    )
