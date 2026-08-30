import hashlib
import sqlite3
from decimal import Decimal

from rate_monitor.services.institution_funding_read_model_db import (
    build_institution_funding_read_model_from_db,
    load_funding_points,
)


def _sha256(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _funding_db(tmp_path):
    db = tmp_path / "publish.sqlite3"
    connection = sqlite3.connect(db)
    connection.execute(
        """
        CREATE TABLE institution_funding_observations (
            institution_id TEXT,
            sector TEXT NOT NULL,
            metric_code TEXT NOT NULL,
            valid_to TEXT,
            identity_status TEXT NOT NULL,
            source_effective_month TEXT NOT NULL,
            value TEXT NOT NULL
        )
        """
    )
    connection.executemany(
        """
        INSERT INTO institution_funding_observations
            (institution_id, sector, metric_code, valid_to, identity_status,
             source_effective_month, value)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                "a",
                "savings_bank",
                "deposit_liabilities_total",
                None,
                "mapped_exact_fss_code",
                "2025-06",
                "000000000080.000000",
            ),
            (
                "a",
                "savings_bank",
                "deposit_liabilities_total",
                None,
                "mapped_exact_fss_code",
                "2025-12",
                "000000000100.000000",
            ),
            (
                "a",
                "savings_bank",
                "deposit_liabilities_total",
                None,
                "mapped_exact_fss_code",
                "2026-06",
                "000000000120.000000",
            ),
            (
                "ignored",
                "savings_bank",
                "deposit_liabilities_total",
                None,
                "unmapped",
                "2026-06",
                "000000000999.000000",
            ),
        ],
    )
    connection.commit()
    connection.close()
    return db


def test_funding_db_adapter_preserves_snapshot_bytes(tmp_path) -> None:
    db = _funding_db(tmp_path)
    before = _sha256(db)

    points = load_funding_points(
        db,
        sector="savings_bank",
        analysis_month="2026-06",
    )

    assert _sha256(db) == before
    assert not (tmp_path / "publish.sqlite3-wal").exists()
    assert not (tmp_path / "publish.sqlite3-shm").exists()
    assert [(point.month, point.balance) for point in points] == [
        ("2025-06", Decimal("80.000000")),
        ("2025-12", Decimal("100.000000")),
        ("2026-06", Decimal("120.000000")),
    ]


def test_read_model_remains_functionally_equivalent_on_immutable_snapshot(tmp_path) -> None:
    db = _funding_db(tmp_path)
    before = _sha256(db)

    rows = build_institution_funding_read_model_from_db(
        db,
        sector="savings_bank",
        analysis_month="2026-06",
    )

    assert _sha256(db) == before
    assert len(rows) == 1
    assert rows[0].institution_id == "a"
    assert rows[0].balance == Decimal("120.000000")
    assert rows[0].change_6m_pct == Decimal("0.2")
    assert rows[0].change_12m_pct == Decimal("0.5")
