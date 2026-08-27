from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from rate_monitor.collectors.data_go_funding.collector import CONTRACTS
from rate_monitor.collectors.data_go_funding.history import (
    historical_months,
    latest_completed_reporting_month,
    shift_month,
    validate_month_key,
)
from rate_monitor.collectors.data_go_funding.history_audit import build_history_audit


def _contract(sector: str):
    return next(contract for contract in CONTRACTS if contract.sector == sector)


def test_historical_months_respects_source_cadence() -> None:
    savings = _contract("savings_bank")
    agri = _contract("nh_local")

    assert historical_months(savings, "2024-01", "2025-12") == [
        "202512",
        "202509",
        "202506",
        "202503",
        "202412",
        "202409",
        "202406",
        "202403",
    ]
    assert historical_months(agri, "202401", "202512") == [
        "202512",
        "202506",
        "202412",
        "202406",
    ]


def test_month_helpers_validate_and_shift() -> None:
    assert validate_month_key("2026-06") == "202606"
    assert shift_month("202601", -1) == "202512"
    assert latest_completed_reporting_month(
        _contract("savings_bank"),
        today=__import__("datetime").date(2026, 8, 28),
    ) == "202606"
    with pytest.raises(ValueError):
        validate_month_key("202613")
    with pytest.raises(ValueError):
        historical_months(_contract("nh_local"), "202507", "202505")


def _make_audit_db(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE institution_funding_observations (
            source_id TEXT NOT NULL,
            source_institution_key TEXT NOT NULL,
            metric_code TEXT NOT NULL,
            source_effective_month TEXT NOT NULL,
            valid_to TEXT,
            revision INTEGER NOT NULL,
            population_scope TEXT NOT NULL,
            identity_status TEXT NOT NULL
        );
        """
    )
    rows = []
    for month in ("2025-03", "2025-06", "2025-12", "2026-03", "2026-06"):
        rows.extend(
            [
                (
                    "data_go_savings_bank_funding",
                    "001",
                    "deposit_liabilities_total",
                    month,
                    None,
                    1,
                    "savings_banks_all_source_reported",
                    "mapped_exact_fss_code",
                ),
                (
                    "data_go_savings_bank_funding",
                    "002",
                    "deposit_liabilities_total",
                    month,
                    None,
                    1,
                    "savings_banks_all_source_reported",
                    "mapped_exact_fss_code",
                ),
            ]
        )
    connection.executemany(
        "INSERT INTO institution_funding_observations VALUES (?,?,?,?,?,?,?,?)",
        rows,
    )
    connection.commit()
    connection.close()


def test_history_audit_reports_missing_expected_month(tmp_path: Path) -> None:
    db_path = tmp_path / "audit.sqlite3"
    _make_audit_db(db_path)

    report = build_history_audit(db_path, windows=(24,))
    savings = report["sources"]["data_go_savings_bank_funding"]

    assert savings["available"] is True
    assert savings["latest_month"] == "2026-06"
    assert savings["latest_institutions"] == 2
    assert savings["duplicate_active_keys"] == 0
    assert "2025-09" in savings["continuity"]["24m"]["missing_months"]
