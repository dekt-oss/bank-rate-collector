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
                "b",
                "savings_bank",
                "deposit_liabilities_total",
                None,
                "mapped_dual_source",
                "2026-06",
                "000000000060.000000",
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
    assert [(point.institution_id, point.month, point.balance) for point in points] == [
        ("a", "2025-06", Decimal("80.000000")),
        ("a", "2025-12", Decimal("100.000000")),
        ("a", "2026-06", Decimal("120.000000")),
        ("b", "2026-06", Decimal("60.000000")),
    ]


def test_read_model_accepts_dual_source_identity_without_imputing_history(
    tmp_path,
) -> None:
    db = _funding_db(tmp_path)
    before = _sha256(db)

    rows = build_institution_funding_read_model_from_db(
        db,
        sector="savings_bank",
        analysis_month="2026-06",
    )

    assert _sha256(db) == before
    assert [row.institution_id for row in rows] == ["a", "b"]

    exact_row, dual_source_row = rows
    assert exact_row.balance == Decimal("120.000000")
    assert exact_row.change_6m_pct == Decimal("0.2")
    assert exact_row.change_12m_pct == Decimal("0.5")

    assert dual_source_row.balance == Decimal("60.000000")
    assert dual_source_row.balance_6m_ago is None
    assert dual_source_row.balance_12m_ago is None
    assert dual_source_row.change_6m_pct is None
    assert dual_source_row.change_12m_pct is None