"""농·축협 이자방식의 추정값을 원천 근거 수준으로 되돌린다.

기존 NH 파서는 `복리` 문자열이 없으면 전부 `simple`로 저장했고, 비고에
복리식 상품을 언급하기만 해도 그 행을 `compound`로 저장했다.

2026-08-10 전국 실원본 9,742개 상세 화면 / 198,670행 전수 확인 결과:

- 직접 복리 근거: 29,100행
- 직접 단리 근거: 0행
- 복리식 상품을 대상상품으로 언급만 한 e-joy 우대금리: 19,472행
- 단리·복리 직접 근거 없음: 150,098행

운영 DB 분포도 `compound=48,572`, `simple=150,098`로 정확히 일치했다.
따라서 기존 `simple` 전부와 e-joy 우대금리의 `compound`만 `unknown`으로
고친다. 관측·원본·provenance는 건드리지 않고 variant 의미와 deterministic
variant_key만 함께 교정한다.

Revision ID: a3b7c2d91e40
Revises: f2c90d8e7a11
Create Date: 2026-08-10
"""

from collections.abc import Sequence
from hashlib import sha256

import sqlalchemy as sa
from alembic import op

revision: str = "a3b7c2d91e40"
down_revision: str | None = "f2c90d8e7a11"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SOURCE_ID = "nh_local"
BONUS_PRODUCT = "e-joy 인터넷예금 우대금리"


def _digest(parts: list[str]) -> str:
    """현재 `make_variant_key` 계약의 16자리 digest를 이 migration에 고정한다."""
    return sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]


def _source_key(link_key: str | None, institution_id: str) -> str:
    prefix = f"{institution_id}:"
    if not link_key or not link_key.startswith(prefix):
        raise RuntimeError(
            "NH outlet source key를 복원할 수 없다: "
            f"institution={institution_id!r}, link={link_key!r}"
        )
    value = link_key[len(prefix) :]
    if not value:
        raise RuntimeError(f"NH outlet source key가 비었다: {link_key!r}")
    return value


def _variant_key(row: dict, interest_method: str) -> str:
    outlet_key = _source_key(row["outlet_link_key"], row["institution_id"])
    org_key = f"{SOURCE_ID}:{outlet_key}"
    term_part = (
        f"m{row['term_months']}"
        if row["term_months"] is not None
        else (
            f"d{row['term_days']}" if row["term_days"] is not None else "none"
        )
    )
    low = "" if row["amount_min"] is None else str(row["amount_min"])
    high = "" if row["amount_max"] is None else str(row["amount_max"])
    return _digest(
        [
            SOURCE_ID,
            org_key,
            row["product_name"],  # NH source_product_key는 원천 상품명 그대로다.
            term_part,
            row["join_channel"],
            interest_method,
            row["payment_method"] or "",
            f"{low}~{high}",
            outlet_key,
        ]
    )


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT v.id, v.variant_key, v.interest_method,"
            "       v.term_months, v.term_days, v.join_channel, v.payment_method,"
            "       v.amount_min, v.amount_max,"
            "       p.name AS product_name, p.institution_id AS institution_id,"
            "       ol.source_entity_key AS outlet_link_key"
            "  FROM product_variants v"
            "  JOIN products p ON p.id = v.product_id"
            "  JOIN institutions i ON i.id = p.institution_id"
            "  LEFT JOIN source_entity_links ol"
            "    ON ol.source_id = :source_id"
            "   AND ol.entity_type = 'outlet'"
            "   AND ol.entity_id = v.outlet_id"
            "   AND ol.valid_to IS NULL"
            " WHERE i.sector = :source_id"
            "   AND (v.interest_method = 'simple'"
            "        OR (v.interest_method = 'compound' AND p.name = :bonus_product))"
        ),
        {"source_id": SOURCE_ID, "bonus_product": BONUS_PRODUCT},
    ).mappings().all()

    # 한 variant에 활성 outlet link가 여러 개 붙어 query가 중복되면 조용히
    # 어느 것을 고르지 않는다. identity 교정은 fail-closed여야 한다.
    ids = [row["id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise RuntimeError("NH variant에 활성 outlet source link가 여러 개다")

    key_owner = {
        key: entity_id
        for entity_id, key in bind.execute(
            sa.text("SELECT id, variant_key FROM product_variants")
        ).all()
    }
    target_owner: dict[str, str] = {}
    updates: list[dict[str, str]] = []
    simple_count = 0
    bonus_count = 0

    for row in rows:
        new_key = _variant_key(dict(row), "unknown")
        owner = key_owner.get(new_key)
        if owner is not None and owner != row["id"]:
            raise RuntimeError(
                "NH interest-method 교정 target variant_key가 이미 존재한다: "
                f"source={row['id']}, target={owner}, key={new_key}"
            )
        prior = target_owner.get(new_key)
        if prior is not None and prior != row["id"]:
            raise RuntimeError(
                "NH interest-method 교정 대상끼리 variant_key가 충돌한다: "
                f"{prior}, {row['id']}, key={new_key}"
            )
        target_owner[new_key] = row["id"]
        updates.append({"id": row["id"], "variant_key": new_key})
        if row["interest_method"] == "simple":
            simple_count += 1
        else:
            bonus_count += 1

    if updates:
        bind.execute(
            sa.text(
                "UPDATE product_variants"
                "   SET interest_method = 'unknown', variant_key = :variant_key"
                " WHERE id = :id"
            ),
            updates,
        )

    print(
        "[a3b7c2d91e40] NH interest_method corrected: "
        f"simple→unknown {simple_count}, e-joy compound→unknown {bonus_count}"
    )


def downgrade() -> None:
    """검증으로 틀렸다고 확인한 추정값은 되살리지 않는다.

    raw/provenance가 그대로 남아 있으므로 필요하면 미래의 더 강한 근거로 다시
    분류할 수 있다. 여기서 `unknown`을 `simple`/`compound`로 복원하면 이미
    확인한 의미 오류를 재도입한다.
    """
