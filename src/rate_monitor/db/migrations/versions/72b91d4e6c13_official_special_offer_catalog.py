"""bank-direct 공식 특판 evidence catalog를 canonical 상품과 분리해 추가한다.

Revision ID: 72b91d4e6c13
Revises: 4d1c2a9e7b60
Create Date: 2026-09-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "72b91d4e6c13"
down_revision: str | None = "4d1c2a9e7b60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "official_special_offer_catalog_evidence",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source_namespace", sa.String(length=64), nullable=False),
        sa.Column("institution_name", sa.Text(), nullable=False),
        sa.Column("institution_normalized", sa.Text(), nullable=False),
        sa.Column("official_product_key", sa.String(length=128), nullable=False),
        sa.Column("product_name", sa.Text(), nullable=False),
        sa.Column("classification", sa.String(length=24), nullable=False),
        sa.Column("availability_status", sa.String(length=24), nullable=False),
        sa.Column("snapshot_as_of", sa.Date(), nullable=False),
        sa.Column("source_effective_from", sa.Date(), nullable=True),
        sa.Column("source_effective_to", sa.Date(), nullable=True),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.Column("source_locator", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=80), nullable=False),
        sa.Column("evidence_key", sa.String(length=80), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("canonical_product_id", sa.String(length=36), nullable=True),
        sa.Column("binding_status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "classification IN ('confirmed_special', 'confirmed_normal')",
            name="ck_official_special_offer_catalog_classification",
        ),
        sa.CheckConstraint(
            "availability_status IN ('confirmed_active', 'confirmed_ended', 'unknown')",
            name="ck_official_special_offer_catalog_availability",
        ),
        sa.CheckConstraint(
            "source_effective_to IS NULL OR "
            "(source_effective_from IS NOT NULL AND "
            "source_effective_to >= source_effective_from)",
            name="ck_official_special_offer_catalog_effective_period",
        ),
        sa.ForeignKeyConstraint(["canonical_product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "evidence_key", name="uq_official_special_offer_catalog_evidence_key"
        ),
    )
    op.create_index(
        "ix_official_special_offer_catalog_identity",
        "official_special_offer_catalog_evidence",
        [
            "source_namespace",
            "institution_normalized",
            "official_product_key",
            "observed_at",
        ],
        unique=False,
    )
    op.create_index(
        "ix_official_special_offer_catalog_availability",
        "official_special_offer_catalog_evidence",
        ["availability_status", "observed_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_official_special_offer_catalog_availability",
        table_name="official_special_offer_catalog_evidence",
    )
    op.drop_index(
        "ix_official_special_offer_catalog_identity",
        table_name="official_special_offer_catalog_evidence",
    )
    op.drop_table("official_special_offer_catalog_evidence")
