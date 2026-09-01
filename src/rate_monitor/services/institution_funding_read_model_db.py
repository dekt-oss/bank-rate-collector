"""DB adapter for the institution-funding L2 read model.

This module is used while building published Strategy artifacts. The published
SQLite snapshot is an immutable deployment artifact: a read must not change its
bytes after ``snapshot`` has written the manifest hash.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from decimal import Decimal
from pathlib import Path

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
        "mapped_dual_source",
    }
)


def _open_immutable_snapshot(db_path: Path) -> sqlite3.Connection:
    """Open a deployment snapshot without journal/transaction side effects.

    ``create_db_engine`` intentionally applies ``PRAGMA journal_mode=WAL`` for
    mutable collector databases. That PRAGMA changes SQLite file bytes even for
    a query-only caller, invalidating the manifest hash after ``snapshot``.
    Strategy build reads a frozen snapshot, so use SQLite's immutable read-only
    URI instead and never create a write-capable SQLAlchemy session here.
    """
    uri = db_path.resolve().as_uri() + "?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    return connection


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

    The query path is deliberately immutable/read-only because this function is
    called after the publish snapshot hash has been sealed into ``manifest``.
    """
    year, month = (int(part) for part in analysis_month.split("-"))

    def shift(delta: int) -> str:
        absolute = year * 12 + (month - 1) + delta
        shifted_year, shifted_month0 = divmod(absolute, 12)
        return f"{shifted_year:04d}-{shifted_month0 + 1:02d}"

    months = sorted({analysis_month, shift(-6), shift(-12)})
    statuses = sorted(VERIFIED_IDENTITY_STATUSES)
    status_placeholders = ",".join("?" for _ in statuses)
    month_placeholders = ",".join("?" for _ in months)

    with closing(_open_immutable_snapshot(db_path)) as connection:
        observations = connection.execute(
            f"""
            SELECT institution_id,
                   sector,
                   source_effective_month,
                   value
            FROM institution_funding_observations
            WHERE sector = ?
              AND metric_code = ?
              AND valid_to IS NULL
              AND institution_id IS NOT NULL
              AND identity_status IN ({status_placeholders})
              AND source_effective_month IN ({month_placeholders})
            ORDER BY institution_id, source_effective_month
            """,
            (sector, metric_code, *statuses, *months),
        ).fetchall()

    return [
        FundingPoint(
            institution_id=str(observation["institution_id"]),
            sector=str(observation["sector"]),
            month=str(observation["source_effective_month"]),
            balance=Decimal(str(observation["value"])),
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
