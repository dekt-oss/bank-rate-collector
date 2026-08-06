"""같은 은행이 두 기관으로 갈라진 것을 합친다

`entity_service.resolve_institution`이 `source_id`까지 맞춰 매핑을 찾았기
때문에, 같은 은행을 두 원천이 받으면 org_key가 완전히 같아도 기관 행이 둘
생겼다. 2026-08-06 발행 DB 실측:

    savings_bank:0010390  finlife_savings_bank  '고려저축은행'  주소 없음
    savings_bank:0010390  fsb                   '고려'         부산광역시 동구 …

저축은행 **79곳 전부**가 이렇게 갈라져 있었다. 전체 2,296개 키 중 갈라진
것이 정확히 그 79개이고, 다른 업권은 원천이 하나뿐이라 해당 없다.

수집기 쪽은 고쳤다. 이 마이그레이션은 이미 들어 있는 행을 합친다.

**합치는 조건은 수집기와 같다** — 공식 코드로 만든 키이고, 정규화한 이름도
같고, 업권도 같을 때만. 하나라도 어긋나면 손대지 않는다. 갈라진 것은 화면에
보이지만 잘못 합쳐진 것은 안 보인다.

**관측은 옮기지 않는다.** `rate_observations`는 `product_variants`를 거쳐
붙고, `variant_key`에 org_key가 들어간다. 관측을 다른 기관으로 옮기면
`variant_key`가 가리키는 곳과 실제가 어긋난다. 대신 상품·점포·매핑만
살아남는 기관으로 돌리고, 진 기관은 `active=0`으로 내린다 — 다음 수집이
살아남은 기관에 붙으면서 자연히 한 줄이 된다.

Revision ID: e18c4a7d9b30
Revises: 0a09e1fc2d26
Create Date: 2026-08-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from rate_monitor.domain.normalization import normalize_institution_name
from rate_monitor.services.institution_matching import normalize_institution

revision: str = "e18c4a7d9b30"
down_revision: str | None = "0a09e1fc2d26"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT l.source_entity_key AS k, i.id AS id, i.sector AS sector,"
            "       i.canonical_name AS name, i.address AS address,"
            "       i.region_sido AS sido, i.region_sigungu AS sigungu,"
            "       i.geo_basis AS geo, i.geo_confidence AS conf"
            "  FROM source_entity_links l"
            "  JOIN institutions i ON i.id = l.entity_id"
            " WHERE l.entity_type = 'institution' AND l.valid_to IS NULL"
        )
    ).fetchall()

    groups: dict[str, list[sa.Row]] = {}
    for row in rows:
        groups.setdefault(row.k, []).append(row)

    merged = 0
    for key, members in groups.items():
        if ":name:" in key:
            continue
        unique = {m.id: m for m in members}
        if len(unique) < 2:
            continue
        if len({m.sector for m in unique.values()}) != 1:
            continue
        if len({normalize_institution(m.name) for m in unique.values()}) != 1:
            continue

        # 주소를 가진 쪽이 남는다. 주소는 이 데이터에서 되찾기 가장 어려운
        # 값이고, 없는 쪽은 원천이 애초에 안 준 것이다.
        ordered = sorted(unique.values(), key=lambda m: (m.address is None, m.id))
        winner, losers = ordered[0], ordered[1:]

        # 이름은 긴 쪽. `고려`보다 `고려저축은행`이 화면에서 덜 헷갈린다.
        name = max((m.name or "" for m in unique.values()), key=len)
        bind.execute(
            sa.text(
                "UPDATE institutions SET canonical_name = :n, normalized_name = :nn"
                " WHERE id = :id"
            ),
            {"n": name, "nn": normalize_institution_name(name), "id": winner.id},
        )

        # 주소·지역은 빈 칸만 채운다. 이미 있는 값은 덮지 않는다.
        if winner.address is None:
            donor = next((m for m in losers if m.address is not None), None)
            if donor is not None:
                bind.execute(
                    sa.text(
                        "UPDATE institutions SET address = :a, region_sido = :sido,"
                        " region_sigungu = :gu, geo_basis = :geo, geo_confidence = :conf"
                        " WHERE id = :id"
                    ),
                    {
                        "a": donor.address,
                        "sido": donor.sido,
                        "gu": donor.sigungu,
                        "geo": donor.geo,
                        "conf": donor.conf,
                        "id": winner.id,
                    },
                )

        for loser in losers:
            for table in ("source_entity_links", "outlets", "products"):
                column = "entity_id" if table == "source_entity_links" else "institution_id"
                where = (
                    " AND entity_type = 'institution'"
                    if table == "source_entity_links"
                    else ""
                )
                bind.execute(
                    sa.text(
                        f"UPDATE {table} SET {column} = :win"
                        f" WHERE {column} = :lose{where}"
                    ),
                    {"win": winner.id, "lose": loser.id},
                )
            bind.execute(
                sa.text("UPDATE institutions SET active = 0 WHERE id = :id"),
                {"id": loser.id},
            )
        merged += len(losers)

    print(f"[e18c4a7d9b30] 갈라진 기관 {merged}개를 합쳤다")


def downgrade() -> None:
    """되돌리지 않는다. `b47e0a91c3d5`와 같은 이유다.

    **스키마를 건드리지 않았으므로 되돌릴 스키마가 없다.** 이 마이그레이션은
    DDL이 하나도 없고 데이터만 옮긴다.

    갈라진 상태로 되돌리려면 어느 상품이 어느 기관에 붙어 있었는지가 있어야
    하는데, 그것을 남기지 않았다. 굳이 필요하면 합치기 전 스냅샷에서
    복원한다 — 발행 DB는 매 실행마다 R2와 rate-data에 남는다.
    """
