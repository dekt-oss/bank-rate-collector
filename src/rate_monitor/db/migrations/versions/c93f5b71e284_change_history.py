"""관측을 변경 이벤트로 (선행 수정안 §3.2)

같은 금리라도 수집할 때마다 새 행이 생겼다. 8월 6일 3.10, 7일 3.10, 8일 3.10.
실측 185,923행 중 43,116행이 그런 중복이고, 네 원천 합계 48,924행/회를 평일마다
쌓으면 1년에 1,272만 행 — 약 19 GB가 된다.

이제는 값이 바뀔 때만 행이 생긴다. 이 마이그레이션은 이미 쌓인 행을 같은
모양으로 접는다.

**행이 줄어든다.** 되돌릴 수 없는 변경이므로 스냅샷 사본으로 먼저 돌려 보고
넣는다. 되돌리려면 R2 스냅샷에서 복원한다.

Revision ID: c93f5b71e284
Revises: b47e0a91c3d5
Create Date: 2026-08-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c93f5b71e284"
down_revision: str | None = "b47e0a91c3d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()

    with op.batch_alter_table("rate_observations", schema=None) as batch_op:
        # NOT NULL 칸은 채운 뒤에 조인다. 지금은 NULL을 허용해 두고 백필한다.
        batch_op.add_column(sa.Column("last_run_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("first_seen_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("last_seen_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("seen_count", sa.Integer(), nullable=False,
                                      server_default="1"))
        batch_op.add_column(sa.Column("valid_from", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("valid_to", sa.DateTime(), nullable=True))

    _fold(bind)

    with op.batch_alter_table("rate_observations", schema=None) as batch_op:
        batch_op.alter_column("last_run_id", nullable=False,
                              existing_type=sa.String(length=36))
        batch_op.alter_column("first_seen_at", nullable=False, existing_type=sa.DateTime())
        batch_op.alter_column("last_seen_at", nullable=False, existing_type=sa.DateTime())
        batch_op.alter_column("valid_from", nullable=False, existing_type=sa.DateTime())
        batch_op.create_foreign_key(
            "fk_rate_observations_last_run", "collection_runs", ["last_run_id"], ["id"]
        )
        # 예전 유니크는 실행마다 행이 생길 때만 뜻이 있었다.
        batch_op.drop_constraint("uq_rate_observations_variant_run", type_="unique")
        batch_op.create_index("ix_rate_observations_last_run_id", ["last_run_id"])
        batch_op.create_index(
            "uq_rate_observations_current",
            ["variant_id"],
            unique=True,
            sqlite_where=sa.text("valid_to IS NULL"),
        )

    # 여기서 VACUUM하지 않는다. alembic 트랜잭션 안이라 SQLite가 거부한다.
    # 지운 자리는 발행 스냅샷이 `VACUUM INTO`로 돌려받는다
    # (services/snapshot_service.create_snapshot).

    op.create_table(
        "collection_run_stats",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("fetched_count", sa.Integer(), nullable=False),
        sa.Column("parsed_count", sa.Integer(), nullable=False),
        sa.Column("unchanged_count", sa.Integer(), nullable=False),
        sa.Column("changed_count", sa.Integer(), nullable=False),
        sa.Column("new_variant_count", sa.Integer(), nullable=False),
        sa.Column("missing_variant_count", sa.Integer(), nullable=False),
        sa.Column("error_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["collection_runs.id"]),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", name="uq_collection_run_stats_run"),
    )


def downgrade() -> None:
    op.drop_table("collection_run_stats")
    with op.batch_alter_table("rate_observations", schema=None) as batch_op:
        batch_op.drop_index("uq_rate_observations_current")
        batch_op.drop_index("ix_rate_observations_last_run_id")
        batch_op.create_unique_constraint(
            "uq_rate_observations_variant_run", ["variant_id", "run_id"]
        )
        batch_op.drop_column("valid_to")
        batch_op.drop_column("valid_from")
        batch_op.drop_column("seen_count")
        batch_op.drop_column("last_seen_at")
        batch_op.drop_column("first_seen_at")
        batch_op.drop_column("last_run_id")
    # 접은 행은 되살리지 않는다. 이력이 필요하면 스냅샷에서 복원한다.


def _fold(bind: sa.engine.Connection) -> None:
    """같은 값이 이어지는 구간을 한 행으로 접는다.

    **`(variant_id, content_hash)`로 묶으면 안 된다.** 3.10 → 3.20 → 3.10처럼
    돌아온 값이 한 덩어리가 되어, 중간의 3.20이 언제였는지가 사라진다.
    시간순으로 훑으며 **이어지는** 구간만 묶는다.
    """
    rows = bind.execute(
        sa.text(
            "SELECT id, variant_id, content_hash, run_id, observed_at"
            "  FROM rate_observations ORDER BY variant_id, observed_at, id"
        )
    ).mappings().all()

    keep: list[dict[str, object]] = []
    drop: list[str] = []

    current_variant = None
    head: dict[str, object] | None = None

    for row in rows:
        if row["variant_id"] != current_variant:
            # 앞 비교 단위의 마지막 구간을 먼저 닫는다. 이걸 빠뜨리면 그 행이
            # keep에 안 들어가 last_run_id가 NULL로 남는다.
            if head is not None:
                keep.append(head)
            current_variant = row["variant_id"]
            head = None

        if head is not None and head["hash"] == row["content_hash"]:
            # 같은 값이 이어진다. 행을 버리고 대표 행의 카운터만 올린다.
            drop.append(row["id"])
            head["last_seen_at"] = row["observed_at"]
            head["last_run_id"] = row["run_id"]
            head["seen_count"] = int(head["seen_count"]) + 1
            continue

        if head is not None:
            # 값이 바뀌었다. 앞 구간은 여기서 끝난다.
            head["valid_to"] = row["observed_at"]
            keep.append(head)

        head = {
            "pk": row["id"],
            "hash": row["content_hash"],
            "first_seen_at": row["observed_at"],
            "last_seen_at": row["observed_at"],
            "last_run_id": row["run_id"],
            "seen_count": 1,
            "valid_from": row["observed_at"],
            "valid_to": None,
        }

    if head is not None:
        keep.append(head)

    if keep:
        bind.execute(
            sa.text(
                "UPDATE rate_observations SET last_run_id = :last_run_id,"
                "  first_seen_at = :first_seen_at, last_seen_at = :last_seen_at,"
                "  seen_count = :seen_count, valid_from = :valid_from,"
                "  valid_to = :valid_to WHERE id = :pk"
            ),
            [{k: v for k, v in row.items() if k != "hash"} for row in keep],
        )

    # 접힌 행을 지운다. 값이 그대로였던 구간이라 잃는 정보는 "몇 번 봤는가"
    # 뿐이고, 그것은 seen_count에 남는다.
    for start in range(0, len(drop), 500):
        chunk = drop[start : start + 500]
        marks = ",".join(f":p{i}" for i in range(len(chunk)))
        bind.execute(
            sa.text(f"DELETE FROM rate_observations WHERE id IN ({marks})"),
            {f"p{i}": value for i, value in enumerate(chunk)},
        )
