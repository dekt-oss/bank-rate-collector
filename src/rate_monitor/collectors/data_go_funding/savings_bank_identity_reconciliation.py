"""Latest-month savings-bank funding identity reconciliation.

The production evidence for this remediation is the latest Data.go savings-bank
population, so this module deliberately does not rewrite historical months.  It
only fills identity on the latest active month using the strict FSB+Finlife
exact-code consensus gate.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, select

from rate_monitor.collectors.data_go_funding.savings_bank_identity import (
    MAPPED_DUAL_SOURCE_STATUS,
    SAVINGS_BANK_SECTOR_TOTAL_KEY,
    resolve_savings_bank_dual_source_consensus,
)
from rate_monitor.db.institution_funding_models import InstitutionFundingObservation
from rate_monitor.db.session import create_db_engine, make_session_factory, session_scope

FUNDING_SOURCE_ID = "data_go_savings_bank_funding"


class SavingsBankFundingIdentityConflict(RuntimeError):
    """An existing mapped observation disagrees with current dual-source consensus."""


@dataclass(frozen=True)
class SavingsBankFundingIdentityReconciliationResult:
    latest_month: str | None
    scanned: int
    eligible_unmapped: int
    mapped: int
    unchanged_mapped: int
    no_consensus: int
    excluded_aggregate: int


def reconcile_latest_savings_bank_funding_identity(
    db_path: Path,
) -> SavingsBankFundingIdentityReconciliationResult:
    """Fill identity only for the latest active savings-bank funding month.

    The function never changes amount, source month, revision, validity, hashes
    or raw provenance.  Existing mapped rows are immutable; if strict consensus
    exists and points elsewhere, the transaction fails instead of rewriting the
    canonical institution.
    """
    engine = create_db_engine(db_path)
    factory = make_session_factory(engine)

    latest_month: str | None = None
    scanned = eligible_unmapped = mapped = unchanged_mapped = 0
    no_consensus = excluded_aggregate = 0

    with session_scope(factory) as session:
        latest_month = session.scalar(
            select(func.max(InstitutionFundingObservation.source_effective_month)).where(
                InstitutionFundingObservation.source_id == FUNDING_SOURCE_ID,
                InstitutionFundingObservation.sector == "savings_bank",
                InstitutionFundingObservation.valid_to.is_(None),
            )
        )
        if latest_month is None:
            return SavingsBankFundingIdentityReconciliationResult(
                latest_month=None,
                scanned=0,
                eligible_unmapped=0,
                mapped=0,
                unchanged_mapped=0,
                no_consensus=0,
                excluded_aggregate=0,
            )

        observations = list(
            session.scalars(
                select(InstitutionFundingObservation)
                .where(
                    InstitutionFundingObservation.source_id == FUNDING_SOURCE_ID,
                    InstitutionFundingObservation.sector == "savings_bank",
                    InstitutionFundingObservation.source_effective_month == latest_month,
                    InstitutionFundingObservation.valid_to.is_(None),
                )
                .order_by(InstitutionFundingObservation.source_institution_key)
            )
        )
        scanned = len(observations)

        for observation in observations:
            if observation.source_institution_key == SAVINGS_BANK_SECTOR_TOTAL_KEY:
                excluded_aggregate += 1
                continue

            consensus = resolve_savings_bank_dual_source_consensus(
                session,
                source_institution_key=observation.source_institution_key,
                source_institution_name=observation.source_institution_name,
                source_crno=observation.source_crno,
            )

            if observation.institution_id is not None:
                if (
                    consensus.institution_id is not None
                    and observation.institution_id != consensus.institution_id
                ):
                    raise SavingsBankFundingIdentityConflict(
                        "savings-bank funding identity conflict: "
                        f"source_key={observation.source_institution_key} "
                        f"month={observation.source_effective_month} "
                        f"existing={observation.institution_id} "
                        f"consensus={consensus.institution_id}"
                    )
                unchanged_mapped += 1
                continue

            eligible_unmapped += 1
            if consensus.institution_id is None:
                no_consensus += 1
                continue

            observation.institution_id = consensus.institution_id
            observation.identity_status = MAPPED_DUAL_SOURCE_STATUS
            mapped += 1

    return SavingsBankFundingIdentityReconciliationResult(
        latest_month=str(latest_month),
        scanned=scanned,
        eligible_unmapped=eligible_unmapped,
        mapped=mapped,
        unchanged_mapped=unchanged_mapped,
        no_consensus=no_consensus,
        excluded_aggregate=excluded_aggregate,
    )
