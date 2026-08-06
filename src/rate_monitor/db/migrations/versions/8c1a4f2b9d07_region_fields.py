"""institutions·outlets에 지역 네 칸 (v4 §4.2)

화면이 매번 SQL에서 주소를 잘라 쓰던 것을 칸으로 옮긴다. 같은 규칙이 수집
쪽(kfcc/parser)과 화면 쪽(dashboard_service)에 두 벌 있었고, 한쪽만 고치면
수집한 값과 보이는 값이 갈라진다.

**주소가 없거나 못 읽으면 비워 둔다.** 지어내지 않는다. 대신 review_items에
남겨서 나중에 셀 수 있게 한다 — 조용히 NULL만 남으면 "원래 없는 것"과
"채우다 실패한 것"을 구별할 수 없다.

`sido_code`/`sigungu_code`는 그대로 NULL이다. 주소를 파싱했다고 행정구역
공식 코드를 추정 입력하지 않는다 (v3.1 §11).

Revision ID: 8c1a4f2b9d07
Revises: 31f56a26f628
Create Date: 2026-08-06
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

from rate_monitor.db.models import new_id
from rate_monitor.services.region_service import is_known_sido, region_fields

revision: str = "8c1a4f2b9d07"
down_revision: str | None = "31f56a26f628"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("institutions", "outlets")


def upgrade() -> None:
    for table in TABLES:
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.add_column(sa.Column("region_sido", sa.String(length=32), nullable=True))
            batch_op.add_column(sa.Column("region_sigungu", sa.String(length=32), nullable=True))
            batch_op.add_column(
                sa.Column(
                    "geo_basis",
                    sa.String(length=32),
                    nullable=False,
                    server_default="none",
                )
            )
            batch_op.add_column(sa.Column("geo_confidence", sa.String(length=16), nullable=True))
            batch_op.create_index(
                f"ix_{table}_region_sido", ["region_sido"], unique=False
            )
            batch_op.create_index(
                f"ix_{table}_region_sigungu", ["region_sigungu"], unique=False
            )

    _backfill(op.get_bind())


def downgrade() -> None:
    for table in TABLES:
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.drop_index(f"ix_{table}_region_sigungu")
            batch_op.drop_index(f"ix_{table}_region_sido")
            batch_op.drop_column("geo_confidence")
            batch_op.drop_column("geo_basis")
            batch_op.drop_column("region_sigungu")
            batch_op.drop_column("region_sido")


def _backfill(bind: sa.engine.Connection) -> None:
    """기존 행의 네 칸을 주소에서 채운다.

    원천은 source_entity_links로 찾는다. 같은 기관이 두 원천에 걸쳐 있으면
    가장 최근 활성 매핑을 쓴다 — 여러 벌 중 하나를 골라야 하는데, 오래된
    쪽을 고를 이유가 없다.
    """
    now = datetime.now(UTC).replace(tzinfo=None)
    unresolved: list[tuple[str, str, str, str | None]] = []

    for table in TABLES:
        entity_type = "institution" if table == "institutions" else "outlet"
        rows = bind.execute(
            sa.text(
                f"SELECT e.id AS id, e.address AS address,"
                f"       (SELECT l.source_id FROM source_entity_links l"
                f"         WHERE l.entity_type = :entity_type AND l.entity_id = e.id"
                f"         ORDER BY l.valid_to IS NULL DESC, l.created_at DESC"
                f"         LIMIT 1) AS source_id"
                f"  FROM {table} e"
            ),
            {"entity_type": entity_type},
        ).mappings().all()

        updates = []
        for row in rows:
            fields = region_fields(row["source_id"] or "", row["address"])
            updates.append(
                {
                    "pk": row["id"],
                    "sido": fields.sido,
                    "sigungu": fields.sigungu,
                    "basis": fields.basis.value,
                    "confidence": fields.confidence,
                }
            )
            if fields.sido is None:
                unresolved.append(("region_unresolved", entity_type, row["id"], row["address"]))
            elif not is_known_sido(fields.sido):
                # 버리지 않는다. 실측 두 종 중 하나는 층 표기(`신동해빌딩`)이고
                # 다른 하나는 시군구가 멀쩡한 진짜 주소(`전남광주통합특별시`)라,
                # 코드가 둘을 구별할 방법이 없다. 세어 둘 뿐이다.
                unresolved.append(("region_unknown_sido", entity_type, row["id"], row["address"]))

        if updates:
            bind.execute(
                sa.text(
                    f"UPDATE {table} SET region_sido = :sido, region_sigungu = :sigungu,"
                    f"       geo_basis = :basis, geo_confidence = :confidence"
                    f" WHERE id = :pk"
                ),
                updates,
            )

    _record_unresolved(bind, unresolved, now)


MESSAGES = {
    "region_unresolved": "주소에서 시도를 뽑지 못해 지역을 비워 뒀다",
    "region_unknown_sido": "시도 이름을 별칭표가 모른다. 값은 그대로 뒀다",
}


def _record_unresolved(
    bind: sa.engine.Connection,
    unresolved: list[tuple[str, str, str, str | None]],
    now: datetime,
) -> None:
    """지역이 비었거나 수상한 행을 review_items에 남긴다.

    전국 공시(finlife)나 조회조건만 아는 신협처럼 원래 주소가 없는 원천이
    많아 건수가 클 수 있다. 그래도 남기는 이유는, 나중에 "이 원천은 왜
    지역이 비어 있나"를 물었을 때 답이 데이터 안에 있어야 하기 때문이다.
    """
    if not unresolved:
        return
    bind.execute(
        sa.text(
            "INSERT INTO review_items"
            " (id, run_id, entity_type, entity_id, issue_type, severity, message,"
            "  payload_json, status, created_at)"
            " VALUES (:id, NULL, :entity_type, :entity_id, :issue_type, 'info',"
            "         :message, :payload, 'open', :created_at)"
        ),
        [
            {
                "id": new_id(),
                "issue_type": issue_type,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "message": MESSAGES[issue_type],
                "payload": f'{{"address": {_json_str(address)}}}',
                "created_at": now,
            }
            for issue_type, entity_type, entity_id, address in unresolved
        ],
    )


def _json_str(value: str | None) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)
