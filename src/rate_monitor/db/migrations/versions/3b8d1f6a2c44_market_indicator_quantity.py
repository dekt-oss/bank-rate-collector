"""market_indicators 값을 wide fixed-decimal Quantity로 옮긴다.

MarketIndicator에는 percent 금리뿐 아니라 조원 단위 수신잔액이 들어간다.
기존 Rate 저장계약의 최대 999.9999로는 2026-06 예금은행 총예금
2,281.4891조원을 저장할 수 없다.

이 migration은 기존 숫자를 float로 변환하지 않는다. Decimal로 읽어 6자리
fixed-decimal 문자열로 다시 쓰고, 동시에 새 normalized-value hash로 전환한다.
행 identity/source/date/unit은 변경하지 않는다.

Revision ID: 3b8d1f6a2c44
Revises: a3b7c2d91e40
Create Date: 2026-08-27
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation

import sqlalchemy as sa
from alembic import op

from rate_monitor.db.types import (
    MAX_QUANTITY,
    MAX_RATE,
    QUANTITY_DEC_DIGITS,
    QUANTITY_EXPONENT,
    QUANTITY_WIDTH,
    RATE_EXPONENT,
    RATE_WIDTH,
    Quantity,
    Rate,
)

revision: str = "3b8d1f6a2c44"
down_revision: str | None = "a3b7c2d91e40"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _decimal(raw: object) -> Decimal:
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise RuntimeError(f"market_indicators value를 Decimal로 읽지 못했다: {raw!r}") from exc
    if not value.is_finite() or value < 0 or value > MAX_QUANTITY:
        raise RuntimeError(f"Quantity 범위 밖의 기존 market indicator: {value}")
    return value


def _quantity_text(raw: object) -> tuple[Decimal, str]:
    value = _decimal(raw)
    quantized = value.quantize(QUANTITY_EXPONENT)
    if quantized != value:
        raise RuntimeError(
            f"기존 market indicator가 Quantity 6자리 정밀도를 초과한다: {value}"
        )
    return quantized, f"{quantized:0{QUANTITY_WIDTH}f}"


def _rate_text(raw: object) -> str:
    value = _decimal(raw)
    if value > MAX_RATE:
        raise RuntimeError(
            "Rate downgrade 범위를 넘는 market indicator가 있어 되돌릴 수 없다: "
            f"{value} > {MAX_RATE}"
        )
    quantized = value.quantize(RATE_EXPONENT)
    if quantized != value:
        raise RuntimeError(
            "Rate downgrade 4자리 정밀도로 lossless 변환할 수 없다: "
            f"{value} -> {quantized}"
        )
    return f"{quantized:0{RATE_WIDTH}f}"


def _new_hash(indicator_code: str, effective: object, value: Decimal, unit: str) -> str:
    canonical = f"{value:.{QUANTITY_DEC_DIGITS}f}"
    payload = f"{indicator_code}|{effective}|{canonical}|{unit}".encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def upgrade() -> None:
    bind = op.get_bind()
    rows = list(
        bind.execute(
            sa.text(
                "SELECT id, indicator_code, source_effective_at, value, unit "
                "FROM market_indicators ORDER BY id"
            )
        ).mappings()
    )

    # SQLite VARCHAR 길이는 강제되지 않으므로 기존 8자리 컬럼 안에서 먼저
    # 19자리 canonical text로 바꾼다. float/CAST를 거치지 않는다.
    for row in rows:
        numeric, storage = _quantity_text(row["value"])
        content_hash = _new_hash(
            str(row["indicator_code"]),
            row["source_effective_at"],
            numeric,
            str(row["unit"]),
        )
        bind.execute(
            sa.text(
                "UPDATE market_indicators "
                "SET value = :value, content_hash = :content_hash WHERE id = :id"
            ),
            {"value": storage, "content_hash": content_hash, "id": row["id"]},
        )

    with op.batch_alter_table("market_indicators") as batch_op:
        batch_op.alter_column(
            "value",
            existing_type=Rate(length=RATE_WIDTH),
            type_=Quantity(length=QUANTITY_WIDTH),
            existing_nullable=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    rows = list(bind.execute(sa.text("SELECT id, value FROM market_indicators ORDER BY id")).mappings())

    # 큰 잔액이나 5~6자리 소수가 한 건이라도 들어왔다면 조용히 잘라내지 않는다.
    # 운영 rollback은 이 migration 이전 snapshot 복원을 사용해야 한다.
    converted = [(row["id"], _rate_text(row["value"])) for row in rows]
    for row_id, storage in converted:
        bind.execute(
            sa.text("UPDATE market_indicators SET value = :value WHERE id = :id"),
            {"value": storage, "id": row_id},
        )

    with op.batch_alter_table("market_indicators") as batch_op:
        batch_op.alter_column(
            "value",
            existing_type=Quantity(length=QUANTITY_WIDTH),
            type_=Rate(length=RATE_WIDTH),
            existing_nullable=False,
        )
