"""기관별 수신잔액 observation 저장축을 추가한다.

Revision ID: 8f41c2a7d990
Revises: 3b8d1f6a2c44
Create Date: 2026-08-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from rate_monitor.db.types import QUANTITY_WIDTH

revision: str = "8f41c2a7d990"
down_revision: str | None = "3b8d1f6a2c44"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "institution_funding_observations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("institution_id", sa.String(length=36), nullable=True),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("source_institution_key", sa.String(length=128), nullable=False),
        sa.Column("source_institution_name", sa.Text(), nullable=False),
        sa.Column("source_crno", sa.String(length=32), nullable=True),
        sa.Column("sector", sa.String(length=32), nullable=False),
        sa.Column("metric_code", sa.String(length=64), nullable=False),
        sa.Column("metric_name", sa.String(length=128), nullable=False),
        sa.Column("source_effective_month", sa.String(length=7), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        # Quantity is a zero-padded fixed-decimal string on SQLite.
        sa.Column("value", sa.String(length=QUANTITY_WIDTH), nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=False),
        sa.Column("source_value_text", sa.Text(), nullable=False),
        sa.Column("source_unit", sa.String(length=16), nullable=False),
        sa.Column("observation_basis", sa.String(length=32), nullable=False),
        sa.Column("statement_basis", sa.String(length=32), nullable=False),
        sa.Column("population_scope", sa.String(length=64), nullable=False),
        sa.Column("identity_status", sa.String(length=24), nullable=False),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.Column("source_locator", sa.Text(), nullable=False),
        sa.Column("raw_artifact_id", sa.String(length=36), nullable=False),
        sa.Column("content_hash", sa.String(length=80), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("valid_from", sa.DateTime(), nullable=False),
        sa.Column("valid_to", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["institution_id"], ["institutions.id"]),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"]),
        sa.ForeignKeyConstraint(["raw_artifact_id"], ["raw_artifacts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_id",
            "source_institution_key",
            "metric_code",
            "source_effective_month",
            "revision",
            name="uq_institution_funding_revision",
        ),
    )
    op.create_index(
        "uq_institution_funding_active",
        "institution_funding_observations",
        ["source_id", "source_institution_key", "metric_code", "source_effective_month"],
        unique=True,
        sqlite_where=sa.text("valid_to IS NULL"),
    )
    op.create_index(
        "ix_institution_funding_sector_month",
        "institution_funding_observations",
        ["sector", "source_effective_month"],
        unique=False,
    )
    op.create_index(
        "ix_institution_funding_institution_month",
        "institution_funding_observations",
        ["institution_id", "source_effective_month"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_institution_funding_institution_month",
        table_name="institution_funding_observations",
    )
    op.drop_index(
        "ix_institution_funding_sector_month",
        table_name="institution_funding_observations",
    )
    op.drop_index(
        "uq_institution_funding_active",
        table_name="institution_funding_observations",
    )
    op.drop_table("institution_funding_observations")
