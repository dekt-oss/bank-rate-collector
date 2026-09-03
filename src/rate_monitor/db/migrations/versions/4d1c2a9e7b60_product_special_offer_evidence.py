"""상품 특판 여부의 forward-only evidence registry를 추가한다.

기존 products.is_special_sale은 변경하지 않는다. unknown을 false로 낮추지 않고
원천 snapshot과 명시적 판정 근거를 별도 append-only 표에 보존한다.

Revision ID: 4d1c2a9e7b60
Revises: f6a1c4e29b70
Create Date: 2026-09-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4d1c2a9e7b60"
down_revision: str | None = "f6a1c4e29b70"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "product_special_offer_evidence",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("product_id", sa.String(length=36), nullable=False),
        sa.Column("source_product_key", sa.String(length=128), nullable=False),
        sa.Column("classification", sa.String(length=24), nullable=False),
        sa.Column("evidence_kind", sa.String(length=48), nullable=False),
        sa.Column("snapshot_as_of", sa.Date(), nullable=False),
        sa.Column("source_effective_from", sa.Date(), nullable=True),
        sa.Column("source_effective_to", sa.Date(), nullable=True),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.Column("source_locator", sa.Text(), nullable=False),
        sa.Column("evidence_ref", sa.Text(), nullable=False),
        sa.Column("raw_artifact_id", sa.String(length=36), nullable=True),
        sa.Column("content_hash", sa.String(length=80), nullable=False),
        sa.Column("evidence_key", sa.String(length=80), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "classification IN ('unknown', 'confirmed_special', 'confirmed_normal')",
            name="ck_product_special_offer_classification",
        ),
        sa.CheckConstraint(
            "source_effective_to IS NULL OR "
            "(source_effective_from IS NOT NULL AND "
            "source_effective_to >= source_effective_from)",
            name="ck_product_special_offer_effective_period",
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.ForeignKeyConstraint(["raw_artifact_id"], ["raw_artifacts.id"]),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("evidence_key", name="uq_product_special_offer_evidence_key"),
    )
    op.create_index(
        "ix_product_special_offer_snapshot",
        "product_special_offer_evidence",
        ["product_id", "snapshot_as_of", "observed_at"],
        unique=False,
    )
    op.create_index(
        "ix_product_special_offer_source_key",
        "product_special_offer_evidence",
        ["source_id", "source_product_key"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_product_special_offer_source_key",
        table_name="product_special_offer_evidence",
    )
    op.drop_index(
        "ix_product_special_offer_snapshot",
        table_name="product_special_offer_evidence",
    )
    op.drop_table("product_special_offer_evidence")
