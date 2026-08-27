"""Stage 0 market_indicators wide Quantity 저장계약."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from rate_monitor.db import models as m
from rate_monitor.db.types import (
    Quantity,
    QuantityPrecisionError,
    canonical_quantity_text,
    quantity_storage_text,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PRE_QUANTITY_REVISION = "f2c90d8e7a11"

OLD_SEVEN = (
    ("bok_bank_savings_deposit_rate", "2026-06-30", "003.0800", "percent"),
    ("bok_bank_pure_savings_deposit_rate", "2026-06-30", "003.0200", "percent"),
    ("bok_bank_term_deposit_1y_rate", "2026-06-30", "003.2600", "percent"),
    ("bok_savings_bank_deposit_balance", "2026-06-30", "100.3558", "trillion_krw"),
    ("bok_credit_union_deposit_balance", "2026-06-30", "140.3664", "trillion_krw"),
    ("bok_broad_mutual_finance_deposit_balance", "2026-06-30", "519.4273", "trillion_krw"),
    ("bok_kfcc_deposit_balance", "2026-06-30", "243.2478", "trillion_krw"),
)


def _alembic(command: str, db_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *command.split()],
        cwd=REPO_ROOT,
        env={
            **os.environ,
            "RATE_MONITOR_DB_URL": f"sqlite+pysqlite:///{db_path}",
            "PYTHONPATH": str(REPO_ROOT / "src"),
        },
        capture_output=True,
        text=True,
    )


def _seed_old_market_indicators(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        for index, (code, effective, value, unit) in enumerate(OLD_SEVEN):
            conn.execute(
                """
                INSERT INTO market_indicators (
                    id, indicator_code, indicator_name, source_id, observed_at,
                    source_effective_at, value, unit, raw_artifact_id,
                    source_locator, content_hash, validation_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"indicator-{index}",
                    code,
                    code,
                    "bok_ecos_macro",
                    "2026-08-27 00:00:00",
                    effective,
                    value,
                    unit,
                    f"artifact-{index}",
                    f"fixture/{code}",
                    f"sha256:legacy-{index}",
                    "valid",
                ),
            )
        conn.commit()
    finally:
        conn.close()


def _values(db_path: Path) -> dict[str, Decimal]:
    conn = sqlite3.connect(db_path)
    try:
        return {
            code: Decimal(str(value))
            for code, value in conn.execute(
                "SELECT indicator_code, value FROM market_indicators ORDER BY indicator_code"
            )
        }
    finally:
        conn.close()


def test_quantity_accepts_2000_trillion_without_float_roundtrip() -> None:
    assert quantity_storage_text(Decimal("2281.4891")) == "000000002281.489100"
    assert canonical_quantity_text(Decimal("2281.4891")) == "2281.489100"


def test_quantity_refuses_silent_precision_loss() -> None:
    with pytest.raises(QuantityPrecisionError):
        quantity_storage_text(Decimal("1.1234567"))


def test_market_indicator_model_uses_quantity_but_product_rates_stay_rate() -> None:
    market_type = m.MarketIndicator.__table__.c.value.type
    base_rate_type = m.RateObservation.__table__.c.base_rate.type

    assert isinstance(market_type, Quantity)
    assert market_type.impl.length == 19
    assert base_rate_type.impl.length == 8


def test_quantity_migration_preserves_existing_seven_numeric_values(tmp_path: Path) -> None:
    db_path = tmp_path / "quantity-migration.sqlite3"
    before_upgrade = _alembic(f"upgrade {PRE_QUANTITY_REVISION}", db_path)
    assert before_upgrade.returncode == 0, before_upgrade.stderr
    _seed_old_market_indicators(db_path)
    before = _values(db_path)

    result = _alembic("upgrade head", db_path)
    assert result.returncode == 0, result.stderr
    after = _values(db_path)

    assert after == before
    assert len(after) == len(OLD_SEVEN)
    conn = sqlite3.connect(db_path)
    try:
        raw = conn.execute(
            "SELECT value, typeof(value) FROM market_indicators "
            "WHERE indicator_code='bok_bank_term_deposit_1y_rate'"
        ).one()
        market_decl = conn.execute("PRAGMA table_info(market_indicators)").fetchall()
        rate_decl = conn.execute("PRAGMA table_info(rate_observations)").fetchall()
    finally:
        conn.close()
    assert raw == ("000000000003.260000", "text")
    assert next(row[2] for row in market_decl if row[1] == "value") == "VARCHAR(19)"
    assert next(row[2] for row in rate_decl if row[1] == "base_rate") == "VARCHAR(8)"


def test_quantity_migration_can_downgrade_losslessly_before_large_values(tmp_path: Path) -> None:
    db_path = tmp_path / "quantity-downgrade.sqlite3"
    assert _alembic(f"upgrade {PRE_QUANTITY_REVISION}", db_path).returncode == 0
    _seed_old_market_indicators(db_path)
    assert _alembic("upgrade head", db_path).returncode == 0

    result = _alembic(f"downgrade {PRE_QUANTITY_REVISION}", db_path)
    assert result.returncode == 0, result.stderr

    conn = sqlite3.connect(db_path)
    try:
        raw = conn.execute(
            "SELECT value FROM market_indicators "
            "WHERE indicator_code='bok_bank_term_deposit_1y_rate'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert raw == "003.2600"


def test_quantity_downgrade_fails_closed_after_large_balance_is_stored(tmp_path: Path) -> None:
    db_path = tmp_path / "quantity-no-lossy-downgrade.sqlite3"
    assert _alembic("upgrade head", db_path).returncode == 0

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO market_indicators (
                id, indicator_code, indicator_name, source_id, observed_at,
                source_effective_at, value, unit, raw_artifact_id,
                content_hash, validation_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "large",
                "bok_bank_total_deposit_balance",
                "예금은행 총예금(말잔)",
                "bok_ecos_macro",
                "2026-08-27 00:00:00",
                "2026-06-30",
                "000000002281.489100",
                "trillion_krw",
                "artifact-large",
                "sha256:large",
                "valid",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    result = _alembic(f"downgrade {PRE_QUANTITY_REVISION}", db_path)
    assert result.returncode != 0
    assert "Rate downgrade 범위를 넘는" in result.stderr
