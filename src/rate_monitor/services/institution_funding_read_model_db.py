"""DB adapter for the institution-funding L2 read model."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from rate_monitor.db.institution_funding_models import InstitutionFundingObservation
from rate_monitor.db.session import create_db_engine, make_session_factory, session_scope
from rate_monitor.services.institution_funding_read_model import (
    FundingPoint,
    InstitutionFundingReadRow,
    build_institution_funding_read_model,
)

FUNDING_METRIC_CODE = "deposit_liabilities_total"
VERIFIED_IDENTITY_STATUSES = frozenset(
    {
        "mapped_exact_fss_code",
        "mapped_exact_nh_brc_name",
        "mapped_exact_cu_ingno",
    }
)


def load_funding_points(
    db_path: Path,
    *,
    sector: str,
    analysis_month: str,
    metric_code: str = FUNDING_METRIC_CODE,
) -> list[FundingPoint]:
    """Load active exact-identity observations needed for 6M/12M metrics.

    Source-specific exact identity states are normalized to the L2 internal
    ``exact`` state. Only one explicit canonical metric and the analysis month
    plus its exact 6M/12M priors are loaded; no nearest-month interpolation is
    allowed.
    """
    year, month = (int(part) for part in analysis_month.split("-"))

    def shift(delta: int) -> str:
        absolute = year * 12 + (month - 1) + delta
        shifted_year, shifted_month0 = divmod(absolute, 12)
        return f"{shifted_year:04d}-{shifted_month0 + 1:02d}"

    months = {analysis_month, shift(-6), shift(-12)}
    engine = create_db_engine(db_path)
    factory = make_session_factory(engine)
    with session_scope(factory) as session:
        observations = list(
            session.scalars(
                select(InstitutionFundingObservation).where(
                    InstitutionFundingObservation.sector == sector,
                    InstitutionFundingObservation.metric_code == metric_code,
                    InstitutionFundingObservation.valid_to.is_(None),
                    InstitutionFundingObservation.institution_id.is_not(None),
                    InstitutionFundingObservation.identity_status.in_(
                        VERIFIED_IDENTITY_STATUSES
                    ),
                    InstitutionFundingObservation.source_effective_month.in_(months),
                )
            )
        )

    return [
        FundingPoint(
            institution_id=str(observation.institution_id),
            sector=observation.sector,
            month=observation.source_effective_month,
            balance=observation.value,
            identity_status="exact",
            quality_status="usable_exact",
        )
        for observation in observations
    ]


def build_institution_funding_read_model_from_db(
    db_path: Path,
    *,
    sector: str,
    analysis_month: str,
    metric_code: str = FUNDING_METRIC_CODE,
) -> list[InstitutionFundingReadRow]:
    points = load_funding_points(
        db_path,
        sector=sector,
        analysis_month=analysis_month,
        metric_code=metric_code,
    )
    return build_institution_funding_read_model(
        points,
        sector=sector,
        analysis_month=analysis_month,
    )
