"""FSB 가입가능지역 temporal membership 표를 추가한다.

금리 observation과 본점 소재지는 건드리지 않는다. 공식 AREA membership만
별도 축으로 저장하며, 활성 자연키는 source + institution + product_type + area다.

Revision ID: f6a1c4e29b70
Revises: 8f41c2a7d990
Create Date: 2026-09-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f6a1c4e29b70"
down_revision: str | None = "8f41c2a7d990"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "institution_availability_memberships",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("institution_id", sa.String(length=36), nullable=False),
        sa.Column("product_type", sa.String(length=32), nullable=False),
        sa.Column("area_code", sa.String(length=32), nullable=False),
        sa.Column("area_label", sa.String(length=32), nullable=False),
        sa.Column("availability_match_key", sa.String(length=128), nullable=False),
        sa.Column("source_effective_date", sa.Date(), nullable=False),
        sa.Column("source_locator", sa.Text(), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("seen_count", sa.Integer(), nullable=False),
        sa.Column("valid_from", sa.DateTime(), nullable=False),
        sa.Column("valid_to", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["institution_id"], ["institutions.id"]),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_institution_availability_active",
        "institution_availability_memberships",
        ["source_id", "institution_id", "product_type", "area_code"],
        unique=True,
        sqlite_where=sa.text("valid_to IS NULL"),
    )
    op.create_index(
        "ix_institution_availability_cohort",
        "institution_availability_memberships",
        ["source_id", "product_type", "area_code", "institution_id"],
        unique=False,
    )
    op.create_index(
        "ix_institution_availability_institution",
        "institution_availability_memberships",
        ["institution_id", "product_type", "valid_to"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_institution_availability_institution",
        table_name="institution_availability_memberships",
    )
    op.drop_index(
        "ix_institution_availability_cohort",
        table_name="institution_availability_memberships",
    )
    op.drop_index(
        "uq_institution_availability_active",
        table_name="institution_availability_memberships",
    )
    op.drop_table("institution_availability_memberships")
