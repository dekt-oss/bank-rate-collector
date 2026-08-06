"""finlife 소스를 권역별로 가른다 (v4 §6.2).

같은 API가 저축은행(`030300`)과 시중은행(`020000`)을 함께 준다. 지금까지
둘 다 `source_id="finlife"` 하나로 들어왔는데, 그러면 화면이 둘을 못 가른다
— 시중은행은 참고지표로 내려가고 저축은행은 메인 비교표에 남아야 한다.

**기존 레코드를 지우지 않는다** (v4 §6.2). 이름만 옮긴다.

발행 중인 DB(rate-data `1b5ba28`, 2026-08-06)에서 확인한 것:

    관측 6,463건 · 기관 79개 — 전부 sector=savings_bank
    원본 아티팩트 80건 — 전부 topFinGrpNo=030300
    링크 748건 (기관 79 + 상품 669)

즉 지금까지 들어온 `finlife` 레코드는 **하나도 빠짐없이 저축은행이다.**
그래서 조건 없이 `finlife_savings_bank`로 옮겨도 된다. 그 전제가 깨지면
(은행 행이 섞여 있으면) upgrade가 멈춘다 — 조용히 잘못 옮기지 않는다.
"""

from alembic import op
from sqlalchemy import text

revision = "d5a71c3f8b62"
down_revision = "c93f5b71e284"
branch_labels = None
depends_on = None

# sources의 id·name을 뺀 나머지 칼럼. 두 곳에서 같은 목록을 써야 하므로
# 여기 한 번만 적는다. 칼럼이 늘면 여기만 고친다.
SOURCE_COPY_COLUMNS = (
    "sector, mode, source_role, trust_level, priority, base_reference, enabled,"
    " schedule_cron, policy_status, coverage_status, parser_version,"
    " created_at, updated_at"
)

OLD = "finlife"
NEW = "finlife_savings_bank"

# source_id를 들고 있는 표. sources를 마지막에 옮겨야 외래키가 매 순간
# 성립한다 — 먼저 옮기면 자식 행이 없는 부모를 가리킨다.
CHILD_TABLES = ("collection_runs", "source_entity_links", "entity_aliases",
                "collection_run_stats")


def _table_exists(bind, name: str) -> bool:
    return bind.execute(
        text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:n"), {"n": name}
    ).first() is not None


def upgrade() -> None:
    bind = op.get_bind()

    source = bind.execute(
        text("SELECT sector FROM sources WHERE id = :old"), {"old": OLD}
    ).first()
    if source is None:
        return  # 새 DB. 옮길 것이 없다.

    # 전제 확인. 은행 행이 섞여 있으면 이 마이그레이션은 틀린 도구다.
    mixed = bind.execute(
        text(
            "SELECT COUNT(*) FROM rate_observations o"
            "  JOIN collection_runs r ON r.id = o.run_id"
            "  JOIN product_variants v ON v.id = o.variant_id"
            "  JOIN products p ON p.id = v.product_id"
            "  JOIN institutions i ON i.id = p.institution_id"
            " WHERE r.source_id = :old AND i.sector <> 'savings_bank'"
        ),
        {"old": OLD},
    ).scalar()
    if mixed:
        raise RuntimeError(
            f"finlife 관측 중 저축은행이 아닌 것이 {mixed}건이다. "
            "전부 저축은행이라는 전제가 깨졌으므로 옮기지 않는다 — "
            "권역별로 나눠 옮기는 마이그레이션을 따로 써야 한다"
        )

    # 새 이름의 sources 행을 먼저 만든다. 자식이 가리킬 부모가 있어야 한다.
    bind.execute(
        text(
            f"INSERT INTO sources (id, name, {SOURCE_COPY_COLUMNS})"
            f" SELECT :new, :name, {SOURCE_COPY_COLUMNS} FROM sources WHERE id = :old"
        ),
        {"new": NEW, "name": "금융감독원 비교공시 — 저축은행", "old": OLD},
    )

    for table in CHILD_TABLES:
        if _table_exists(bind, table):
            bind.execute(
                text(f"UPDATE {table} SET source_id = :new WHERE source_id = :old"),
                {"new": NEW, "old": OLD},
            )

    bind.execute(text("DELETE FROM sources WHERE id = :old"), {"old": OLD})


def downgrade() -> None:
    """되돌린다. 은행 소스는 건드리지 않는다.

    `finlife_bank`는 이 마이그레이션이 만든 것이 아니라 수집이 만든다.
    되돌린다고 은행 데이터를 지우면 수집분을 잃는다.
    """
    bind = op.get_bind()
    if bind.execute(
        text("SELECT 1 FROM sources WHERE id = :new"), {"new": NEW}
    ).first() is None:
        return

    bind.execute(
        text(
            f"INSERT INTO sources (id, name, {SOURCE_COPY_COLUMNS})"
            f" SELECT :old, :name, {SOURCE_COPY_COLUMNS} FROM sources WHERE id = :new"
        ),
        {
            "old": OLD,
            "name": "금융감독원 금융상품통합비교공시 오픈API",
            "new": NEW,
        },
    )
    for table in CHILD_TABLES:
        if _table_exists(bind, table):
            bind.execute(
                text(f"UPDATE {table} SET source_id = :old WHERE source_id = :new"),
                {"old": OLD, "new": NEW},
            )
    bind.execute(text("DELETE FROM sources WHERE id = :new"), {"new": NEW})
