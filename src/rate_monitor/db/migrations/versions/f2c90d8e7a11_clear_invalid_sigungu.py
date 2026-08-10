"""시군구가 아닌 주소 토큰을 지역 칸에서 뺀다.

기존 지역 백필은 주소의 두 번째 토막을 시군구로 저장했다. 그래서 실제 발행
데이터에 `대구 / 동덕로`처럼 도로명이 `region_sigungu`로 들어간 사례가 있다.

`region_service.looks_like_sigungu`와 같은 규칙으로 기존 institutions/outlets를
다시 검사한다. 잘못된 값은 `region_sigungu`만 비우고 `region_sido`와 주소
원문은 보존한다. 시도까지는 근거가 있으므로 confidence는 medium으로 낮춘다.

Revision ID: f2c90d8e7a11
Revises: e18c4a7d9b30
Create Date: 2026-08-10
"""

from collections.abc import Sequence
import json

import sqlalchemy as sa
from alembic import op

from rate_monitor.db.models import new_id
from rate_monitor.domain.timeutil import now_kst
from rate_monitor.services.region_service import looks_like_sigungu

revision: str = "f2c90d8e7a11"
down_revision: str | None = "e18c4a7d9b30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("institutions", "outlets")


def upgrade() -> None:
    bind = op.get_bind()
    now = now_kst().replace(tzinfo=None)
    cleared: list[tuple[str, str, str | None, str, str]] = []

    for table in TABLES:
        entity_type = "institution" if table == "institutions" else "outlet"
        rows = bind.execute(
            sa.text(
                f"SELECT id, address, region_sido, region_sigungu FROM {table}"
                " WHERE region_sido IS NOT NULL AND region_sigungu IS NOT NULL"
            )
        ).mappings().all()

        bad = [
            row
            for row in rows
            if not looks_like_sigungu(row["region_sido"], row["region_sigungu"])
        ]
        if not bad:
            continue

        bind.execute(
            sa.text(
                f"UPDATE {table} SET region_sigungu = NULL, geo_confidence = 'medium'"
                " WHERE id = :pk"
            ),
            [{"pk": row["id"]} for row in bad],
        )
        cleared.extend(
            (
                entity_type,
                row["id"],
                row["address"],
                row["region_sido"],
                row["region_sigungu"],
            )
            for row in bad
        )

    if cleared:
        bind.execute(
            sa.text(
                "INSERT INTO review_items"
                " (id, run_id, entity_type, entity_id, issue_type, severity, message,"
                "  payload_json, status, created_at)"
                " VALUES (:id, NULL, :entity_type, :entity_id, 'region_invalid_sigungu',"
                "         'info', :message, :payload, 'open', :created_at)"
            ),
            [
                {
                    "id": new_id(),
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "message": "시군구가 아닌 주소 토큰을 지역 칸에서 비웠다. 주소 원문은 그대로다",
                    "payload": json.dumps(
                        {
                            "address": address,
                            "region_sido": sido,
                            "removed_region_sigungu": sigungu,
                        },
                        ensure_ascii=False,
                    ),
                    "created_at": now,
                }
                for entity_type, entity_id, address, sido, sigungu in cleared
            ],
        )


def downgrade() -> None:
    """잘못된 파생값은 복원하지 않는다.

    주소 원문이 남아 있으므로 미래 규칙으로 다시 파생할 수 있다. 여기서 도로명을
    시군구 칸으로 되돌리면 이미 확인한 데이터 오류를 재도입하게 된다.
    """
