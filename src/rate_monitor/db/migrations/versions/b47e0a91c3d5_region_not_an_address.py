"""지역이 아닌 값을 지역 칸에서 뺀다

`8c1a4f2b9d07`은 주소의 첫 토막을 무조건 시도로 넣었다. 그래서 저축은행중앙회가
동양저축은행 주소로 주는 `신동해빌딩 1,2,3층`이 시도 `신동해빌딩`, 구·군
`1,2,3층`이 됐고, 공개 사이트의 지역 필터와 구·군 필터에 그대로 떴다.

`region_service.looks_like_sido`가 이제 그걸 거른다. 이 마이그레이션은 이미
들어 있는 행에 같은 규칙을 다시 먹인다.

**주소 원문은 건드리지 않는다.** `address` 칸은 그대로이므로 잃는 정보는 없고,
지역 칸만 비워진다. `전남광주통합특별시`처럼 별칭표가 모를 뿐 시군구가
멀쩡한 이름은 그대로 남는다.

Revision ID: b47e0a91c3d5
Revises: 8c1a4f2b9d07
Create Date: 2026-08-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from rate_monitor.db.models import new_id
from rate_monitor.domain.timeutil import now_kst
from rate_monitor.services.region_service import looks_like_sido

revision: str = "b47e0a91c3d5"
down_revision: str | None = "8c1a4f2b9d07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("institutions", "outlets")


def upgrade() -> None:
    bind = op.get_bind()
    now = now_kst().replace(tzinfo=None)
    cleared: list[tuple[str, str, str | None]] = []

    for table in TABLES:
        entity_type = "institution" if table == "institutions" else "outlet"
        rows = bind.execute(
            sa.text(
                f"SELECT id, address, region_sido FROM {table}"
                f" WHERE region_sido IS NOT NULL"
            )
        ).mappings().all()

        bad = [row for row in rows if not looks_like_sido(row["region_sido"])]
        if not bad:
            continue

        bind.execute(
            sa.text(
                f"UPDATE {table} SET region_sido = NULL, region_sigungu = NULL,"
                f"       geo_confidence = 'none' WHERE id = :pk"
            ),
            [{"pk": row["id"]} for row in bad],
        )
        cleared.extend((entity_type, row["id"], row["address"]) for row in bad)

    # 앞 마이그레이션이 남긴 표시는 뜻이 달라졌으므로 걷어낸다. 그 행들은
    # 이제 "이름을 모르는 시도"가 아니라 "지역 칸을 비웠다"이다.
    bind.execute(sa.text("DELETE FROM review_items WHERE issue_type = 'region_unknown_sido'"))

    if cleared:
        bind.execute(
            sa.text(
                "INSERT INTO review_items"
                " (id, run_id, entity_type, entity_id, issue_type, severity, message,"
                "  payload_json, status, created_at)"
                " VALUES (:id, NULL, :entity_type, :entity_id, 'region_not_an_address',"
                "         'info', :message, :payload, 'open', :created_at)"
            ),
            [
                {
                    "id": new_id(),
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "message": "주소에 시도가 없어 지역 칸을 비웠다. 주소 원문은 그대로다",
                    "payload": _json_str(address),
                    "created_at": now,
                }
                for entity_type, entity_id, address in cleared
            ],
        )


def downgrade() -> None:
    """되돌리지 않는다.

    비운 것을 다시 채우려면 틀린 값을 복원해야 한다. 스키마는 그대로이므로
    되돌릴 것도 없다 — 다시 채우고 싶으면 앞 마이그레이션의 백필을 돌리면
    된다.
    """


def _json_str(address: str | None) -> str:
    import json

    return json.dumps({"address": address}, ensure_ascii=False)
