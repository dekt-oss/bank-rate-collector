"""DB adapter for funding Direct Peer populations."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from rate_monitor.db.institution_funding_models import InstitutionFundingObservation
from rate_monitor.db.models import Institution
from rate_monitor.db.session import create_db_engine, make_session_factory, session_scope
from rate_monitor.services.institution_funding_peer_service import FundingPeerPoint
from rate_monitor.services.institution_funding_read_model_db import (
    FUNDING_METRIC_CODE,
    VERIFIED_IDENTITY_STATUSES,
)


def load_funding_peer_points(
    db_path: Path,
    *,
    sector: str,
    analysis_month: str,
) -> list[FundingPeerPoint]:
    """Load one exact active funding point per mapped institution for a month.

    Region fields come from the canonical institution row. Unknown geography is
    preserved as ``None``; it may participate in nationwide same-sector peers
    but never in a narrower region population.
    """
    engine = create_db_engine(db_path)
    factory = make_session_factory(engine)
    with session_scope(factory) as session:
        rows = list(
            session.execute(
                select(
                    InstitutionFundingObservation.institution_id,
                    InstitutionFundingObservation.sector,
                    InstitutionFundingObservation.value,
                    Institution.region_sido,
                    Institution.region_sigungu,
                )
                .join(
                    Institution,
                    Institution.id == InstitutionFundingObservation.institution_id,
                )
                .where(
                    InstitutionFundingObservation.sector == sector,
                    InstitutionFundingObservation.metric_code == FUNDING_METRIC_CODE,
                    InstitutionFundingObservation.source_effective_month == analysis_month,
                    InstitutionFundingObservation.valid_to.is_(None),
                    InstitutionFundingObservation.institution_id.is_not(None),
                    InstitutionFundingObservation.identity_status.in_(
                        VERIFIED_IDENTITY_STATUSES
                    ),
                )
            )
        )

    return [
        FundingPeerPoint(
            institution_id=str(institution_id),
            sector=row_sector,
            balance=balance,
            region_sido=region_sido,
            region_sigungu=region_sigungu,
        )
        for institution_id, row_sector, balance, region_sido, region_sigungu in rows
    ]
