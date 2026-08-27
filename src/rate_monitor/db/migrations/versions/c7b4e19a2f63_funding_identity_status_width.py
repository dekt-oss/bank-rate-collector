"""기관별 수신 identity 상태 문자열 계약을 실제 상태값 길이에 맞춘다.

Revision ID: c7b4e19a2f63
Revises: 8f41c2a7d990
Create Date: 2026-08-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c7b4e19a2f63"
down_revision: str | None = "8f41c2a7d990"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("institution_funding_observations") as batch_op:
        batch_op.alter_column(
            "identity_status",
            existing_type=sa.String(length=24),
            type_=sa.String(length=48),
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("institution_funding_observations") as batch_op:
        batch_op.alter_column(
            "identity_status",
            existing_type=sa.String(length=48),
            type_=sa.String(length=24),
            existing_nullable=False,
        )
